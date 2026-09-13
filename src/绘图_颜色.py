"""颜色工具 — Oklab ⇄ sRGB 转换与 alpha 通道处理

只放底层数学与图像工具；配色（主色 / 副色 / 警告色的推导）在 src/绘图_主题.py，
排版层用 set_alpha_channel 给背景图叠透明度。
"""

from __future__ import annotations

import numpy as np

# ---- Oklab 转换矩阵 ----

_线性到LMS = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
])

_LMS到Oklab = np.array([
    [ 0.2104542553,  0.7936177850, -0.0040720468],
    [ 1.9779984951, -2.4285922050,  0.4505937099],
    [ 0.0259040371,  0.7827717662, -0.8086757660],
])

_Oklab到LMS = np.linalg.inv(_LMS到Oklab)

_LMS到线性 = np.linalg.inv(_线性到LMS)


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    """sRGB(0~1) → Linear RGB"""
    mask = c <= 0.04045
    out = np.where(mask, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return out


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    """Linear RGB → sRGB(0~1)：Oklab 反算可能得到轻微出界的负值，先夹到 0 再开幂"""
    c = np.clip(c, 0.0, None)
    mask = c <= 0.0031308
    out = np.where(mask, c * 12.92, 1.055 * (c ** (1 / 2.4)) - 0.055)
    return np.clip(out, 0.0, 1.0)


def _srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """(N,3) sRGB(0~1) → (N,3) Oklab"""
    lin = _srgb_to_linear(rgb)
    lms = lin @ _线性到LMS.T
    lms_cbrt = np.cbrt(lms.clip(0))
    lab = lms_cbrt @ _LMS到Oklab.T
    return lab


def _oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """(N,3) Oklab → (N,3) sRGB(0~1)"""
    lms_cbrt = lab @ _Oklab到LMS.T
    lms = lms_cbrt ** 3
    lin = lms @ _LMS到线性.T
    return _linear_to_srgb(lin)


def set_alpha_channel(image_data: np.ndarray, alpha_value: float) -> np.ndarray:
    if image_data.ndim < 2 or image_data.shape[2] not in (3, 4):
        raise ValueError("图像必须为 3 通道 (RGB) 或 4 通道 (RGBA)")

    if image_data.dtype.kind == 'f':
        alpha_val = np.clip(alpha_value, 0.0, 1.0)
    else:
        alpha_val = int(np.clip(round(alpha_value * 255), 0, 255))

    if image_data.shape[2] == 3:
        alpha = np.full(
            (image_data.shape[0], image_data.shape[1]),
            alpha_val,
            dtype=image_data.dtype,
        )
        return np.dstack((image_data, alpha))
    else:
        out = image_data.copy()
        out[:, :, 3] = alpha_val
        return out
