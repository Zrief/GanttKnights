"""排版 — 罗德岛终端风格：页眉 + 左信息列甘特图 + 按区独立卡片的底栏

整幅图从上到下分三段，全部按像素排布（dpi 150 下 1 数据单位 = 1 像素）：

  页眉  大字粗体标题 + 右侧带强调竖线的"数据来源 / 更新时间"块
  甘特  固定宽左信息列（类型色条 + 类型关键词）+ 顶部日期轴带 + 每日竖网格
        + 贯穿全高的 TODAY 柱带；事件名优先写在条上，条太短时引到条外
  底栏  按"凭证兑换 / 新增时装 / 新增模组"分区的卡片行：近白面板 + 顶部色带标题
        + 圆角头像 + 干员名；行数与格宽由试排搜索决定

排版参考 astrbot_plugin_ark_calendar 的日历模板（HTML/CSS 渲染），吸收四点：
  1) 时间轴 = 固定宽【左侧信息列】+ 顶部深色【日期轴带】+ 每日竖网格 + 贯穿全高的
     TODAY 柱带；名称不再挤在条里，短条也读得出来。
  2) 区块 = 近白面板 + 顶部色带，标题行用反白字，缩到手机宽度也不丢分区识别度。
  3) 页眉 = 大字粗体标题（无衬线，见 字体.py 的"为什么不用衬线"）+ 右侧带强调竖线的信息块。
  4) 底栏排版由条目数自动搜索：行数最少 → 填得最满 → 格宽最接近理想值。

配色不写死：整套色值由 src.绘图_主题.建主题(背景图) 推导——色相与彩度取自图片，
明度梯度（深底/面板/文字/强调）是固定规范，于是每张背景图自动得到自己的主体色系，
事件类型与底栏分区分取同一条强调色阶的不同档位。

本模块只负责排版与绘制：数据（记录列表 / 分区 / 主题 / 时间窗）全部由调用方传入。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.patheffects import Normal, SimplePatchShadow, withStroke
from matplotlib.textpath import TextToPath
from PIL import Image as PILimage
from PIL import ImageChops, ImageDraw

from .config import settings
from .甘特行 import 分行
from .绘图_图表 import 缩放图片
from .绘图_颜色 import set_alpha_channel
from .绘图_主题 import 主题
from .字体 import 注册字体, 字体指纹
from .提醒文案 import 展示名

logger = logging.getLogger(__name__)

# —— 文案（颜色一律由 建主题(背景图) 推导，这里不写死任何色值）——
图标题 = "近期活动一览"
类型关键词 = {0: "寻访", 1: "活动", 2: "福利", 99: "长期"}
组顺序 = ("限时", "中坚", "标准", "甄选", "活动", "福利", "长期")
"""甘特图左列从上到下的分组：卡池先按池子种类细分（`活动.子类型`），其余按大类。

