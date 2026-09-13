"""字体注册：把 `字体/` 下的静态字重注册进 matplotlib，并给出"真粗体是否可用"。

为什么需要这个模块
------------------
本机的 `Noto Sans SC` 是**可变字体（VF）**，而 matplotlib 没有任何变体轴接口，只会渲染默认
实例 —— 实测默认权重是 Thin(100)，于是标题不仅加不粗，还偏细。缺 Bold 时 matplotlib 也只
warning 后降级，**不会伪粗**。所以必须用**静态独立字重**文件。

为什么不用衬线（2026-09 决定）
------------------------------
衬线只出现在页眉大标题与底栏分区标签两处，两处都是纯中文短串；而**所有候选字体的汉字
advance 都是 1.000em**（实测 Noto / 微软雅黑 / 宋体一致），换族对版面宽度零影响，纯粹是审美
选择。反过来，缺 `字体/` 时旧代码会把标题退到系统 `Noto Serif SC`（可变字体 → ExtraLight(200)），
标题反而更细、只能靠描边硬凑。故统一用无衬线粗体，少依赖一支 25MB 的字体文件。

`字体/` 目录不进 git（.gitignore），需要时按 OFL-1.1 自行放置：
  NotoSansCJKsc-Regular.otf / NotoSansCJKsc-Bold.otf
  NotoSansMono-Regular.ttf / NotoSansMono-Bold.ttf
下载：https://github.com/notofonts/noto-cjk/releases （Sans2.004 的 SC 包）
      https://github.com/notofonts/noto-fonts （Noto Sans Mono）
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

from .config import settings

logger = logging.getLogger(__name__)

# 字体目录取自 settings（默认 ROOT_DIR/字体，可用 GK_FONT_DIR 或构造参数覆盖）。
# 注意：不能在 import 期把它求值成常量——settings 是可注入的，求值太早就锁死了。
def 取字体目录() -> Path:
    return Path(settings.字体目录)

无衬线族 = "Noto Sans CJK SC"
等宽族 = "Noto Sans Mono"

# 文件 → (family, 字重)：同一 family 的多个字重必须同版本，matplotlib 才能按字重挑对。
# 两层两族：无衬线管正文与标题、等宽管数字与日期
# （思源黑的数字 advance 是 0.56em 而斜杠是 1em 全角，日期会被撑开，所以数字要单独一层）
字体表 = {
    "NotoSansCJKsc-Regular.otf": (无衬线族, "normal"),
    "NotoSansCJKsc-Bold.otf": (无衬线族, "bold"),
    "NotoSansMono-Regular.ttf": (等宽族, "normal"),
    "NotoSansMono-Bold.ttf": (等宽族, "bold"),
}

已注册 = False
真粗体可用 = False


def 注册字体() -> bool:
    """注册 字体/ 下的静态字重；返回"真粗体是否可用"（不可用时调用方应改用描边兜底）"""
    global 已注册, 真粗体可用
    if 已注册:
        return 真粗体可用

    字体目录 = 取字体目录()
    可用文件 = [名 for 名 in 字体表 if (字体目录 / 名).exists()]
    for 名 in 可用文件:
        try:
            fm.fontManager.addfont(str(字体目录 / 名))   # mpl≥3.8 会清 findfont 缓存
        except Exception:
            logger.warning("字体注册失败：%s", 名)

    真粗体可用 = (字体目录 / "NotoSansCJKsc-Bold.otf").exists()
    if not 真粗体可用:
        logger.warning("字体/ 里缺粗体文件，粗体请求将不会生效；调用方需用描边兜底")

    if 可用文件:
        plt.rcParams["font.sans-serif"] = [无衬线族, 等宽族]
        # 不使用衬线：把 serif 也指到无衬线族，避免任何漏网的 family="serif" 落到系统衬线
        # （那支是可变字体，默认实例只有 ExtraLight(200)）。
        plt.rcParams["font.serif"] = [无衬线族]
    plt.rcParams["axes.unicode_minus"] = False
    已注册 = True
    return 真粗体可用


def 命中检查() -> dict[str, str]:
    """自检：确认各字重真的命中 字体/ 里的文件，而不是系统那支可变字体"""
    注册字体()
    字体目录 = 取字体目录()
    结果 = {}
    for 名, (族, 字重) in 字体表.items():
        if not (字体目录 / 名).exists():
            continue
        try:
            路径 = Path(fm.findfont(fm.FontProperties(family=族, weight=字重),
                                    fallback_to_default=False))
            结果[f"{族}/{字重}"] = f"{路径.name}{'' if 路径.parent.resolve() == 字体目录.resolve() else '  ← 不是仓库文件!'}"
        except Exception as e:
            结果[f"{族}/{字重}"] = f"解析失败 {e}"
    return 结果
