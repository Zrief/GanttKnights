"""通用绘图件 — 与具体排版无关的图片准备。

这里只放背景图的 cover 缩放；**字体的注册与角色解析全在 `src/字体.py`**（单一入口，
它负责"随包 → 自定义 → 平台字体"三层候选与真粗体判定）。版面全部在 `src/绘图_排版.py`。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image as PILimage


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