顺序与 `活动.子类型顺序` 一致。组数比大类多，但每组名都是两个字，左列宽度不用改。"""


def 组标签(条目) -> str:
    """一条记录归到哪个左列分组：有子类型就用子类型，否则用大类的关键词。"""
    return 条目.子类型 or 类型关键词.get(条目.类型, "")



区名表 = ("凭证兑换", "新增时装", "新增模组")
新增键 = {"凭证兑换": "凭证", "新增时装": "时装", "新增模组": "模组"}
周名 = ["一", "二", "三", "四", "五", "六", "日"]

# 字体：优先用 字体/ 下的静态字重（系统那支是可变字体，只能渲染最细的默认实例）
# ⚠️ 这里**不能在 import 期调用 注册字体()**：那会在加载模块时扫全部字重、重建
# matplotlib 字体缓存（秒级阻塞）。作为 AstrBot 插件加载时会卡住事件循环。
# 改为首次真正出图时再注册 —— 见 绘制甘特图() 里的 _确保字体就绪()。
#
# 标题族 / 等宽 / 真粗体：**首次出图时**由 字体.注册字体() 的解析结果覆盖（见 _确保字体就绪()）。
# 这里给的是"还没解析"时的占位值——解析一定发生在任何绘制之前。
# 不使用衬线：标题与底栏分区标签也用无衬线（理由见 字体.py）。
标题族 = "Noto Sans CJK SC"
等宽 = "Noto Sans Mono"

# 注册前先按"无真粗体"处理：粗体() 会据此走同色描边兜底。
真粗体 = False
粗字重 = "normal"
_字体指纹: tuple | None = None


def _确保字体就绪() -> None:
    """出图前注册字体并落地角色字体（按"字体来源指纹"幂等）。

    必须在真正画字之前调用：matplotlib 在 draw 时按 family 名解析字体，
    仅设置 rcParams 而不注册文件是找不到 字体/ 下那几支静态字重的。

    判据用 `字体.字体指纹()` 而不是一个一次性布尔：AstrBot 是长驻进程，
    "禁用/启用插件"不会重载模块，用一次性布尔会让"往 `data/font.ttf` 或 `字体/`
    放字体"在本次进程内**永远不生效**（2026-09-14 审查实测）。指纹变了就重解析。
    """
    global _字体指纹, 标题族, 等宽, 真粗体, 粗字重
    指纹 = 字体指纹()
    if _字体指纹 == 指纹:
        return
    方案 = 注册字体()
    标题族 = 方案.无衬线族
    等宽 = 方案.等宽族
    真粗体 = 方案.真粗体
    粗字重 = "bold" if 真粗体 else "normal"
    _字体指纹 = 指纹


def 粗体(色: str, 粗细: float = 0.9):
    """没有真字重时用同色描边兜底；有真字重就不描（交给 fontweight）"""
    return None if 真粗体 else [withStroke(linewidth=粗细, foreground=色), Normal()]


# —— 画布尺寸（dpi150 下的像素）——
DPI = 150
图宽px = 2400
边距左px = 边距右px = 60
边距下px = 46
轴宽px = 图宽px - 边距左px - 边距右px

页眉高px = 96
页眉间距px = 18
甘特左列px = 78           # 只放活动类型关键词（寻访/活动/福利/长期）
甘特轴带px = 54           # 顶部日期轴带
甘特行高px = 82
甘特底px = 6
甘特间距px = 96
行高px = 228              # 每行底栏卡片高度
行间距px = 36             # 行与行之间

# —— 底栏排版参数 ——
格宽最小px = 128
格宽最大px = 210
理想格宽px = 158
区间隙px = 30
格内边距px = 22
最大图标px = 96
顶条px = 4                # 卡片顶部色条
标题行px = 36
卡圆角px = 10             # 面板圆角：直角太锐，只磨一点点

# —— 底栏卡片的"标题带"：淡而浊的一层，从卡片顶部一路渐隐，配本区深色标题字 ——
# （对照过"深艳实带 + 反白字"与"顶部细色条"两版：实带太跳、细条又几乎看不见；
#   定稿靠"淡色带 + 长渐变"给装饰性，色相识别由色带与标题字色双重承载）
底栏带_不透明 = 0.90      # 最深处的不透明度
底栏带_曲线 = 1.0         # 渐隐曲线指数：1 = 线性，越大越"只贴着顶部"
底栏带_亮度 = 0.80        # 标题带色的明度：够亮才配得起深色标题字

# —— 甘特条上的名字：条**里**与条**外**（引线）共用同一套字号 / 字重 / 描边 ——
# 曾经条内是 15px 粗体带描边、条外是 13px 常规无描边——同一个活动名两种长相，2026-09-24 统一。
# 颜色仍各自跟底色走（条内 = 对色，条外 = 主文），那是物理约束不是风格。
条名_字号 = 15
条名_字重 = 粗字重
条名_描边 = 0.7
头像圆角比 = 0.06         # 头像几乎方形，只把尖角磨掉一点
头像描边px = 2


def 组弧度表() -> dict[str, float]:
    """左列分组 → 色弧上的位置（主色 → 副色连续过渡）。

    组名、左列色轨、组内每根条的条色三处同源——一个颜色，一眼对得上。
    """
    return {名: i / (len(组顺序) - 1) for i, 名 in enumerate(组顺序)}


def 区弧度表() -> dict[str, float]:
    """底栏分区 → 色弧上的位置（与类型共用同一条弧，靠明度档位区分）"""
    名们 = list(区名表)
    return {名: i / (len(名们) - 1) for i, 名 in enumerate(名们)}


# ============================ 文本宽度 ============================
# 交给 matplotlib 自己量（`TextToPath`，与渲染器同一条 set_text 路径、含 fallback
# 列表），按 (串, 字号, family, weight) 缓存。一次渲染只有几十次调用（活动名 +
# 日期刻度 + 底栏截断），实测冷缓存 +19ms、热缓存 ~0，代价可忽略。
# （旧版曾有"汉字 1em / 西文 0.55em"的估算法，与真实字形有系统性偏差且方向随字体
#   翻转，换字体后会让"名字放不放得进条内"这类卡边判定出错，已删。）
#
# ⚠️ **不要**改成 `FT2Font.load_char()` 逐字取 advance：字体里缺该字形时（例如没装中文字体、
#    只剩 DejaVu），本机实测**直接段错误 0xC0000005 把宿主进程打死**——AstrBot 会跟着挂。
#    `get_text_width_height_descent()` 遇到缺字形只 warning，是安全的。


@lru_cache(maxsize=1)
def _度量器() -> TextToPath:
    """TextToPath 构造要建 MathTextParser，按需创建"""
    return TextToPath()


@lru_cache(maxsize=4096)
def _真实宽度(s: str, 字号: float, family: str | None, weight: str | None) -> float:
    """按 family+weight 交给 matplotlib 量字符串宽度（px）。缓存键含字号与字重。"""
    prop = fm.FontProperties(family=family, weight=weight, size=字号)
    return _度量器().get_text_width_height_descent(s, prop, False)[0] * DPI / 72


def 文本宽(s: str, 字号: float, family: str | None = None,
           weight: str | None = None) -> float:
    """文本宽度（px）。调用方应传入**实际绘制时用的** family/weight，否则会量错字体。"""
    return _真实宽度(s, 字号, family, weight)


def 截到宽(s: str, 最大px: float, 字号: float, family: str | None = None,
           weight: str | None = None) -> str:
    if 文本宽(s, 字号, family, weight) <= 最大px:
        return s
    while s and 文本宽(s + "…", 字号, family, weight) > 最大px:
        s = s[:-1]
    return s + "…"


def 载图标数组(文件名: str) -> np.ndarray | None:
    """读一条目的头像；文件名缺失、缓存未命中或图片损坏都返回 None（按无图渲染）"""
    if not 文件名:
        return None
    路径 = Path(settings.icon_cache_dir) / 文件名
    if not 路径.exists():
        return None
    try:
        return np.asarray(PILimage.open(路径).convert("RGBA"))
    except Exception:
        logger.warning("头像读取失败，按无图渲染: %s", 文件名)
        return None


# ============================ 底栏排版搜索 ============================

def 试排(分区: list[tuple[str, list[dict]]], 格宽px: float) -> list[list[tuple]]:
    """按像素装箱：区优先整块落位（当前行放不下就整体挪到下一行），
    只有连一行都放不下的超长区才拆开，且先填满当前行的剩余格子再续到下一行。
    返回 行们：每行是 [(区名, 标签, 条目们, 起始px)]。"""
    行们: list[list[tuple]] = []
    当前: list[tuple] = []
    已用 = 0.0
    单区容量 = max(int(轴宽px // 格宽px), 1)

    def 换行():
        nonlocal 当前, 已用
        if 当前:
            行们.append(当前)
        当前, 已用 = [], 0.0

    for 区名, 条目们 in 分区:
        n = len(条目们)
        整区放得下 = n <= 单区容量
        剩余 = n
        while 剩余 > 0:
            空余 = int((轴宽px - 已用 - (区间隙px if 当前 else 0.0)) // 格宽px)
            if 整区放得下:
                取 = 剩余 if 空余 >= 剩余 else 0   # 当前行放不下整个区 → 整区挪到下一行
            else:
                取 = min(空余, 剩余)               # 超长区：先填满当前行剩余格子
            if 取 <= 0:
                换行()
                continue
            起 = 已用 + (区间隙px if 当前 else 0.0)
            当前.append((区名, "", 条目们[n - 剩余:n - 剩余 + 取], 起))
            已用 = 起 + 取 * 格宽px
            剩余 -= 取
    换行()

    # 被拆开的区在标题行标出 1/2、2/2
    总数: dict[str, int] = {}
    for 行 in 行们:
        for 区名, _, _, _ in 行:
            总数[区名] = 总数.get(区名, 0) + 1
    序号: dict[str, int] = {}
    for 行 in 行们:
        for i, (区名, _, 块, 起) in enumerate(行):
            序号[区名] = 序号.get(区名, 0) + 1
            行[i] = (区名, 区名 if 总数[区名] == 1
                     else f"{区名} {序号[区名]}/{总数[区名]}", 块, 起)
    return 行们


def 行填充率(行: list[tuple], 格宽px: float) -> float:
    _, _, 块, 起 = 行[-1]
    return (起 + len(块) * 格宽px) / 轴宽px


def 选版面(分区: list[tuple[str, list[dict]]]) -> tuple[list[list[tuple]], int]:
    """枚举格宽 → 打分选最优：行数最少 > 填得最满 > 格宽最接近理想值"""
    最优 = None
    for 格宽px in range(格宽最小px, 格宽最大px + 1):
        行们 = 试排(分区, 格宽px)
        if not 行们:
            continue
        填充 = [行填充率(行, 格宽px) for 行 in 行们]
        平均, 最差 = sum(填充) / len(填充), min(填充)
        切块数 = sum(len(行) for 行 in 行们) - len(分区)
        分 = (-8.0 * len(行们)                       # 行数越少图越矮
              - 3.0 * (1 - 平均)                      # 整体填得越满越好
              - 1.5 * (1 - 最差)                      # 别出现空荡荡的一行
              - 5.0 * abs(格宽px - 理想格宽px) / 理想格宽px   # 格子别太挤也别太空
              - 4.0 * 切块数)                         # 尽量保持区的完整性
        if 最优 is None or 分 > 最优[0]:
            最优 = (分, 格宽px, 行们)
    if 最优 is None:
        return [], 理想格宽px
    return 最优[2], 最优[1]


# ============================ 画布 ============================

背景透明度 = 0.55         # 背景图叠加时的 alpha
# 压暗后背景亮度 p95 的目标值（0~1）：越大背景越清楚。
# 取 0.27 是为了让两张性格不同的背景图各自保留反差比例（固定系数会把它们压成同一种纹理）。
# 背景图自带的 logo/水印不属于我们要处理的问题，素材什么样就是什么样。
背景目标P95 = 0.27


def 压暗系数(底图: np.ndarray, 深底色: str) -> float:
    """按源图亮度反解压暗系数，使合成后的 p95 落在目标值上。

    固定系数（原来是 0.42）会把两张性格完全不同的图压成同一种纹理：
    实测输入反差差 15%，输出极差却完全相同。改成按图反解后，每张图保留自己的
    反差比例，而整体仍然是"有氛围的暗纹理"。
    """
    源p95 = float(np.percentile(底图.mean(axis=2), 95))
    if 源p95 <= 0.02:
        return 0.42
    r, g, b = (int(深底色[i:i + 2], 16) / 255 for i in (1, 3, 5))
    底亮度 = 0.2126 * r + 0.7152 * g + 0.0722 * b
    系数 = (背景目标P95 - 底亮度 * (1 - 背景透明度)) / (源p95 * 背景透明度)
    return float(np.clip(系数, 0.30, 0.55))


def 建分区画布(事件数: int, 行数: int, 主题: 主题, 背景路径: str | Path):
    """从上到下：页眉、甘特图、行数 行底栏。每段高度按像素给定，
    再用 0 间距的 GridSpec 精确落位（height_ratios 的一个单位 = 一个像素）"""
    plt.rcParams["font.size"] = 10
    甘特高px = 甘特轴带px + max(事件数, 1) * 甘特行高px + 甘特底px
    比例 = [页眉高px, 页眉间距px, 甘特高px, 甘特间距px]
    for i in range(max(行数, 0)):
        if i:
            比例.append(行间距px)
        比例.append(行高px)
    总高px = sum(比例) + 边距下px
    fig = plt.figure(figsize=(图宽px / DPI, 总高px / DPI), dpi=DPI, facecolor=主题.深底)
    # 背景图铺满整张画布（figimage 垫在所有内容之下），压暗后垫底
    try:
        底图 = 缩放图片(str(背景路径), 图宽px, 总高px)
        底图 = set_alpha_channel(底图, 背景透明度)
        底图[:, :, :-1] *= 压暗系数(底图[:, :, :-1], 主题.深底)
        fig.figimage(底图, 0, 0, zorder=-3)
    except Exception:
        logger.warning("背景图绘制失败，仅用底色: %s", 背景路径)
    gs = fig.add_gridspec(
        nrows=len(比例), ncols=1, height_ratios=比例, hspace=0.0,
        left=边距左px / 图宽px, right=1 - 边距右px / 图宽px,
        top=1.0, bottom=边距下px / 总高px,
    )
    return fig, gs, fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[2, 0])


def 行轴(fig, gs, 行号: int):
    """第 行号 行底栏的 ax（在第 2 行甘特之后的 4 + 2×行号 行）"""
    return fig.add_subplot(gs[4 + 2 * 行号, 0])


# ============================ 页眉 ============================

def 填页眉(ax, fig, 主题: 主题, 现在: datetime, 标题: str = 图标题) -> None:
    """页眉直接坐在整图背景上，只补一层左侧渐变保证标题可读"""
    bb = ax.get_position()
    宽 = bb.width * fig.bbox.width
    高 = bb.height * fig.bbox.height
    ax.set_xlim(0, 宽)
    ax.set_ylim(0, 高)
    ax.set_aspect("auto")
    ax.set_axis_off()

    # 横向渐变 × 纵向收尾：纵向在页眉下沿收到 0，避免与页面之间出现硬边
    遮罩色 = [int(主题.更深[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    横 = np.linspace(0.88, 0.10, 256) ** 1.3
    纵 = np.ones(256)
    收尾 = int(256 * 0.62)
    纵[收尾:] = np.linspace(1.0, 0.0, 256 - 收尾) ** 1.4
    渐变 = np.zeros((256, 256, 4))
    渐变[:, :, 0:3] = 遮罩色
    渐变[:, :, 3] = 纵[:, None] * 横[None, :]
    ax.imshow(渐变, extent=(0, 宽, 0, 高), aspect="auto",
              interpolation="bilinear", zorder=1)

    # 左：标题（只留标题，去掉 kicker 与英文副标题这类装饰）
    ax.text(30, 高 / 2, 标题, fontsize=30, color=主题.主文, family=标题族,
            ha="left", va="center", zorder=4, fontweight=粗字重,
            path_effects=粗体(主题.主文, 1.0))

    # 右：数据来源块（日期区间在甘特图里已经表达，这里换成来源与更新时间）
    右 = 宽 - 30
    ax.add_patch(Rectangle((右 - 340, 高 / 2 - 30), 4, 60,
                           facecolor=主题.今天, edgecolor="none", zorder=4))
    ax.text(右, 高 / 2 + 12, "数据来源 PRTS Wiki", fontsize=17, color=主题.主文,
            ha="right", va="center", zorder=4, fontweight=粗字重,
            path_effects=粗体(主题.主文, 0.8))
    ax.text(右, 高 / 2 - 18, f"更新于 {现在:%Y-%m-%d %H:%M}", fontsize=10.5,
            color=主题.次文, ha="right", va="center", zorder=4)


# ============================ 甘特图 ============================

def 填甘特区(ax, fig, 记录, 主题: 主题, 左边界: datetime, 右边界: datetime,
            现在: datetime) -> None:
    """整幅绘图区 + 顶部日期轴带 + 每日竖网格 + TODAY 通栏线；
    事件名写在条上（沿用原版做法），条太短放不下时用箭头引到条外"""
    bb = ax.get_position()
    轴宽 = bb.width * fig.bbox.width
    轴高 = bb.height * fig.bbox.height
    ax.set_xlim(0, 轴宽)
    ax.set_ylim(0, 轴高)
    ax.set_aspect("auto")
    ax.set_axis_off()
    ax.set_facecolor("none")

    总小时 = (右边界 - 左边界).total_seconds() / 3600
    绘图宽px = 轴宽 - 甘特左列px
    顶 = 轴高 - 甘特轴带px          # 轴带下沿
    总天 = (右边界 - 左边界).days
    今天日序 = (现在.replace(hour=0, minute=0, second=0, microsecond=0) - 左边界).days

    def x(小时: float) -> float:
        return 甘特左列px + 小时 / 总小时 * 绘图宽px

    显示 = list(reversed(记录))   # 倒序：卡池在上、长期在下（沿用原图观感）
    弧度 = 组弧度表()
    名字号 = 15

    def 画合并行(行, 条色, y0, y中, 条高) -> None:
        """把 N 个常驻条目画在**同一行**里：条铺满全图、按数量斜切等分、每段写名字。

        分隔用**斜线**而不是竖线：甘特区里的竖线是日期网格，竖着切会被读成"某个时间点"，
        斜切才看得出"这几条是并列的，不是首尾相接"。
        """
        x0, x1 = x(0), x(总小时)
        条 = FancyBboxPatch((x0, y0), x1 - x0, 条高,
                           boxstyle="round,pad=0,rounding_size=2.5",
                           facecolor=条色, edgecolor="none", zorder=3)
        条.set_path_effects([SimplePatchShadow(offset=(0, -3), alpha=0.30), Normal()])
        ax.add_patch(条)

        段宽 = (x1 - x0) / len(行)
        斜量 = 条高 * 0.45      # 斜线的水平投影：太立像竖线，太平像斜杠
        字色 = 主题.对色(条色)
        for k, 条目 in enumerate(行):
            段左 = x0 + k * 段宽
            if k:
                ax.add_line(Line2D([段左 - 斜量 / 2, 段左 + 斜量 / 2], [y0, y0 + 条高],
                                   color=主题.更深, linewidth=3.2, alpha=0.78,
                                   solid_capstyle="round", zorder=4))
            ax.text(段左 + 段宽 / 2, y中, 展示名(条目.名称), fontsize=条名_字号, color=字色,
                    ha="center", va="center", zorder=4, clip_path=条, fontweight=条名_字重,
                    path_effects=粗体(字色, 条名_描边))

    # 行 = 若干条目：铺满全图的常驻条并成一行，其余各自一行（见 `分行`）
    行们 = 分行(显示, 左边界, 右边界)
    行标签们 = [组标签(行[0]) for 行 in 行们]

    # 标签相同的连续**行**归为一个功能块，块内给左列一条色轨、块间加分隔线，
    # 这样即使相邻两组的颜色相近，也能一眼看出分组边界
    组们: list[tuple[int, int, str]] = []
    i = 0
    while i < len(行标签们):
        j = i
        while j + 1 < len(行标签们) and 行标签们[j + 1] == 行标签们[i]:
            j += 1
        组们.append((i, j, 行标签们[i]))
        i = j + 1
    for 起, 止, 标签 in 组们:
        组色 = 主题.大色块(弧度.get(标签, 0.0))
        ax.add_patch(Rectangle((0, 顶 - (止 + 1) * 甘特行高px), 甘特左列px,
                               (止 - 起 + 1) * 甘特行高px,
                               facecolor=组色, alpha=0.17, edgecolor="none", zorder=0.6))
        # 组名写在**整组的垂直中心**：跨多行时那是视觉中心，而不是"只属于第一行"；
        # 组内每行不再重复写，靠左列这条色轨认（颜色仍与条色同源，一眼对上）
        ax.text(18, 顶 - (起 + (止 - 起 + 1) / 2) * 甘特行高px,
                标签, fontsize=11.5,
                color=组色, ha="left", va="center", zorder=4,
                fontweight=粗字重, path_effects=粗体(组色, 0.6))
    for 起, _, _ in 组们[1:]:
        y = 顶 - 起 * 甘特行高px
        ax.add_line(Line2D([0, 轴宽], [y, y], color=主题.主文, alpha=0.26,
                           linewidth=1.8, zorder=2.6))


    # 每日竖网格
    for d in range(总天 + 1):
        xx = x(d * 24)
        ax.add_line(Line2D([xx, xx], [0, 顶], color=主题.网格, linewidth=1, zorder=1))

    # 周末柱带（白）与今天柱带（强调色）：一眼看出休息日与今天
    一格宽 = 绘图宽px * 24 / 总小时
    for d in range(总天):
        日 = 左边界 + timedelta(days=d)
        if 日.weekday() >= 5:
            ax.add_patch(Rectangle((x(d * 24), 0), 一格宽, 顶, facecolor="white",
                                   alpha=0.09, edgecolor="none", zorder=1.4))
    今天柱 = x(24 * 今天日序)
    ax.add_patch(Rectangle((今天柱, 0), 一格宽, 顶, facecolor=主题.今天,
                           alpha=0.28, edgecolor="none", zorder=1.5))

    # 行
    for i, 行 in enumerate(行们):
        代表 = 行[0]
        条色 = 主题.大色块(弧度.get(组标签(代表), 0.0))
        y顶 = 顶 - i * 甘特行高px
        y底 = y顶 - 甘特行高px

        ax.add_line(Line2D([0, 轴宽], [y底, y底], color=主题.分隔, linewidth=1, zorder=2))
        ax.add_patch(Rectangle((0, y底), 7, 甘特行高px, facecolor=条色,
                               edgecolor="none", zorder=3))
        条高 = 甘特行高px * 0.60
        y0 = y底 + (甘特行高px - 条高) / 2
        y中 = y0 + 条高 * 0.5

        if len(行) > 1:            # 常驻合并行：斜切等分
            画合并行(行, 条色, y0, y中, 条高)
            continue

        条目 = 代表
        名 = 展示名(条目.名称)
        始, 终 = 条目.开始, 条目.结束
        起小时 = max((始 - 左边界).total_seconds() / 3600, 0)
        止小时 = min((终 - 左边界).total_seconds() / 3600, 总小时)
        if 止小时 <= 起小时:
            continue
        x0, x1 = x(起小时), x(止小时)
        # 小圆角：dpi 150 下 1 数据单位 = 1 像素，所以 rounding_size 就是像素值；
        # pad=0 是必须的，否则 boxstyle 会把矩形向外撑开
        条 = FancyBboxPatch((x0, y0), x1 - x0, 条高,
                            boxstyle="round,pad=0,rounding_size=2.5",
                            facecolor=条色, edgecolor="none", zorder=3)
        条.set_path_effects([SimplePatchShadow(offset=(0, -3), alpha=0.30), Normal()])
        ax.add_patch(条)

        # 名字：优先写在条里；条太短就引到条外（右优先，其次左侧）。
        # 两处共用 条名_字号 / 条名_字重 / 条名_描边，只有颜色跟底色走
        字色 = 主题.对色(条色)
        名宽 = 文本宽(名, 条名_字号, weight=条名_字重)
        条内够放 = x1 - x0 >= 名宽 + 26
        右够 = 轴宽 - x1 >= 名宽 + 60
        左够 = x0 >= 名宽 + 60
        if 条内够放:
            ax.text((x0 + x1) / 2, y中, 名, fontsize=条名_字号, color=字色,
                    ha="center", va="center", zorder=4, clip_path=条, fontweight=条名_字重,
                    path_effects=粗体(字色, 条名_描边))
        elif 右够 or 左够:
            靠右 = 右够
            锚x = x1 if 靠右 else x0
            ax.annotate(名, xy=(锚x, y中), xytext=(锚x + (14 if 靠右 else -14), y中),
                        arrowprops=dict(arrowstyle="-", color=主题.次文, lw=1.2),
                        fontsize=条名_字号, color=主题.主文, fontweight=条名_字重,
                        path_effects=粗体(主题.主文, 条名_描边),
                        ha="left" if 靠右 else "right", va="center", zorder=4)

    # 顶部日期轴带（半透明，背景图仍能透出）+ 左列右边界
    ax.add_patch(Rectangle((0, 顶), 轴宽, 甘特轴带px, facecolor=主题.更深,
                           alpha=0.82, edgecolor="none", zorder=7))
    ax.add_line(Line2D([0, 轴宽], [顶, 顶], color=主题.分隔, linewidth=1, zorder=8))
    ax.add_line(Line2D([甘特左列px, 甘特左列px], [0, 轴高], color=主题.分隔,
                       linewidth=1, zorder=8))
    上次右 = -1e9
    for d in range(总天 + 1):
        日 = 左边界 + timedelta(days=d)
        if 日 > 右边界:
            break
        xx = x(d * 24)
        是今天 = 日.date() == 现在.date()
        轴色 = 主题.今天 if 是今天 else 主题.分隔
        ax.add_line(Line2D([xx, xx], [顶, 轴高], color=轴色,
                           linewidth=3 if 是今天 else 1, zorder=9))
        # 每天一个刻度；只在真的放不下时才跳过（今天永远保留）
        # 注：文本宽度按 11 号估，实际绘制用的是 11.5 号（历史遗留，见 docs 记录）
        字宽 = 文本宽(f"{日:%m/%d}", 11, family=等宽)
        贴左 = xx + 8 + 字宽 < 轴宽
        左 = xx + 8 if 贴左 else xx - 8 - 字宽
        if 左 < 上次右 + 6 and not 是今天:
            continue
        上次右 = 左 + 字宽
        轴字色 = 主题.今天 if 是今天 else 主题.主文
        ax.text(xx + (8 if 贴左 else -8), 顶 + 42, f"{日:%m/%d}", fontsize=11.5,
                color=轴字色, family=等宽,
                ha="left" if 贴左 else "right", va="center",
                zorder=10, fontweight=粗字重 if 是今天 else "normal",
                path_effects=粗体(轴字色, 0.7) if 是今天 else None)
        ax.text(xx + (8 if 贴左 else -8), 顶 + 17, f"周{周名[日.weekday()]}",
                fontsize=10, color=主题.今天 if 是今天 else 主题.次文,
                ha="left" if 贴左 else "right", va="center", zorder=10)


# ============================ 底栏卡片 ============================

def _色带(色: str, 场: np.ndarray, 最强: float) -> np.ndarray:
    """把 alpha 场（0~1）乘上最强值后铺成本区色的 RGBA 图，用于面板上的渐变修饰"""
    rgb = [int(色[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    图 = np.zeros((*场.shape, 4))
    图[:, :, 0:3] = rgb
    图[:, :, 3] = 场 * 最强
    return 图


def 圆角图标(arr: np.ndarray, 边长px: int, 描边色: tuple[int, ...]) -> np.ndarray:
    """方形头像裁圆角 + 描一圈细边（4 倍超采样后缩回，保证边缘干净）"""
    倍 = 4
    大 = 边长px * 倍
    描 = 头像描边px * 倍
    半径 = max(int(大 * 头像圆角比), 2)
    图 = PILimage.fromarray(arr).convert("RGBA").resize((大, 大), PILimage.LANCZOS)
    遮罩 = PILimage.new("L", (大, 大), 0)
    ImageDraw.Draw(遮罩).rounded_rectangle(
        [描, 描, 大 - 1 - 描, 大 - 1 - 描], radius=max(半径 - 描, 1), fill=255)
    图.putalpha(ImageChops.multiply(图.getchannel("A"), 遮罩))
    画布 = PILimage.new("RGBA", (大, 大), (0, 0, 0, 0))
    ImageDraw.Draw(画布).rounded_rectangle(
        [0, 0, 大 - 1, 大 - 1], radius=半径, outline=描边色, width=描)
    画布.alpha_composite(图)
    return np.asarray(画布.resize((边长px, 边长px), PILimage.LANCZOS))


def 填行(ax, fig, 行: list[tuple], 格宽px: float, 主题: 主题) -> None:
    """一行底栏：每个区一块面板（面板底 + 顶部色带 + 标题行 + 头像 + 干员名）"""
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor("none")
    bb = ax.get_position()
    轴宽 = bb.width * fig.bbox.width
    轴高 = bb.height * fig.bbox.height
    ax.set_xlim(0, 轴宽)
    ax.set_ylim(0, 轴高)
    ax.set_aspect("auto")

    名字字号 = max(12, min(14, int(格宽px / 12)))
    副题字号 = 名字字号 - 2
    名字px = 名字字号 / 72 * DPI
    副题px = 副题字号 / 72 * DPI
    固定px = 顶条px + 标题行px + 12 + 9 + 名字px + 5 + 副题px + 10
    边长 = int(max(min(格宽px - 2 * 格内边距px, 最大图标px, 轴高 - 固定px), 40))
    图标顶y = 轴高 - (顶条px + 标题行px + 12)
    图标底y = 图标顶y - 边长
    名字顶y = 图标底y - 9
    副题顶y = 名字顶y - 名字px - 5
    题下y = 轴高 - 顶条px - 标题行px
    弧度 = 区弧度表()
    描边RGB = 主题.描边RGB()

    for 区名, 标签, 条目们, 起px in 行:
        卡宽 = len(条目们) * 格宽px
        t = 弧度.get(区名, 0.0)
        色 = 主题.标题色(t, 底栏带_亮度)
        # 卡高按内容走：只有干员名（凭证）就没有第二条的位置，不留空
        有两行 = any(条目.get("名称") for 条目 in 条目们)
        卡底y = 副题顶y - 副题px - 10 if 有两行 else 名字顶y - 名字px - 10
        卡高 = 轴高 - 卡底y

        # 面板：轻微圆角（直角太硬），色带与卡片共用同一个圆角轮廓
        卡 = FancyBboxPatch((起px + 卡圆角px, 卡底y + 卡圆角px),
                            卡宽 - 2 * 卡圆角px, 卡高 - 2 * 卡圆角px,
                            boxstyle=f"round,pad={卡圆角px},rounding_size={卡圆角px}",
                            facecolor=主题.面板底(t), edgecolor="none", zorder=1)
        卡.set_path_effects([SimplePatchShadow(offset=(0, -4), alpha=0.35), Normal()])
        ax.add_patch(卡)
        # 标题带：从卡片**最顶上**一路渐隐到底（不是"标题行下沿才起渐变"，那样像贴了一块色）
        纵 = np.linspace(0.0, 1.0, 128) ** 底栏带_曲线
        带 = ax.imshow(_色带(色, 纵 * np.ones((1, 128)), 底栏带_不透明),
                       extent=(起px, 起px + 卡宽, 卡底y, 轴高), aspect="auto",
                       zorder=1.2, interpolation="bilinear", origin="lower")
        带.set_clip_path(卡)            # 让色带跟着圆角收紧，不然四角会冒出去
        # 标题压在本区深色字上（色带够淡，正是为它让路）；位置往下压 1/6 行高（6px），
        # 免得离卡片上沿太近、离头像又太远，上下留白看起来就对称了
        题色 = 主题.面板标题色(t)
        ax.text(起px + 16, 题下y + 标题行px / 3, 标签, fontsize=15,
                color=题色, family=标题族, ha="left", va="center", zorder=3,
                fontweight=粗字重, path_effects=粗体(题色, 0.9))

        for j, 条目 in enumerate(条目们):
            cx = 起px + j * 格宽px + 格宽px / 2
            arr = 载图标数组(条目.get("图标文件名", ""))
            if arr is not None:
                ax.imshow(圆角图标(arr, 边长, 描边RGB), aspect="auto",
                          interpolation="none",
                          extent=(cx - 边长 / 2, cx + 边长 / 2, 图标底y, 图标顶y),
                          zorder=2)
            ax.text(cx, 名字顶y, 条目.get("干员", ""), fontsize=名字字号, ha="center", va="top",
                    color=主题.面板题, zorder=3, fontweight=粗字重,
                    path_effects=粗体(主题.面板题, 0.7))
            名称 = 条目.get("名称")
            if 名称:
                副题 = 截到宽(f"· {名称}", 格宽px - 6, 副题字号)
                ax.text(cx, 副题顶y, 副题, fontsize=副题字号, ha="center", va="top",
                        color=主题.面板次文, zorder=3)


# ============================ 出图 ============================

def 建分区(新增: dict) -> list[tuple[str, list[dict]]]:
    """新增预告 JSON → 底栏三区；模组名与干员名高度重复，展示层去掉"""
    分区: list[tuple[str, list[dict]]] = []
    for 名 in 区名表:
        条目们 = list(新增.get(新增键[名], []))
        if 名 == "新增模组":
            条目们 = [{**条目, "名称": ""} for 条目 in 条目们]
        分区.append((名, 条目们))
    return 分区


def 绘制甘特图(输出路径: str | Path, 分区: list[tuple[str, list[dict]]], 记录,
              主题: 主题, 左边界: datetime, 右边界: datetime,
              背景路径: str | Path, 现在: datetime,
              标题: str = 图标题) -> str:
    """搜索底栏版面 → 建画布 → 画页眉/甘特/底栏 → 存图；返回版面概况"""
    _确保字体就绪()
    有效 = [(区名, 条目们) for 区名, 条目们 in 分区 if 条目们]
    底栏行们, 格宽px = 选版面(有效)
    # ⚠️ 两个"行"不是一回事：`底栏行们` 是底栏的卡片行，甘特的行数得按 `分行()` 算——
    # 铺满全图的常驻条会并成一行，还用 len(记录) 就会在甘特底下多留一块空白（2026-09-24 修）。
    甘特行数 = len(分行(记录, 左边界, 右边界))
    fig, gs, ax_页眉, ax_chart = 建分区画布(甘特行数, len(底栏行们), 主题, 背景路径)
    填页眉(ax_页眉, fig, 主题, 现在, 标题)
    填甘特区(ax_chart, fig, 记录, 主题, 左边界, 右边界, 现在)
    for r, 行 in enumerate(底栏行们):
        填行(行轴(fig, gs, r), fig, 行, 格宽px, 主题)
    目标 = Path(输出路径)
    目标.parent.mkdir(parents=True, exist_ok=True)
    try:
        fig.savefig(目标, dpi=DPI, facecolor=fig.get_facecolor())
    finally:
        plt.close(fig)
    if not 底栏行们:
        return "无底栏条目"
    概况 = " + ".join(" | ".join(f"{标签}×{len(块)}" for _, 标签, 块, _ in 行)
                     for 行 in 底栏行们)
    return f"{len(底栏行们)} 行 / 格宽{格宽px:.0f}px / {概况}"
