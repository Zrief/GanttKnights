"""通用绘图件 — 与具体排版无关的图片准备与字体回退

只放两件被 src.绘图_排版 复用的东西：背景图 cover 缩放、中文字体注册与回退。
版面本身全部在 src.绘图_排版.py。
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image as PILimage

from .config import settings

logger = logging.getLogger(__name__)


def 缩放图片(路径: str | Path, 目标宽: int, 目标高: int) -> np.ndarray:
    """读取图片 → cover 缩放 → 居中裁剪 → 返回 float RGB (0~1)"""
    img = PILimage.open(路径).convert("RGB")
    sx = 目标宽 / img.width
    sy = 目标高 / img.height
    scale = max(sx, sy)
    新宽 = round(img.width * scale)
    新高 = round(img.height * scale)
    img = img.resize((新宽, 新高), PILimage.LANCZOS)
    left = (新宽 - 目标宽) // 2
    top = (新高 - 目标高) // 2
    img = img.crop((left, top, left + 目标宽, top + 目标高))
    return np.array(img, dtype=np.float64) / 255.0


def 设置字体() -> None:
    """注册 settings.font_path 指向的字体；缺失时回退到系统中文字体"""
    font_path = Path(settings.font_path)
    if font_path.exists():
        fm.fontManager.addfont(str(font_path))
        plt.rcParams["font.sans-serif"] = [settings.font_family]
        return
    # fallback: try system CJK fonts
    for candidate in ("Noto Sans CJK SC", "Noto Sans CJK JP", "Droid Sans Fallback", "AR PL UMing CN"):
        try:
            plt.rcParams["font.sans-serif"] = [candidate]
            fm.findfont(candidate, fallback_to_default=False)
            logger.warning("字体 %s 不存在，回退到 %s", settings.font_path, candidate)
            return
        except Exception:
            continue
    logger.warning("无可用中文字体，图形中文可能显示为方块")
