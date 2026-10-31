"""渲染服务 —— 把同步的「取数 + 渲染」内核接到 asyncio 上（见 docs/插件化.md「接上宿主」）。

三件事：

1. **不阻塞事件循环**：matplotlib 渲染是秒级 CPU 占用，`src/获取_prts.py` 又是同步
   `httpx`——整个流程统一塞进 `asyncio.to_thread`。因此本模块顶层**不 import matplotlib**，
   它只在工作线程里被拖进来（冷缓存实测 1139ms，同步导入会让事件循环停半秒以上）。
2. **单飞锁**：同一时刻只允许一次「刷新数据 + 渲染」。锁不是缓存——它保护的是**可变的内核全局
   `settings`**（`应用设置()` 就地改写）与"两个请求同时写同一个产物文件"。
   并发请求会排队（第一个 1.5s，第二个再 1.5s），这是**有意接受**的：性能在这个产品里不重要
   （「两次自我推翻」），换掉的是整套签名缓存与它带来的 8 类 bug。
3. **按需渲染，不留缓存**：请求来就画，直接原子落到 `settings.output_path`（`Gantt.jpg`）。
   每天真正有价值的信息是"和昨天比变了什么"，那由**抓取时的合并动作**回答
   （`src/汇总_活动.py::合并差异` → `src/数据变化.py` 落盘 → `渲染结果.变化`），
   而不是靠复用昨天的图。

### 背景：按日期顺序轮换

指定了 `background_file` 就用它（且必须真的存在）；否则按日期顺序轮换背景图。
同一天保持同一张，换天后切换到下一张，避免同一天重复出图时背景和配色变化。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path

from ..src.config import Settings, settings as 内核设置
from ..src.流水线 import 今天写过, 更新增预告, 更新数据, render_once
from ..src.流水线 import 渲染结果
from .配置 import 运行配置
from ..src.日志 import logger

魔数长度 = 8
_JPEG魔数 = b"\xff\xd8\xff"
_PNG魔数 = b"\x89PNG\r\n\x1a\n"


def 图是完整的(路径: Path | str) -> bool:
    """只读文件头 8 字节判魔数：截断/空的产物不发给用户（比整图解码便宜 300 倍）。"""
    try:
        with Path(路径).open("rb") as f:
            头 = f.read(魔数长度)
    except OSError:
        return False
    return 头.startswith(_JPEG魔数) or 头.startswith(_PNG魔数)


class 素材缺失(RuntimeError):
    """画图必需的素材缺失：背景图目录为空，**或**指定的那张背景图不存在。

    单独一个类型是为了让入口层把它翻译成**给用户看的一句话**，而不是"渲染失败"。
    插件侧在调内核之前就定下"用哪张背景"（`_背景路径()`），拿不到时换成这里的 `素材缺失`，
    不让内核的 `背景图缺失` 冒到事件循环上——那是普通异常，但在 `to_thread` 里冒泡等于任务失败。
    """

    def __init__(self, 目录: Path, 文件: str = "") -> None:
        super().__init__(f"背景图不可用：{文件 or 目录}")
        self.目录 = 目录
        self.文件 = 文件


class 字体缺失(RuntimeError):
    """环境里连一支能画中文的字体都没有（典型：早期官方 Docker 镜像）。

    与 素材缺失 同一套路：调内核前自查（`_同步出图` ②），把内核的
    `src.字体.字体缺失` 换成插件侧类型，入口层翻译成修法指引——
    否则内核会静默画出一张豆腐图发进群（2026-10 Docker issue 实例）。
    """


class 渲染服务:
    """按插件侧路径与配置驱动内核；同一实例可被多个会话共享。"""

    def __init__(self, 插件目录: Path, 数据目录: Path,
                 额外字体: dict[str, str] | None = None) -> None:
        self.插件目录 = Path(插件目录)
        self.数据目录 = Path(数据目录)
        # AstrBot 文档化的自定义字体插槽（data/font.ttf 等），由入口层按实例路径算好传进来；
        # 内核不认识 AstrBot，只收"角色 → 文件"。
        self.额外字体 = 额外字体 or None
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

        - 数据（CSV/预告/图标缓存/警告/产物/最近数据变化记录）全在 `data/plugin_data/<插件名>/`
          ——用户数据与代码分离，升级插件不覆盖；
        - 素材（字体/背景图）默认在插件目录内只读；背景图可被配置指到别处（插件升级不会覆盖）；
        - 字体不在插件配置里暴露：自定义走插件目录 `字体/` 或 AstrBot 的 `data/font*.ttf` 约定；
        - 时间窗来自插件配置，用户一改就生效。
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
        回溯已结束: bool = False,
    ) -> 渲染结果:
        """出图：锁内「刷新数据 → 记录/对比日差 → 选背景 → 渲染 → 原子落到 Gantt.jpg」。

        抛出 `素材缺失` 表示"没有背景图，画不了"；其余失败由 `render_once()` 自己吞掉并记日志
        （入口层用 `产物可用()` 兜底判断）。依赖问题不会走到这里——`main.py` 在导入期就
        `import matplotlib`，缺依赖时插件根本加载不起来，宿主会先把依赖装上（「装得上、上得了架」）。

        """
        async with self._锁:
            return await asyncio.to_thread(
                self._同步出图, 现在时间, 运行配置, 自动更新, 强制刷新, 回溯已结束
            )

    @staticmethod
    def 产物可用(图片路径: str | Path) -> bool:
        """临发图前的最后一道校验：文件头魔数完整（截断的 JPEG 不发给用户）"""
        return 图是完整的(图片路径)

    def 最近变化日期(self) -> str:
        """最近一次数据合并的日期（给 `/方舟日程 状态` 用）；没有则空串"""
        from ..src.数据变化 import 读, 默认路径

        记录 = 读(默认路径(self.数据目录))
        return 记录.日期 if 记录 is not None else ""

    # ==================== 工作线程里做的事 ====================

    def _同步出图(
        self,
        现在时间: datetime,
        运行配置: 运行配置,
        自动更新: bool,
        强制刷新: bool,
        回溯已结束: bool = False,
    ) -> 渲染结果:
        self._启用Agg()
        设置 = self.应用设置(运行配置)
        现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")

        # ① 数据新鲜度：活动数据与首页预告各管各的，同一天里各只抓一次
        if 自动更新 or 强制刷新:
            self._刷新数据(现在时间, 现在字符串, 设置, 强制=强制刷新, 回溯已结束=回溯已结束)

        # ② 定下"用哪张背景"：它决定整套配色（素材缺失在这里抛出）
        背景路径 = self._背景路径(运行配置, 设置, 现在时间)
        if 背景路径 is None:
            raise 素材缺失(Path(设置.bg_dir))

        # ②.5 字体自查：三层候选全落空时内核只会画豆腐图，这里提前一步拦下、
        # 换成给用户的修法指引。延迟 import——本模块顶层不碰 matplotlib（秒级开销）
        from ..src.字体 import 注册字体
        from ..src.字体 import 字体缺失 as 内核字体缺失
        try:
            注册字体()
        except 内核字体缺失 as exc:
            raise 字体缺失(str(exc))

        # ③ 画进临时文件，校验完整后**原子替换**到正式产物路径。
        #    直接写 Gantt.jpg 的话，宿主"发送那一刻"可能读到半张图（它是在发送时才读文件的）。
        目标 = Path(设置.output_path)
        临时 = 目标.with_suffix(f".tmp{目标.suffix}")
        结果 = render_once(
            现在时间=现在时间,
            强制刷新=False,   # 刷新已在 ① 做过（render_once 的强制刷新就是这两件事，别抓两遍）
            输出路径=临时,
            背景路径=背景路径,
            标题=运行配置.标题,
            结束偏移们=运行配置.有效结束偏移们(),
            开始偏移们=运行配置.有效开始偏移们(),
            底栏分区=运行配置.底栏分区(),
            控制台打印提醒=False,   # 插件里提醒随图走，不打到 stdout
        )
        if not 图是完整的(临时):
            logger.error("渲染未产出完整图片，按失败处理：%s", 临时)
            临时.unlink(missing_ok=True)
            return 结果        # 入口层会报"渲染失败"，不会把这张图发出去
        try:
            os.replace(临时, 目标)
        except OSError:
            logger.exception("产物落盘失败：%s", 目标)
            临时.unlink(missing_ok=True)
            return 结果
        return replace(结果, 图片路径=目标)

    def _刷新数据(self, 现在时间: datetime, 现在字符串: str, 设置: Settings,
                  *, 强制: bool, 回溯已结束: bool = False) -> None:
        """按新鲜度抓活动数据 / 首页预告；抓取失败只记日志，沿用上次数据继续出图。

        两者各按自己的"今天写过"判断（活动数据是 CSV、首页预告是 `新增预告.json`）：
        分开判断才能避免"CSV 是今天的"让**没抓成的预告**一整天不再重试。

        `回溯已结束=True`（`/方舟日程 初始化`）= 初始化：扫**最近半年**的活动公告，
        并把扫描结果**覆盖重建**成新的活动数据（旧行/旧格式不保留）；
        日常只扫进行中 + 近 7 天结束过的（见 `src/解析_API活动.py`），且是增量合并。
        **全新安装（还没有 CSV）会自动初始化一次**，用户不必自己去点。
        """
        需数据, 需预告 = (True, True) if 强制 else (
            not 今天写过(Path(设置.all_data_path), 现在时间),
            not 今天写过(Path(设置.new_items_path), 现在时间),
        )
        # 还没有 CSV（全新安装 / 用户删了数据）→ 本次自动做一次初始化（全量扫），
        # 否则第一次出图只有"进行中的活动"，看起来像缺内容（剿灭轮换就是这么缺的）
        首次 = not Path(设置.all_data_path).exists()
        if 需数据 and 首次 and not 回溯已结束:
            回溯已结束 = True
            logger.info("还没有活动数据（全新安装）→ 本次自动初始化（全量扫所有活动的公告）")
        if 需数据:
            更新数据(现在字符串, 回溯已结束=回溯已结束)
        if 需预告:
            try:
                更新增预告(现在时间, 现在字符串)
            except Exception:
                logger.exception("新增预告获取失败（沿用上次数据）")

    @staticmethod
    def _启用Agg() -> None:
        """切无头后端。必须在任何 pyplot 导入之前调用（内核的 matplotlib 导入发生在其后）。"""
        import matplotlib

        matplotlib.use("Agg", force=True)

    @staticmethod
    def _背景路径(运行配置: 运行配置, 设置: Settings, 现在时间: datetime) -> str | None:
        """定下这次用哪张背景图（目录空则 None）。

        - 指定了文件名/绝对路径 → 用它（**必须真的存在**：写错文件名要给一句人话，
          而不是让内核拿着一支不存在的图去画——内核在背景读不到时会退回默认配色，
          结果是一张"没人看得出哪里错"的图）；
        - 否则按日期顺序轮换：同一天使用同一张，换天后切换到下一张。
        """
        if 运行配置.指定背景:
            指定 = Path(运行配置.指定背景)
            路径 = 指定 if 指定.is_absolute() else Path(设置.bg_dir) / 指定
            if not 路径.is_file():
                raise 素材缺失(路径.parent, 文件=str(路径))
            return str(路径)
        图片后缀 = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
        候选 = sorted(
            p for p in Path(设置.bg_dir).glob("*")
            if p.is_file() and p.suffix.lower() in 图片后缀
        )
        if not 候选:
            return None
        # 使用自 1970-01-01 起的天数轮换，确保每隔 N 天遍历到下一张。
        天数 = (现在时间.date() - datetime(1970, 1, 1).date()).days
        return str(候选[天数 % len(候选)])
