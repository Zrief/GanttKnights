from __future__ import annotations

from datetime import datetime, timedelta

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd
from PIL import Image as PILimage

from src.config import settings
from src.绘图_颜色 import set_alpha_channel

WEEK_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _缩放图片(路径: str, 目标宽: int, 目标高: int) -> np.ndarray:
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


def 创建画布(背景路径: str, 纹理路径: str, 事件数: int) -> tuple[plt.Figure, plt.Axes]:
    plt.rcParams["font.sans-serif"] = [settings.font_family]
    plt.rcParams["font.size"] = settings.font_size
    fig = plt.figure(figsize=settings.fig_size, facecolor=settings.fig_facecolor)
    ax = plt.subplot(111, frameon=False)

    dpi = fig.dpi
    图宽 = round(settings.fig_size[0] * dpi)
    图高 = round(settings.fig_size[1] * dpi)

    bg_arr = _缩放图片(背景路径, 图宽, 图高)
    tx_arr = _缩放图片(纹理路径, 图宽, 图高) if 纹理路径 else None

    bg_img = set_alpha_channel(bg_arr, settings.bg_alpha)
    bg_img[:, :, :-1] = bg_img[:, :, :-1] * settings.bg_brightness
    fig.figimage(bg_img, 0, 0, zorder=-3)

    if tx_arr is not None:
        tx_img = set_alpha_channel(tx_arr, settings.texture_alpha)
        fig.figimage(tx_img, 0, 0, zorder=-2)

    ax.grid(True, which="major", linestyle="--", color=[0.2, 0.2, 0.2], linewidth=1)
    ax.grid(True, which="minor", linestyle=":", color="gray", linewidth=0.75)

    高亮 = settings.min_bar_hours
    ax.fill_betweenx([-0.5, max(事件数 - 0.5, 0)], 高亮, 高亮 + 24, color="white", alpha=0.3)
    return fig, ax


def plot_events(
    df: pd.DataFrame,
    left_border: datetime,
    right_border: datetime,
    colors: list[str],
    ax: plt.Axes,
    min_bar_hours: int | None = None,
) -> None:
    if min_bar_hours is None:
        min_bar_hours = settings.min_bar_hours

    total_hours = _hours_between(left_border, right_border)

    for idx, name in enumerate(df.iloc[:, 0]):
        start_time = df.iloc[idx, 1]
        end_time = df.iloc[idx, 2]

        bar_left = max(_hours_between(left_border, start_time), -1)
        raw_width = min(
            _hours_between(start_time, end_time),
            _hours_between(left_border, end_time),
            total_hours - max(bar_left, 0),
        )
        bar_width = raw_width

        if (
            _hours_between(left_border, end_time) <= 0
            or bar_left >= total_hours
            or bar_left + bar_width < min_bar_hours
        ):
            continue

        ax.barh(
            y=idx,
            width=bar_width,
            left=bar_left,
            edgecolor="k",
            linewidth=1.618,
            color=colors[idx % len(colors)],
            alpha=0.75,
            joinstyle="bevel",
        )
        _draw_label(ax, idx, name, bar_left, bar_width, total_hours)


def _draw_label(
    ax: plt.Axes, idx: int, name: str, bar_left: float, bar_width: float,
    total_hours: float,
) -> None:
    visible_start = max(bar_left, 0)
    visible_width = bar_width - (visible_start - bar_left)
    if visible_width <= 0:
        return

    bar_end = bar_left + bar_width

    if visible_width > 3 * 24:
        # 足够宽，居中显示完整名称
        ax.text(x=visible_start + visible_width / 2, y=idx, s=name,
                va="center", ha="center", fontweight="bold")
    elif visible_width > 24:
        # 中等宽度，居中截断
        max_chars = int(visible_width // 8)
        if max_chars > 0:
            ax.text(x=visible_start + visible_width / 2, y=idx, s=name[:max_chars],
                    va="center", ha="center", fontweight="bold")
    else:
        # 窄条：用箭头将文字标在条外
        visible_end = min(bar_end, total_hours)
        right_space = total_hours - max(visible_end, 0)
        left_space = visible_start
        if right_space > left_space and right_space > 10:
            ax.annotate(name, xy=(bar_end, idx), xytext=(bar_end + 12, idx),
                        arrowprops=dict(arrowstyle="->", color="white", lw=1.5),
                        va="center", ha="left", fontweight="bold", color="white",
                        clip_on=True)
        elif left_space > 10:
            ax.annotate(name, xy=(visible_start, idx), xytext=(max(visible_start - 12, 0), idx),
                        arrowprops=dict(arrowstyle="->", color="white", lw=1.5),
                        va="center", ha="right", fontweight="bold", color="white",
                        clip_on=True)


def set_x_ticks(
    ax: plt.Axes,
    left_border: datetime,
    right_border: datetime,
) -> None:
    ax.minorticks_on()
    ax.tick_params(axis="both", which="major", direction="in", width=1, length=5)
    ax.tick_params(axis="both", which="minor", direction="in", width=1, length=2)
    ax.xaxis.set_minor_locator(MultipleLocator(12))

    positions = []
    labels = []
    current = left_border
    prev_month = 0

    while current <= right_border:
        offset_hours = _hours_between(left_border, current)

        if offset_hours == 0:
            labels.append(_fmt_first_tick(current))
            positions.append(offset_hours)
        elif current.month != prev_month:
            labels.append(current.strftime(f"%m月\n·\n周{WEEK_NAMES[current.weekday()]}"))
            positions.append(offset_hours)
        elif offset_hours % 24 == 0:
            labels.append(current.strftime(f"%d\n·\n周{WEEK_NAMES[current.weekday()]}"))
            positions.append(offset_hours)

        prev_month = current.month
        current += timedelta(hours=4)

    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontweight="bold", c="white")


def _fmt_first_tick(dt: datetime) -> str:
    wd = WEEK_NAMES[dt.weekday()]
    end_of_month = (dt.replace(month=(dt.month % 12) + 1, day=1) - timedelta(days=1))
    if dt.day + settings.left_offset_days + settings.right_offset_days - dt.weekday() < end_of_month.day:
        return dt.strftime(f"%m月\n·\n周{wd}")
    return dt.strftime(f"%d\n·\n周{wd}")


def _hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600
