"""通用绘图件 — 与具体排版无关的图片准备。

这里只放背景图的 cover 缩放；**字体的注册与角色解析全在 `src/字体.py`**
（单一入口，它负责"随包 → 自定义 → 平台字体"三层候选与真粗体判定）。版面全部在 `src/绘图_排版.py`。

> 阶段四曾在这里加过一层按"路径 + 文件指纹"的 `lru_cache`（省 ~190ms 解码 + 缩放）。
> 2026-09-14 按第一性原理拿掉了：一次出图只解码一次背景图，0.19s 相对整张图秒级的绘制时间
> 可以忽略；换来的是 8.8MB/张（2400×1282×3 uint8）的常驻内存，以及"忘了把指纹放进缓存键
> 就会一直用旧背景"这一类正确性风险。实测有无这一层的 JPEG 字节完全一致，所以拿掉它不改变任何像素。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image as PILimage


def 缩放图片(路径: str | Path, 目标宽: int, 目标高: int) -> np.ndarray:
    """读取图片 → cover 缩放 → 居中裁剪 → 返回 float RGB (0~1)

    实测那张 2.9MB 的 WebP 解码 + LANCZOS 缩放约 190ms；一次出图只走一次，
    直接解码比加一层缓存更简单也更省内存。
    """
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
    return np.asarray(img, dtype=np.uint8).astype(np.float64) / 255.0
