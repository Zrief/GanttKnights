from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    """流程级设置（路径 / 时间窗 / 请求量 / 字体）。

    版面尺寸与配色档位不放这里：它们属于排版内部规范，见 src/绘图_排版.py 与
    src/绘图_主题.py，整幅图的尺寸由数据量推导，不对外暴露。
    """

    bg_dir: str = str(ROOT_DIR / "背景图")
    all_data_path: str = str(ROOT_DIR / "数据" / "所有活动数据.csv")
    new_items_path: str = str(ROOT_DIR / "数据" / "新增预告.json")
    icon_cache_dir: str = str(ROOT_DIR / "数据" / "图片缓存")
    warning_path: str = str(ROOT_DIR / "数据" / "警告.txt")
    output_path: str = str(ROOT_DIR / "Gantt.jpg")

    api_limit: int = 50  # 全年活动约 40 个，一次 ask 查全，无需再补活动一览
    left_offset_days: int = 3
    right_offset_days: int = 22
    future_buffer_hours: int = 4

    font_family: str = "Noto Sans CJK SC"
    font_path: str = str(ROOT_DIR / "字体" / "NotoSansCJKsc-Regular.otf")


settings = Settings()


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
