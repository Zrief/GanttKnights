"""通用绘图件 — 与具体排版无关的图片准备。

这里只放背景图的 cover 缩放（带"解码结果"缓存）；**字体的注册与角色解析全在 `src/字体.py`**
（单一入口，它负责"随包 → 自定义 → 平台字体"三层候选与真粗体判定）。版面全部在 `src/绘图_排版.py`。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image as PILimage


@lru_cache(maxsize=4)
def _读并缩放(路径: str, 目标宽: int, 目标高: int, 指纹: tuple[int, int]) -> np.ndarray:
    """解码 + cover 缩放 + 居中裁剪，返回 **uint8** 数组。

    缓存里存 uint8（2400×1282×3 ≈ 9MB/张）：存 float64 的话一张就要 74MB 常驻内存，不值得。
    `指纹 = (mtime_ns, size)` 让背景图被替换后自动 miss。
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
    return np.asarray(img, dtype=np.uint8)


def 缩放图片(路径: str | Path, 目标宽: int, 目标高: int) -> np.ndarray:
    """读取图片 → cover 缩放 → 居中裁剪 → 返回 float RGB (0~1)

    实测那张 2.9MB 的 WebP 解码 + LANCZOS 缩放约 190ms；同一张背景在一天里会被反复用到
    （数据变了、面板开关变了、第二天再来一次），所以按"路径 + 目标尺寸 + 文件指纹"缓存 uint8 结果，
    每次只付一次 uint8→float64 转换（约 60ms）。
    """
    p = Path(路径)
    st = p.stat()
    arr = _读并缩放(str(p), 目标宽, 目标高, (st.st_mtime_ns, st.st_size))
    return arr.astype(np.float64) / 255.0
