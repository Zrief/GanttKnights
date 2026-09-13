"""渲染服务 —— 把同步的「取数 + 渲染」内核接到 asyncio 上（见 docs/插件化路线.md §5.5/§5.6/§5.7、§7）。

五件事：

1. **不阻塞事件循环**：matplotlib 渲染是秒级 CPU 占用，`src/获取_prts.py` 又是同步
   `httpx`——整个流程统一塞进 `asyncio.to_thread`。因此本模块顶层**不 import matplotlib**，
   它只在工作线程里被拖进来（冷缓存实测 1139ms，同步导入会让事件循环停半秒以上）。
2. **单飞锁**：同一时刻只允许一次「刷新 + 签名 + 渲染」，后到的请求在锁上等，
   拿到锁后靠**签名缓存**命中，不会重复画同一张图。
3. **签名缓存**（阶段四，取代阶段三的"复用窗口"）：判定与落盘全在 `插件/缓存.py`；
   本模块负责"先刷新数据、再定背景、再算签名"的顺序——**顺序不能反**，
   因为数据内容与背景图片文件都是签名的一部分。
4. **交付**：发出去的是 `渲染缓存/渲染_<签名>.jpg` 那张**按签名命名、写完就不再改**的图；
   另用原子替换同步一份到 `settings.output_path`（`Gantt.jpg`，给人看 / 给 README），
   警告文件也同步刷新。不把发送路径指向 `Gantt.jpg`：宿主是在**发送那一刻**才把本地文件
   读成 base64 的，而 `Gantt.jpg` 会被后续请求覆盖 → 并发时可能发出"别人的图"或半张图。
5. **Agg 后端 + 可写 MPLCONFIGDIR**：插件环境没有显示器，且默认缓存目录在容器/只读环境里
   不可写。MPLCONFIGDIR 必须在 matplotlib **首次导入之前**设好，所以路径准备在
   `准备matplotlib环境()`（构造期调用，只设环境变量），`use("Agg")` 在工作线程里执行。

### 随机背景 × 缓存：按自然日确定性抽签

`_背景路径()` 不是每次请求都 `random.choice`，而是 **`候选[crc32(日期) % 张数]`**——
同一天恒定抽到同一张，换一天才换。三个好处（2026-09-14 审查 + 讨论）：

* **预判与真判定永远一致**：`查现成图()` 与锁内的 `_同步出图()` 拿到的是同一张背景，
  于是"不发请稍候"的请求不会突然静默渲染 1.3s（审查实测：每次重抽时 8 张背景会分叉 4/40，
  最坏接近 (k−1)/k）；
* **同一天只有一张图**：缓存语义从"每天最多 k 张"收敛成"每天 1 张（数据/配置不变时）"；
* **不再复读**：随机重抽时"连发两次得到同一张图"很常见，按日抽签下"换一张"就是换一天。

代价：用户没法靠"再发一次"换背景（想换就改 `background_file` 指定一张，或换一天再看）。
真正"每次都要新图"的语义留给将来的 `/甘特图换背景`。
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

        ⚠️ **只有锁内的 `_同步出图()` 调用它**。入口层的只读预判（`更新计划()` / `查现成图()`）
        一律用 `内核设置()` 现造一份 Settings——否则事件循环里的预判会在渲染进行到一半时
        改写工作线程正在读的全局（用户此刻若刚改过配置，A 请求的画面上会混进 B 请求的窗口参数）。
        """
        设置 = self.内核设置(运行配置)
        for 字段 in fields(Settings):
            setattr(内核设置, 字段.name, getattr(设置, 字段.name))
        return 设置

    # ==================== 出图前的检查与判断 ====================

    def 素材问题(self, 运行配置: 运行配置) -> Path | None:
        """出图前的素材体检：返回"不可出图"的原因（目前只会是背景图目录为空）。

        内核的 `挑选背景图()` 在目录为空时 `SystemExit(1)`——那是给 CLI 用的
        （进程退出码），在插件里会穿透 `to_thread` 变成杀掉任务链的 BaseException
        （`SystemExit` 不是 `Exception` 子类，入口层的 `except Exception` 拦不住）。
        所以这里提前拦下换成一句人话，`_同步出图()` 里还有第二道 RuntimeError 兜底。
        """
        if 运行配置.指定背景:
            return None
        目录 = Path(self.内核设置(运行配置).bg_dir)
        候选 = [p for p in 目录.glob("*") if p.is_file()] if 目录.is_dir() else []
        return None if 候选 else 目录

    @staticmethod
    def _新鲜度(现在时间: datetime, 设置: Settings) -> tuple[bool, bool]:
        """(活动数据该抓吗, 首页预告该抓吗)。两者各按自己的"今天写过"判断：

        活动数据是 CSV（由 `更新数据` 写），首页预告是 `新增预告.json`（由 `更新增预告` 写）。
        分开判断才能修掉阶段三的漏洞——"CSV 是今天的"曾让**没抓成的预告**一整天不再重试。
        """
        return (not 今天写过(Path(设置.all_data_path), 现在时间),
                not 今天写过(Path(设置.new_items_path), 现在时间))

    def 更新计划(self, 现在时间: datetime, 运行配置: 运行配置) -> tuple[bool, bool]:
        """本次出图要联网抓什么（入口层用它决定先发哪句"请稍候"）。

        只读：用 `内核设置()` 现造一份，**不动**内核全局 `settings`
        （全局只由锁内的 `_同步出图()` 写，见 `应用设置()` 的说明）。
        """
        if not 运行配置.每日自动更新:
            return (False, False)
        return self._新鲜度(现在时间, self.内核设置(运行配置))

    def 查现成图(self, 现在时间: datetime, 运行配置: 运行配置) -> bool:
        """**只**用来决定要不要先发一句"请稍候"：只读盘、不写盘、不取锁。

        真正的判定在 `出图()` 的锁内重做一次。背景按自然日确定性抽签（`_背景路径()`），
        所以这里的"抽到哪张"与锁内那次**必然相同**——不会出现"预判说有、实际却静默渲染"
        （审查实测过每次重抽的版本：8 张背景 40 次请求分叉 4/40）。
        剩下的分叉余地只有"两次调用之间数据被别的请求改了"，那本来也该重画。
        """
        try:
            设置 = self.内核设置(运行配置)      # 只读，不改全局 settings
            if 运行配置.每日自动更新 and any(self._新鲜度(现在时间, 设置)):
                return False            # 马上要联网刷新数据 → 现有缓存多半会作废
            背景路径 = self._背景路径(运行配置, 设置, 现在时间)
            if 背景路径 is None:
                return False
            签名 = self.缓存.算签名(运行配置, 现在时间, 设置, 背景路径)
            return self.缓存.查(签名, 现在时间) is not None
        except Exception:
            logger.exception("预查缓存失败（按未命中处理）")
            return False

    @staticmethod
    def 产物可用(图片路径: str | Path) -> bool:
        """临发图前的最后一道校验：文件头魔数完整（截断的 JPEG 不发给用户）"""
        return 图是完整的(图片路径)

    # ==================== 出图 ====================

    async def 出图(
        self,
        *,
        现在时间: datetime,
        运行配置: 运行配置,
        自动更新: bool = True,
        强制刷新: bool = False,
    ) -> 渲染结果:
        """出图：锁内「刷新数据 → 选背景 → 算签名 → 命中就复用，否则渲染并入缓存」。

        `自动更新` 是"允许本次联网刷新"（数据是否真抓由 `_新鲜度()` 按文件决定）；
        `强制刷新=True` 则跳过缓存读取、且无条件重抓活动数据与首页预告。
        """
        async with self._锁:
            return await asyncio.to_thread(
                self._同步出图, 现在时间, 运行配置, 自动更新, 强制刷新
            )

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
            raise RuntimeError(f"背景图目录里没有可用图片：{设置.bg_dir}")

        # ④ 算签名 → 查缓存
        签名 = self.缓存.算签名(运行配置, 现在时间, 设置, 背景路径)
        if not 强制刷新:
            条目 = self.缓存.查(签名, 现在时间)
            if 条目 is not None:
                logger.info("命中渲染缓存（生成于 %s）：%s", 条目.生成时刻, 条目.图片)
                return self._交付(self._结果自条目(条目), 设置)

        # ⑤ 真画一张：直接画进缓存目录，校验魔数完整后再登记、再交付
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
        """按新鲜度抓活动数据 / 首页预告；抓取失败只记日志，沿用上次数据继续出图。"""
        需数据, 需预告 = (True, True) if 强制 else self._新鲜度(现在时间, 设置)
        if 需数据:
            更新数据(现在字符串)
        if 需预告:
            try:
                更新增预告(现在时间, 现在字符串)
            except Exception:
                logger.exception("新增预告获取失败（沿用上次数据）")

    def _交付(self, 结果: 渲染结果, 设置: Settings) -> 渲染结果:
        """把产物同步一份到 `settings.output_path`，并刷新警告文件；**返回原结果**。

        发出去的一直是 `结果.图片路径`——命中缓存时是缓存图，新画时也是缓存图（都是
        `渲染缓存/渲染_<签名>.jpg`，写完就不再改）。`Gantt.jpg` 只是给人看/给 README 的
        副本：宿主在**发送那一刻**才读文件成 base64，把发送路径指向会被后续请求覆盖的
        `Gantt.jpg`，并发时就可能发出"别人的图"或半张图（审查建议 4 + 讨论 D4）。

        两步都是"尽力而为"：复制/写警告失败只记日志，不影响这次把图发出去。
        """
        目标 = Path(设置.output_path)
        来源 = Path(结果.图片路径)
        try:
            if 来源.resolve() != 目标.resolve():
                自建 = self._同步一份(来源, 目标)
                logger.info("产物已同步到 %s（%s）", 目标, "新写" if 自建 else "校验后跳过")
        except OSError:
            logger.exception("同步产物到 %s 失败（不影响发图）", 目标)
        try:
            if 结果.警告:
                Path(设置.warning_path).write_text(结果.警告, encoding="utf-8")
        except OSError:
            logger.exception("写入警告文件失败：%s", 设置.warning_path)
        return 结果

    @staticmethod
    def _同步一份(来源: Path, 目标: Path) -> bool:
        """把 `来源` 原子地写成 `目标`（同目录临时文件 + `os.replace`）。

        非原子的 `copyfile` 会被"发送那一刻才读文件"的宿主读到半张 JPEG；
        内容已相同则跳过（省一次 300KB 写盘）。返回是否真的写了。
        """
        if 目标.exists() and 目标.stat().st_size == 来源.stat().st_size:
            旧 = 目标.read_bytes()
            if 旧 == 来源.read_bytes():
                return False
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
        return True

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

        - 指定了文件名/绝对路径 → 用它；
        - 否则开随机 → 按**自然日**确定性抽签：`候选[crc32(日期) % 张数]`
          （同一天恒定同一张，见模块 docstring 的三条理由）；
        - 否则固定取目录里第一张（出图可复现）。
        """
        if 运行配置.指定背景:
            指定 = Path(运行配置.指定背景)
            return str(指定 if 指定.is_absolute() else Path(设置.bg_dir) / 指定)
        候选 = sorted(p for p in Path(设置.bg_dir).glob("*") if p.is_file())
        if not 候选:
            return None
        if not 运行配置.随机背景:
            return str(候选[0])
        种子 = zlib.crc32(现在时间.date().isoformat().encode("utf-8"))
        return str(候选[种子 % len(候选)])
