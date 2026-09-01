from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    bg_dir: str = str(ROOT_DIR / "背景图")
    texture_dir: str = str(ROOT_DIR / "纹理")
    all_data_path: str = str(ROOT_DIR / "数据" / "所有活动数据.csv")
    data_path: str = str(ROOT_DIR / "数据" / "活动数据.csv")
    output_path: str = str(ROOT_DIR / "Gantt.jpg")

    num_colors: int = 8
    api_limit: int = 10
    left_offset_days: int = 3
    right_offset_days: int = 22
    min_bar_hours: int = 72
    future_buffer_hours: int = 4

    fig_size: tuple[int, int] = (16, 9)
    fig_facecolor: str = "silver"
    font_family: str = "SimHei"
    font_size: int = 16

    bg_alpha: float = 0.6
    texture_alpha: float = 0.2
    bg_brightness: float = 0.45


settings = Settings()


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
