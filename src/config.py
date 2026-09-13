"""流程级设置（路径 / 时间窗 / 请求量 / 字体）。

版面尺寸与配色档位不放这里：它们属于排版内部规范，见 绘图_排版.py 与
绘图_主题.py，整幅图的尺寸由数据量推导，不对外暴露。

## 覆盖顺序

`Settings(...)` 构造参数 > 环境变量 > 默认值（全部相对 `ROOT_DIR` 推导）。

环境变量的意义：让 CLI 与 AstrBot 插件共用同一套渲染内核，而各自的数据/素材
位置不同时不必改代码。插件侧应优先用构造参数注入，环境变量只是兜底。

## 关于 ROOT_DIR

`ROOT_DIR` 取自本文件位置，因此**指向代码所在目录**，与进程的工作目录无关。
但这同时意味着默认值把"代码目录"与"数据目录"混在一起——本机自用没问题，
若要分发则应通过构造参数或环境变量把数据指到别处。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

# —— 环境变量名 → 覆盖的目标字段 ——
# 这些变量**只在本模块被导入时读一次**。要改就得在导入前设好，
# 因此本模块必须在设置完环境变量之后再导入（CLI 的入口脚本已按此顺序处理）。
ENV_数据目录 = "GK_DATA_DIR"
ENV_素材目录 = "GK_ASSET_DIR"
ENV_字体目录 = "GK_FONT_DIR"
ENV_输出路径 = "GK_OUTPUT_PATH"
ENV_背景目录 = "GK_BG_DIR"


def _env路径(名: str) -> Path | None:
    """读一个目录/文件型环境变量；未设置或为空则返回 None"""
    值 = os.environ.get(名, "").strip()
    return Path(值) if 值 else None


@dataclass
class Settings:
    """流程级设置。

    路径字段默认全部相对 `ROOT_DIR` 推导；构造参数可逐个覆盖，
    也可以直接给 `数据目录` / `素材目录` 让所有路径整体搬家。
    """

    # —— 路径：数据（可写、可丢、不进 git）——
    数据目录: Path | None = None
    all_data_path: str | None = None
    new_items_path: str | None = None
    icon_cache_dir: str | None = None
    warning_path: str | None = None
    output_path: str | None = None

    # —— 路径：素材（随代码、只读）——
    素材目录: Path | None = None
    bg_dir: str | None = None

    # —— 时间窗 / 请求量 ——
    api_limit: int = 50  # 全年活动约 40 个，一次 ask 查全，无需再补活动一览
    left_offset_days: int = 3
    right_offset_days: int = 22
    future_buffer_hours: int = 4

    # —— 字体 ——
    字体目录: Path | None = None
    font_family: str = "Noto Sans CJK SC"
    font_path: str | None = None

    def __post_init__(self) -> None:
        # 默认值走环境变量兜底，再由构造参数覆盖
        数据目录 = Path(self.数据目录) if self.数据目录 else (
            _env路径(ENV_数据目录) or (ROOT_DIR / "数据")
        )
        素材目录 = Path(self.素材目录) if self.素材目录 else (
            _env路径(ENV_素材目录) or ROOT_DIR
        )
        字体目录 = Path(self.字体目录) if self.字体目录 else (
            _env路径(ENV_字体目录) or (素材目录 / "字体")
        )
        self.数据目录 = 数据目录
        self.素材目录 = 素材目录
        self.字体目录 = 字体目录

        env = {
            "all_data_path": _env路径("GK_DATA_CSV"),
            "new_items_path": _env路径("GK_NEW_ITEMS"),
            "icon_cache_dir": _env路径("GK_ICON_CACHE"),
            "warning_path": _env路径("GK_WARNING"),
            "output_path": _env路径(ENV_输出路径),
            "bg_dir": _env路径(ENV_背景目录),
        }

        # 未显式给定 → 环境变量 → 默认（相对各自的基准目录）
        self.all_data_path = str(self.all_data_path or env["all_data_path"]
                                 or (数据目录 / "所有活动数据.csv"))
        self.new_items_path = str(self.new_items_path or env["new_items_path"]
                                  or (数据目录 / "新增预告.json"))
        self.icon_cache_dir = str(self.icon_cache_dir or env["icon_cache_dir"]
                                  or (数据目录 / "图片缓存"))
        self.warning_path = str(self.warning_path or env["warning_path"]
                                or (数据目录 / "警告.txt"))
        # output_path 特例：渲染产物是"给人看的展示图"，历来与代码同级（README 引用它），
        # 因此默认挂在 素材目录 而非 数据目录；要改位置用 GK_OUTPUT_PATH。
        self.output_path = str(self.output_path or env["output_path"]
                               or (素材目录 / "Gantt.jpg"))
        self.bg_dir = str(self.bg_dir or env["bg_dir"] or (素材目录 / "背景图"))
        self.font_path = self.font_path or str(字体目录 / "NotoSansCJKsc-Regular.otf")


# 模块级单例：CLI 与插件在未注入时都用它（行为与改造前一致）
settings = Settings()


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
