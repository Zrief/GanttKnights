"""渲染服务 —— 把同步的「取数 + 渲染」内核接到 asyncio 上（见 docs/插件化路线.md §5.5~§5.7、§17.4）。

三件事：

1. **不阻塞事件循环**：matplotlib 渲染是秒级 CPU 占用，`src/获取_prts.py` 又是同步
   `httpx`——整个流程统一塞进 `asyncio.to_thread`。因此本模块顶层**不 import matplotlib**，
   它只在工作线程里被拖进来（冷缓存实测 1139ms，同步导入会让事件循环停半秒以上）。
2. **单飞锁**：同一时刻只允许一次「刷新数据 + 渲染」。锁不是缓存——它保护的是**可变的内核全局
   `settings`**（`应用设置()` 就地改写）与"两个请求同时写同一个产物文件"。
   并发请求会排队（第一个 1.5s，第二个再 1.5s），这是**有意接受**的：性能在这个产品里不重要
   （§17.4），换掉的是整套签名缓存与它带来的 8 类 bug。
3. **按需渲染，不留缓存**：请求来就画，直接原子落到 `settings.output_path`（`Gantt.jpg`）。
   每天真正有价值的信息是"和昨天比变了什么"，那由**抓取时的合并动作**回答
   （`src/汇总_活动.py::合并差异` → `src/数据变化.py` 落盘 → `渲染结果.变化`），
   而不是靠复用昨天的图。

### 背景：按自然日确定性抽签

指定了 `background_file` 就用它（且必须真的存在）；否则 **`候选[crc32(日期) % 张数]`**——
同一天恒定一张，换天才换。没有缓存之后这不是为了缓存稳定，而是为了**观感稳定**：
同一天群里看到的图长得一样，不会因为谁先谁后而换配色。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import zlib
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path

from ..src.config import Settings, settings as 内核设置
from ..src.流水线 import 今天写过, 更新增预告, 更新数据, render_once
from ..src.流水线 import 渲染结果
from .配置 import 运行配置

logger = logging.getLogger("ganttknights")

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

    def 清理旧缓存(self) -> None:
        """删掉阶段四留下的 `渲染缓存/`（升级路径用；渲染缓存已经整个废弃，§17.4）。

        只删这一个目录名，不动同级的 `图片缓存/`（头像）与 `最近数据变化.json`。
        """
        目录 = self.数据目录 / "渲染缓存"
        if 目录.is_dir():
            try:
                shutil.rmtree(目录)
                logger.info("已清理阶段四遗留的渲染缓存目录：%s", 目录)
            except OSError:
                logger.warning("渲染缓存目录删不掉（忽略）：%s", 目录, exc_info=True)

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
        （入口层用 `产物可用()` 兜底判断）。

        `回溯已结束=True` = CLI 的 `--bootstrap`：额外扫描**更老的已结束活动**的公告，
        补录仍在进行的长期轮换与复刻排期（wiki 会复用老活动页，所以这块只有全量扫描才看得到）。
        **全新安装（还没有 CSV）会自动走一次全量回溯**，用户不必自己去点。
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
        """最近一次数据合并的日期（给 `/甘特图状态` 用）；没有则空串"""
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
            提醒天数=运行配置.提醒天数,
            底栏分区=运行配置.底栏分区(),
            控制台打印警告=False,   # 插件里警告随图走，不打到 stdout
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

        **全新安装自动全量回溯**：CSV 还不存在时，用户刚装好插件、手里没有任何数据，
        此时多扫一遍老活动的公告（≈ `cli.py --bootstrap`）才能把长期轮换与复刻排期一起拿到；
        否则第一次出图只有"进行中的活动"，看起来像缺内容（实测：实例那份数据缺剿灭就是这么来的）。
        """
        需数据, 需预告 = (True, True) if 强制 else (
            not 今天写过(Path(设置.all_data_path), 现在时间),
            not 今天写过(Path(设置.new_items_path), 现在时间),
        )
        首次 = not Path(设置.all_data_path).exists()
        if 需数据 and 首次 and not 回溯已结束:
            回溯已结束 = True
            logger.info("还没有活动数据（全新安装）→ 本次自动做一次全量回溯（等价 cli.py --bootstrap）")
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
