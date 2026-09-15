"""字体解析：这次渲染到底用哪支字体，并把它们注册给 matplotlib。

为什么不写死
------------
1. **本机的 `Noto Sans SC` 是可变字体（VF）**，matplotlib 没有变体轴接口，只会渲染默认实例
   —— 实测默认权重是 Thin(100)，标题不仅加不粗还偏细；缺 Bold 时它只 warning 降级，**不伪粗**。
   所以随包静态字重是"设计基线"。
2. **但随包字体不能是唯一来源**：没有 `字体/` 时如果只认死家族名，Windows 上会一路落到
   matplotlib 默认的 DejaVu Sans（不含 CJK）→ **整张图的中文都是豆腐块**（实测，不报错）。
   所以要有平台字体兜底。

三层候选（由前到后）
--------------------
1. `字体/` 下的随包静态字重（`字体表`）；
2. `settings.额外字体`：插件传入 AstrBot 文档化的自定义字体插槽
   （`data/font.ttf` / `font-bold.ttf` / `font-mono.ttf`，见 `core/config/default.py` 的 t2i 提示）；
   另有单文件开关 `settings.font_path` + `settings.font_family`；
3. **平台自带 CJK 家族**（`无衬线候选` / `等宽候选`，沿用 AstrBot 的本地文转图策略
   `astrbot/core/utils/t2i/local_strategy.py:34-111`）：Windows 微软雅黑、macOS 苹方 / Hiragino、
   Linux 与官方 Docker 镜像的 Noto CJK。

不使用衬线（2026-09 决定，理由见 docs「接上宿主」）：衬线只用在页眉标题与底栏分区标签两处，
而所有候选字体的汉字 advance 都是 1.000em，换族对版面零影响，少依赖一支 25MB 的字体文件。

`真粗体` 的判定
---------------
不看"目录里有没有 `NotoSansCJKsc-Bold.otf`"，而是**解析出的粗体文件与常规文件是否不同**：
于是雅黑粗体、Noto CJK Bold 都算真粗体，而"可变字体同一文件"（如系统的 `Noto Sans SC`）
会被正确判为没有真粗体，调用方转而用同色描边兜底。

`字体/` 目录不进 git（.gitignore），需要时按 OFL-1.1 自行放置：
  NotoSansCJKsc-Regular.otf / NotoSansCJKsc-Bold.otf
  NotoSansMono-Regular.ttf / NotoSansMono-Bold.ttf
下载：https://github.com/notofonts/noto-cjk/releases （Sans2.004 的 SC 包）
      https://github.com/notofonts/noto-fonts （Noto Sans Mono）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

from .config import settings

logger = logging.getLogger(__name__)


# 字体目录取自 settings（默认 ROOT_DIR/字体，可用 GK_FONT_DIR 或构造参数覆盖）。
# 注意：不能在 import 期把它求值成常量——settings 是可注入的，求值太早就锁死了。
def 取字体目录() -> Path:
    return Path(settings.字体目录)


无衬线族 = "Noto Sans CJK SC"     # 随包：字体/NotoSansCJKsc-*.otf
等宽族 = "Noto Sans Mono"         # 随包：字体/NotoSansMono-*.ttf

# 文件 → (family, 字重)：同一 family 的多个字重必须同版本，matplotlib 才能按字重挑对。
# 两层两族：无衬线管正文与标题、等宽管数字与日期
# （思源黑的数字 advance 是 0.56em 而斜杠是 1em 全角，日期会被撑开，所以数字要单独一层）
字体表 = {
    "NotoSansCJKsc-Regular.otf": (无衬线族, "normal"),
    "NotoSansCJKsc-Bold.otf": (无衬线族, "bold"),
    "NotoSansMono-Regular.ttf": (等宽族, "normal"),
    "NotoSansMono-Bold.ttf": (等宽族, "bold"),
}

# 角色候选家族（优先级由前到后）。前两个是本项目随包字体的家族名（命中即"设计基线"），
# 其余是平台自带字体——顺序与 AstrBot local T2I 的候选表一致（它把"用户 data/ 字体"排在更前，
# 我们已经用 额外字体 实现那一层）。
无衬线候选 = (
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",       # Linux/Docker：fonts-noto-cjk 的 ttc 首 face
    "Microsoft YaHei",        # Windows（雅黑；它自带真粗体 msyhbd，且拉丁数字是等宽数字）
    "PingFang SC",            # macOS
    "Hiragino Sans GB",       # macOS（较旧系统）
    "Noto Sans SC",           # 系统那支可变字体（实在没有别的才用：默认实例偏细）
    "Droid Sans Fallback",    # Android / 部分精简 Linux
    "AR PL UMing CN",         # 老发行版兜底
)
等宽候选 = (
    "Noto Sans Mono",
    "Noto Sans Mono CJK SC",  # Linux：Noto CJK 的等宽族
    "Noto Sans Mono CJK JP",
    "Microsoft YaHei",        # Windows/macOS 没有等宽 CJK：雅黑/苹方的拉丁数字是等宽数字，
    "PingFang SC",            # 日期轴带照样齐（实测 09/10…12/28 宽度极差 0.00px）
    "Hiragino Sans GB",
    "DejaVu Sans Mono",       # 最后兜底（无 CJK，只保证数字能画出来）
)


@dataclass(frozen=True)
class 字体方案:
    """这次渲染实际选中的字体。"""

    无衬线族: str
    等宽族: str
    真粗体: bool
    正文文件: str
    等宽文件: str
    来源: str          # "随包" / "自定义" / "系统"
    真粗体文件: str = ""


_方案: 字体方案 | None = None
_方案指纹: tuple | None = None


def 字体指纹() -> tuple:
    """会改变"用哪支字体"的全部输入 —— 供 `注册字体()` 判断缓存是否还有效。

    只 `stat` 不读内容：字体文件动辄 20MB，每次出图做内容哈希不划算，而"换字体"
    必然改大小或 mtime（`size` + `mtime_ns` 与 `绘图_图表` / `绘图_主题` 的指纹同一口径）。

    为什么需要它：`_方案` 是**进程级**缓存，而 AstrBot 的"禁用插件→启用插件"不会重载
    已 import 的模块。没有这层指纹时，用户在长驻进程里往 `data/font.ttf`（插件唯一的
    自定义字体入口）或 `字体/` 里放字体**永远不会生效**，只能重启 AstrBot——
    2026-09-14 的对抗性审查实测到了这一点（同进程加入后仍是系统字体，独立进程则生效）。
    """
    条目: list[str] = [str(settings.font_path), settings.font_family]
    try:
        目录 = 取字体目录()
        条目.append(str(目录))
        条目 += sorted(f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}"
                       for p in 目录.iterdir() if p.is_file())
    except OSError:
        条目.append("字体目录读不到")
    for 角色, 路径 in sorted((settings.额外字体 or {}).items()):
        try:
            st = Path(路径).stat()
            条目.append(f"{角色}:{路径}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            条目.append(f"{角色}:{路径}:缺")
    return tuple(条目)


def _解析文件(家族: str, 字重: str = "normal") -> str | None:
    """家族 + 字重 → 字体文件路径；解析不到返回 None（不用 fallback_to_default，否则永远成功）"""
    try:
        return str(fm.findfont(fm.FontProperties(family=家族, weight=字重),
                               fallback_to_default=False))
    except Exception:
        return None


def _挑族(候选: tuple[str, ...] | list[str], 字重: str = "normal") -> tuple[str, str] | None:
    for 家族 in 候选:
        路径 = _解析文件(家族, 字重)
        if 路径:
            return 家族, 路径
    return None


def _注册文件(路径: Path) -> str | None:
    """把一个字体文件交给 matplotlib，返回它声明的家族名（失败返回 None）"""
    try:
        fm.fontManager.addfont(str(路径))
        return fm.FontProperties(fname=str(路径)).get_name()
    except Exception:
        logger.warning("字体注册失败：%s", 路径)
        return None


def _能画中文(路径: Path) -> bool:
    """这个字体文件里有"中"的字形吗？

    自定义槽（`data/font.ttf`）里的字体是用户随手放的，放一支纯拉丁字体进来不会报错，
    只会让整张图的中文变成豆腐块——所以先粗筛一次。
    ⚠️ 只用 `get_char_index()`（安全）；**不要**用 `load_char()`：缺字形时它会段错误。
    """
    try:
        from matplotlib import ft2font

        return ft2font.FT2Font(str(路径)).get_char_index(ord("中")) != 0
    except Exception:
        return False


def _装自定义字体() -> tuple[dict[str, str], str]:
    """注册"自定义字体"来源，返回 {角色: 家族名} 与来源标签。

    两个入口：
      · `settings.额外字体` = {"正文": 路径, "粗体": 路径, "等宽": 路径}
        （插件按 AstrBot 的 data/font*.ttf 约定填）；
      · `settings.font_path` + `settings.font_family`（单文件覆盖，CLI/测试常用）。
    """
    自定义: dict[str, str] = {}
    额外 = settings.额外字体 or {}
    for 角色 in ("正文", "等宽"):
        值 = 额外.get(角色)
        if 值 and Path(值).exists():
            if not _能画中文(Path(值)):
                logger.warning("自定义字体没有中文字形，已忽略（否则整张图会变豆腐块）：%s", 值)
                continue
            家族 = _注册文件(Path(值))
            if 家族:
                自定义[角色] = 家族
    粗体 = 额外.get("粗体")
    if 粗体 and Path(粗体).exists() and _能画中文(Path(粗体)):
        # 粗体不单独挑"族"：同族同字重，靠 weight=bold 解析就能命中（_注册文件 已把它加进字体表）
        _注册文件(Path(粗体))

    if not 自定义:
        候选路径 = Path(settings.font_path)
        if 候选路径.exists() and 候选路径.name not in 字体表:
            if not _能画中文(候选路径):
                logger.warning("font_path 指向的字体没有中文字形，已忽略：%s", 候选路径)
            elif _注册文件(候选路径):
                自定义["正文"] = settings.font_family
    return 自定义, ("自定义" if 自定义 else "")


def 注册字体(强制: bool = False) -> 字体方案:
    """注册所有可用字体源 → 挑出角色字体 → 应用到 rcParams。

    结果按 `字体指纹()` 缓存：指纹不变就直接返回，指纹变了（用户往 `字体/` 或
    `data/font.ttf` 放了/换了字体）就重新解析 —— 长驻进程里这才让"换字体"可见。

    已知边界：matplotlib 的字体表**只增不减**，所以"删掉字体文件"在本进程内仍会解析到
    那条旧记录（指向已不存在的路径的可能），要彻底收敛得重启；同名同字重的**不同文件**
    相争时，`findfont` 平分取先注册的，也可能仍落到旧的。这两条都只在"删/换同名家族"时出现。
    """
    global _方案, _方案指纹
    指纹 = 字体指纹()
    if _方案 is not None and not 强制 and 指纹 == _方案指纹:
        return _方案
    if _方案 is not None:
        logger.info("字体来源发生变化，重新解析字体")

    字体目录 = 取字体目录()
    随包可用 = [名 for 名 in 字体表 if (字体目录 / 名).exists()]
    for 名 in 随包可用:
        _注册文件(字体目录 / 名)

    自定义, 自定义来源 = _装自定义字体()

    候选无衬线 = ([自定义["正文"]] if "正文" in 自定义 else []) + list(无衬线候选)
    候选等宽 = ([自定义["等宽"]] if "等宽" in 自定义 else []) + list(等宽候选)

    无衬线 = _挑族(候选无衬线)
    等宽 = _挑族(候选等宽)
    if 无衬线 is None:      # 连 DejaVu 都解析不到（几乎不可能）：退回 matplotlib 默认，别抛异常
        logger.error("找不到任何可用字体，中文会显示为方块")
        无衬线 = ("sans-serif", "")
    if 等宽 is None:
        等宽 = 无衬线

    真粗体文件 = _解析文件(无衬线[0], "bold") or ""
    真粗体 = bool(真粗体文件) and 真粗体文件 != 无衬线[1]
    # 同文件 → 可变字体（或压根没有 Bold）：不算真粗体，调用方改用同色描边兜底
    来源 = 自定义来源 or ("随包" if 随包可用 else "系统")

    _方案 = 字体方案(
        无衬线族=无衬线[0], 等宽族=等宽[0], 真粗体=真粗体,
        正文文件=无衬线[1], 等宽文件=等宽[1], 来源=来源, 真粗体文件=真粗体文件,
    )
    plt.rcParams["font.sans-serif"] = [_方案.无衬线族, _方案.等宽族]
    # 不使用衬线：serif 也指到无衬线族，避免任何漏网的 family="serif" 落到系统衬线
    # （那支多半是可变字体，默认实例只有 ExtraLight(200)）。
    plt.rcParams["font.serif"] = [_方案.无衬线族]
    plt.rcParams["axes.unicode_minus"] = False
    _方案指纹 = 指纹

    logger.info(
        "字体来源 %s：正文 %s（%s）｜等宽 %s（%s）｜真粗体 %s",
        _方案.来源, _方案.无衬线族, Path(_方案.正文文件).name if _方案.正文文件 else "?",
        _方案.等宽族, Path(_方案.等宽文件).name if _方案.等宽文件 else "?",
        ("是 " + Path(_方案.真粗体文件).name) if _方案.真粗体 else "否（用描边兜底）",
    )
    return _方案


def 命中检查() -> dict[str, str]:
    """自检：每个角色最后用的是哪支文件、是否来自 字体/、真粗体是否可用"""
    方案 = 注册字体()
    字体目录 = 取字体目录().resolve()
    结果: dict[str, str] = {}
    for 角色, 家族, 文件 in (("正文", 方案.无衬线族, 方案.正文文件),
                              ("等宽", 方案.等宽族, 方案.等宽文件)):
        if not 文件:
            结果[f"{角色}/{家族}"] = "解析失败"
            continue
        路径 = Path(文件).resolve()
        标记 = "" if 路径.parent == 字体目录 else "  ← 不是随包文件"
        结果[f"{角色}/{家族}"] = f"{路径.name}{标记}"
    结果["真粗体"] = (f"{Path(方案.真粗体文件).name}（{方案.无衬线族}）"
                      if 方案.真粗体 else "不可用 → 同色描边兜底")
    结果["来源"] = 方案.来源
    return 结果
