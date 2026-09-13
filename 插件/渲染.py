"""渲染服务 —— 把同步的「取数 + 渲染」内核接到 asyncio 上（见 docs/插件化路线.md §5.5~§5.7、§7）。

四件事：

1. **不阻塞事件循环**：matplotlib 渲染是秒级 CPU 占用，`src/获取_prts.py` 又是同步
   `httpx`——整个流程统一塞进 `asyncio.to_thread`。因此本模块顶层**不 import matplotlib**，
   它只在工作线程里被拖进来（冷缓存实测 1139ms，同步导入会让事件循环停半秒以上）。
2. **单飞锁**：同一时刻只允许一次「刷新 + 签名 + 渲染」，后到的请求在锁上等，
   拿到锁后靠**签名缓存**命中，不会重复画同一张图。
3. **签名缓存**（阶段四）：判定与落盘全在 `插件/缓存.py`；本模块负责
   "先刷新数据、再定背景、再算签名"的顺序——**顺序不能反**，因为数据内容与背景图片都是签名的一部分。
4. **交付**：发出去的是 `渲染缓存/渲染_<签名>.jpg` 那张**按签名命名、写完就不再改**的图；
   另用原子替换同步一份到 `settings.output_path`（`Gantt.jpg`，给人看 / 给 README）。
   不把发送路径指向 `Gantt.jpg`：宿主是在**发送那一刻**才把本地文件读成 base64 的，
   而 `Gantt.jpg` 会被后续请求覆盖 → 并发时可能发出"别人的图"或半张图。

**对外的面只有三个**：`准备matplotlib环境()`（构造期）、`出图()`、`产物可用()`。
其余（背景怎么选、数据要不要刷、缓存怎么算）都是内部细节——入口层没有别的判断要做，
做一份"提前预判"只会多一条与真判定分叉的路径（阶段四审查实测过分叉代价：静默慢渲染）。

### 背景：按自然日确定性抽签

指定了 `background_file` 就用它；否则 **`候选[crc32(日期) % 张数]`**——同一天恒定一张，换天才换。
于是"同一份数据 + 同一天"在签名上就是一张图、只会渲染一次，
也不会出现"连发两次得到同一张"之类的随机观感问题。用户想立刻换背景就显式指定一张。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import zlib
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from ..src.config import Settings, settings as 内核设置
from ..src.流水线 import 今天写过, 更新增预告, 更新数据, render_once
from ..src.流水线 import 渲染结果
from .配置 import 运行配置
from .缓存 import 图是完整的, 缓存条目, 渲染缓存

logger = logging.getLogger("ganttknights")


class 素材缺失(RuntimeError):
    """画图必需的素材缺失：背景图目录为空，**或**指定的那张背景图不存在。

    单独一个类型是为了让入口层把它翻译成**给用户看的一句话**，而不是"渲染失败"。
    内核的 `挑选背景图()` 在目录为空时 `SystemExit(1)`——那是给 CLI 用的（进程退出码），
    在插件里会穿透 `to_thread` 变成杀掉任务链的 BaseException（`SystemExit` 不是 `Exception`
    子类，入口层的 `except Exception` 拦不住），所以必须在这里换成普通异常。
    """

    def __init__(self, 目录: Path, 文件: str = "") -> None:
        super().__init__(f"背景图不可用：{文件 or 目录}")
        self.目录 = 目录
        self.文件 = 文件


class 渲染服务:
    """按插件侧路径与配置驱动内核；同一实例可被多个会话共享。"""

    def __init__(self, 插件目录: Path, 数据目录: Path,
                 额外字体: dict[str, str] | None = None) -> None:
        self.插件目录 = Path(插件目录)
        self.数据目录 = Path(数据目录)
        # AstrBot 文档化的自定义字体插槽（data/font.ttf 等），由入口层按实例路径算好传进来；
        # 内核不认识 AstrBot，只收"角色 → 文件"。
        self.额外字体 = 额外字体 or None
        self.缓存 = 渲染缓存(self.数据目录)
        # 锁在事件循环里首次使用时才绑定循环（Python 3.10+ 的 Lock 不再在构造期绑定），
        # 这里构造于插件加载期也安全。
        self._锁 = asyncio.Lock()

    # ==================== 环境与设置 ====================

    def 准备matplotlib环境(self) -> Path:
        """准备 matplotlib 的缓存目录（只设环境变量，不 import matplotlib）。

        > 注意：`MPLCONFIGDIR` 只在 matplotlib **首次导入**时被读取。若宿主进程已经
        > 导入过 matplotlib，这里改的只是给"还没导入"的场景兜底——`use("Agg")` 仍然有效。
        """
        目录 = self.数据目录 / "mplconfig"
        目录.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(目录)
        return 目录

    def 内核设置(self, 运行配置: 运行配置) -> Settings:
        """插件侧路径 + 数值配置 → 内核 Settings。

        - 数据（CSV/预告/图标缓存/警告/产物）全在 `data/plugin_data/<插件名>/`
          ——用户数据与代码分离，升级插件不覆盖；
        - 素材（字体/背景图）默认在插件目录内只读；背景图可被配置指到别处（插件升级不会覆盖）；
        - 字体不在插件配置里暴露：自定义走插件目录 `字体/` 或 AstrBot 的 `data/font*.ttf` 约定；
        - 时间窗来自插件配置，用户一改就生效（签名里含这些值，旧缓存自动失效）。
        """
        return Settings(
            数据目录=self.数据目录,
            素材目录=self.插件目录,
            output_path=str(self.数据目录 / "Gantt.jpg"),
            bg_dir=运行配置.背景目录 or None,
            额外字体=self.额外字体,
            left_offset_days=运行配置.左边界天数,
            right_offset_days=运行配置.右边界天数,
        )

    def 应用设置(self, 运行配置: 运行配置) -> Settings:
        """把内核的全局 `settings` 就地改成插件这份，并返回它。

        内核各模块（`流水线` / `筛选_活动` / `字体` / `绘图_*`）都在**调用时**读全局
        `settings`（阶段一保证过没有模块级取值），所以就地覆盖即可，无需给每个函数加参数。
        代价是进程级全局状态：CLI 与插件不会同时跑，互不影响。

        ⚠️ 只有**工作线程里、锁内**的 `_同步出图()` 调用它，事件循环从不写全局。
        """
        设置 = self.内核设置(运行配置)
        for 字段 in fields(Settings):
            setattr(内核设置, 字段.name, getattr(设置, 字段.name))
        return 设置

    # ==================== 出图 ====================

    async def 出图(
        self,
        *,
        现在时间: datetime,
        运行配置: 运行配置,
        自动更新: bool = True,
        强制刷新: bool = False,
    ) -> 渲染结果:
        """出图：锁内「刷新数据 → 清理缓存 → 选背景 → 算签名 → 命中就复用，否则渲染并入缓存」。

        抛出 `素材缺失` 表示"没有背景图，画不了"；其余失败由 `render_once()` 自己吞掉并记日志
        （入口层用 `产物可用()` 兜底判断）。
        """
        async with self._锁:
            return await asyncio.to_thread(
                self._同步出图, 现在时间, 运行配置, 自动更新, 强制刷新
            )

    @staticmethod
    def 产物可用(图片路径: str | Path) -> bool:
        """临发图前的最后一道校验：文件头魔数完整（截断的 JPEG 不发给用户）"""
        return 图是完整的(图片路径)

    def 缓存概况(self) -> dict:
        """缓存目录的现状（给 `/甘特图状态` 用）：条数 / 占用 / 最新一条的生成时刻。"""
        return self.缓存.概况()

    # ==================== 工作线程里做的事 ====================

    def _同步出图(
        self,
        现在时间: datetime,
        运行配置: 运行配置,
        自动更新: bool,
        强制刷新: bool,
    ) -> 渲染结果:
        self._启用Agg()
        设置 = self.应用设置(运行配置)
        现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")

        # ① 数据新鲜度：活动数据与首页预告各管各的，同一天里各只抓一次
        if 自动更新 or 强制刷新:
            self._刷新数据(现在时间, 现在字符串, 设置, 强制=强制刷新)

        # ② 收拾一下缓存目录：过期条目 / 损坏图片 / 没人认领的散图（只在锁内、出图路径上做）
        try:
            self.缓存.清理(现在时间)
        except Exception:
            logger.exception("清理渲染缓存失败（不影响本次出图）")

        # ③ 定下"用哪张背景"：它既决定整套配色，也是签名的一部分（§7）
        背景路径 = self._背景路径(运行配置, 设置, 现在时间)
        if 背景路径 is None:
            raise 素材缺失(Path(设置.bg_dir))

        # ④ 算签名 → 查缓存
        签名 = self.缓存.算签名(运行配置, 现在时间, 设置, 背景路径)
        if not 强制刷新:
            条目 = self.缓存.查(签名, 现在时间)
            if 条目 is not None:
                logger.info("命中渲染缓存（生成于 %s）：%s", 条目.生成时刻, 条目.图片)
                return self._交付(self._结果自条目(条目), 设置)

        # ⑤ 真画一张：直接画进缓存目录，校验完整后再登记、再交付
        缓存图 = self.缓存.图片路径(签名)
        结果 = render_once(
            现在时间=现在时间,
            强制刷新=False,   # 刷新已在 ① 做过（render_once 的强制刷新就是这两件事，别抓两遍）
            输出路径=缓存图,
            背景路径=背景路径,
            标题=运行配置.标题,
            提醒天数=运行配置.提醒天数,
            底栏分区=运行配置.底栏分区(),
            控制台打印警告=False,   # 插件里警告随图走，不打到 stdout
        )
        if not 图是完整的(缓存图):
            logger.error("渲染未产出完整图片，按失败处理：%s", 缓存图)
            return 结果        # 入口层会报"渲染失败"，不会把这张图发出去
        try:
            self.缓存.存入(签名, 结果, 现在时间)
        except OSError:
            # 缓存写不进去（磁盘满/只读/被占）不该毁掉一张**已经画好且完整**的图：
            # 记录一句，照常交付（2026-09-14 审查实测过这条失败路径）
            logger.exception("写入渲染缓存失败（不影响本次交付）：%s", 缓存图)
        return self._交付(结果, 设置)

    def _刷新数据(self, 现在时间: datetime, 现在字符串: str,
                  设置: Settings, *, 强制: bool) -> None:
        """按新鲜度抓活动数据 / 首页预告；抓取失败只记日志，沿用上次数据继续出图。

        两者各按自己的"今天写过"判断（活动数据是 CSV、首页预告是 `新增预告.json`）：
        分开判断才能避免"CSV 是今天的"让**没抓成的预告**一整天不再重试。
        """
        需数据, 需预告 = (True, True) if 强制 else (
            not 今天写过(Path(设置.all_data_path), 现在时间),
            not 今天写过(Path(设置.new_items_path), 现在时间),
        )
        if 需数据:
            更新数据(现在字符串)
        if 需预告:
            try:
                更新增预告(现在时间, 现在字符串)
            except Exception:
                logger.exception("新增预告获取失败（沿用上次数据）")

    def _交付(self, 结果: 渲染结果, 设置: Settings) -> 渲染结果:
        """把产物同步一份到 `settings.output_path`，并刷新警告文件；**返回原结果**。

        发出去的一直是 `结果.图片路径`（缓存图，写完不再改）。`Gantt.jpg` 只是给人看/给
        README 的副本，用原子替换写——宿主在发送那一刻才读文件，指向会被覆盖的文件
        就可能发出别人的图或半张图。

        两步都是"尽力而为"：复制/写警告失败只记日志，不影响这次把图发出去。
        """
        目标 = Path(设置.output_path)
        来源 = Path(结果.图片路径)
        try:
            if 来源.resolve() != 目标.resolve():
                self._原子复制(来源, 目标)
        except OSError:
            logger.exception("同步产物到 %s 失败（不影响发图）", 目标)
        try:
            if 结果.警告:
                Path(设置.warning_path).write_text(结果.警告, encoding="utf-8")
        except OSError:
            logger.exception("写入警告文件失败：%s", 设置.warning_path)
        return 结果

    @staticmethod
    def _原子复制(来源: Path, 目标: Path) -> None:
        """同目录临时文件 + `os.replace`。

        不做"内容相同就跳过"：那要读两份文件（~600KB）才能省一次写（~300KB），
        净亏 I/O——第一性原理上这是负优化（2026-09-14 复盘删掉了它）。
        """
        目标.parent.mkdir(parents=True, exist_ok=True)
        fd, 临时 = tempfile.mkstemp(dir=str(目标.parent), prefix=".gantt-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as 出:
                with 来源.open("rb") as 入:
                    shutil.copyfileobj(入, 出)
                os.fsync(出.fileno())
            os.replace(临时, 目标)
        finally:
            if os.path.exists(临时):
                os.unlink(临时)

    @staticmethod
    def _结果自条目(条目: 缓存条目) -> 渲染结果:
        """manifest 里的概要 → 渲染结果（命中缓存时入口层拿到的东西与新画时同型）"""
        return 渲染结果(
            图片路径=Path(条目.图片),
            概况=条目.概况,
            警告=条目.警告,
            标题=条目.标题,
            条目数=条目.条目数,
            名称数=条目.名称数,
            分区计数=dict(条目.分区计数),
        )

    @staticmethod
    def _启用Agg() -> None:
        """切无头后端。必须在任何 pyplot 导入之前调用（内核的 matplotlib 导入发生在其后）。"""
        import matplotlib

        matplotlib.use("Agg", force=True)

    @staticmethod
    def _背景路径(运行配置: 运行配置, 设置: Settings, 现在时间: datetime) -> str | None:
        """定下这次用哪张背景图（**一定是具体路径**，签名要用它；目录空则 None）。

        - 指定了文件名/绝对路径 → 用它（**必须真的存在**：写错文件名要给一句人话，
          而不是让内核拿着一支不存在的图去画——内核在背景读不到时会退回默认配色，
          结果是一张"没人看得出哪里错"的图）；
        - 否则按**自然日**抽签：`候选[crc32(日期) % 张数]`（同一天恒定一张，见模块 docstring）。
        """
        if 运行配置.指定背景:
            指定 = Path(运行配置.指定背景)
            路径 = 指定 if 指定.is_absolute() else Path(设置.bg_dir) / 指定
            if not 路径.is_file():
                raise 素材缺失(路径.parent, 文件=str(路径))
            return str(路径)
        候选 = sorted(p for p in Path(设置.bg_dir).glob("*") if p.is_file())
        if not 候选:
            return None
        种子 = zlib.crc32(现在时间.date().isoformat().encode("utf-8"))
        return str(候选[种子 % len(候选)])
