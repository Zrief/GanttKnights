"""渲染服务 —— 把同步的「取数 + 渲染」内核接到 asyncio 上（见 docs/插件化路线.md §5.5/§5.6/§5.7）。

三件事：

1. **不阻塞事件循环**：matplotlib 渲染是秒级 CPU 占用，`src/获取_prts.py` 又是同步
   `httpx`——整个流程统一塞进 `asyncio.to_thread`。因此本模块顶层**不 import matplotlib**，
   它只在工作线程里被拖进来（冷缓存实测 1139ms，同步导入会让事件循环停半秒以上）。
2. **单飞锁 + 短期复用**：同一时刻只允许一次渲染（`asyncio.Lock` + 锁内 double-check），
   渲染完成后在"复用窗口"内重复请求直接复用这张图。
   > 这是阶段三的最小实现：阶段四会换成"业务签名缓存 + manifest + 跨日失效"（§7）。
3. **Agg 后端 + 可写 MPLCONFIGDIR**：插件环境没有显示器，且默认缓存目录在容器/只读环境里
   不可写。MPLCONFIGDIR 必须在 matplotlib **首次导入之前**设好，所以路径准备在
   `准备matplotlib环境()`（构造期调用，只设环境变量），`use("Agg")` 在工作线程里执行。
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path

from ..src.config import Settings, settings as 内核设置
from ..src.流水线 import 今天写过, 更新增预告, 更新数据, render_once
from ..src.流水线 import 渲染结果
from .配置 import 运行配置

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
        # 锁在事件循环里首次使用时才绑定循环（Python 3.10+ 的 Lock 不再在构造期绑定），
        # 这里构造于插件加载期也安全。
        self._锁 = asyncio.Lock()
        # 复用记录：(时刻, 底栏分区, 渲染结果)。底栏分区进键，改开关后不会继续发旧图。
        self._最近: tuple[datetime, tuple[str, ...] | None, 渲染结果] | None = None

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
        - 时间窗来自插件配置，用户一改就生效（阶段四会并入缓存签名）。
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
        """把内核的全局 `settings` 就地改成插件这份。

        内核各模块（`流水线` / `筛选_活动` / `字体` / `绘图_*`）都在**调用时**读全局
        `settings`（阶段一保证过没有模块级取值），所以就地覆盖即可，无需给每个函数加参数。
        代价是进程级全局状态：CLI 与插件不会同时跑，互不影响。
        """
        设置 = self.内核设置(运行配置)
        for 字段 in fields(Settings):
            setattr(内核设置, 字段.name, getattr(设置, 字段.name))
        return 设置

    # ==================== 出图前的检查与判断 ====================

    def 素材问题(self, 运行配置: 运行配置) -> Path | None:
        """出图前的素材体检：返回"不可出图"的原因（目前只会是背景图目录为空）。

        内核的 `挑选背景图()` 在目录为空时 `SystemExit(1)`——那是给 CLI 用的
        （进程退出码），在插件里会穿透 `to_thread` 变成杀掉任务链的 BaseException。
        所以这里提前拦下，换成一句能给用户看的话。
        """
        if 运行配置.指定背景:
            return None
        目录 = Path(self.内核设置(运行配置).bg_dir)
        候选 = [p for p in 目录.glob("*") if p.is_file()] if 目录.is_dir() else []
        return None if 候选 else 目录

    def 需要每日更新(self, 现在时间: datetime, 运行配置: 运行配置) -> bool:
        """活动数据不是今天抓的 → 本次出图前先更新（语义与 CLI 的"每天只爬一次"一致）。"""
        if not 运行配置.每日自动更新:
            return False
        设置 = self.应用设置(运行配置)
        return not 今天写过(Path(设置.all_data_path), 现在时间)

    def 取复用(self, 现在时间: datetime, 运行配置: 运行配置) -> 渲染结果 | None:
        """复用窗口内已渲染过、且底栏分区开关没变的图（同步、不取锁；锁内二次确认见 `出图()`）。"""
        if 运行配置.复用窗口秒 <= 0 or self._最近 is None:
            return None
        时刻, 分区, 结果 = self._最近
        if 分区 != 运行配置.底栏分区():
            return None
        if 现在时间 - 时刻 > timedelta(seconds=运行配置.复用窗口秒):
            return None
        路径 = Path(结果.图片路径)
        if not 路径.exists() or 路径.stat().st_size == 0:
            self._最近 = None
            return None
        return 结果

    def 清理复用(self) -> None:
        self._最近 = None

    # ==================== 出图 ====================

    async def 出图(
        self,
        *,
        现在时间: datetime,
        运行配置: 运行配置,
        自动更新: bool,
        强制刷新: bool = False,
    ) -> 渲染结果:
        """渲染（或复用）一张图。

        单飞：并发请求只会有一次真渲染——后到的请求在锁上等待，
        拿到锁后先查复用，命中就直接返回，不再画第二张。
        """
        async with self._锁:
            if not 强制刷新:
                命中 = self.取复用(现在时间, 运行配置)
                if 命中 is not None:
                    logger.info("复用上一次渲染结果：%s", 命中.图片路径)
                    return 命中
            结果 = await asyncio.to_thread(
                self._同步出图, 现在时间, 运行配置, 自动更新, 强制刷新
            )
            self._最近 = (现在时间, 运行配置.底栏分区(), 结果)
            return 结果

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

        # 与 CLI 同样的"每天只做一次"策略：活动数据与新增预告各管各的新鲜度
        # （活动数据当天抓过时，预告仍要确认是今天的，否则底栏整区缺失）。
        if 自动更新:
            更新数据(现在字符串)
            try:
                更新增预告(现在时间, 现在字符串)
            except Exception:
                logger.exception("新增预告获取失败（沿用上次数据）")

        return render_once(
            现在时间=现在时间,
            强制刷新=强制刷新,
            输出路径=设置.output_path,
            背景路径=self._背景路径(运行配置, 设置),
            标题=运行配置.标题,
            提醒天数=运行配置.提醒天数,
            底栏分区=运行配置.底栏分区(),
            控制台打印警告=False,   # 插件里警告随图走，不打到 stdout
        )

    @staticmethod
    def _启用Agg() -> None:
        """切无头后端。必须在任何 pyplot 导入之前调用（内核的 matplotlib 导入发生在其后）。"""
        import matplotlib

        matplotlib.use("Agg", force=True)

    @staticmethod
    def _背景路径(运行配置: 运行配置, 设置: Settings) -> str | None:
        """None = 交给内核从 bg_dir 随机取一张。"""
        if 运行配置.指定背景:
            指定 = Path(运行配置.指定背景)
            return str(指定 if 指定.is_absolute() else Path(设置.bg_dir) / 指定)
        if 运行配置.随机背景:
            return None
        # 关闭随机且未指定文件 → 固定取目录里第一张，出图可复现（阶段四缓存也靠它）
        候选 = sorted(p for p in Path(设置.bg_dir).glob("*") if p.is_file())
        return str(候选[0]) if 候选 else None
