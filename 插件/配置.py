"""插件配置读取 —— `_conf_schema.json` → 运行配置（含越界夹取）。

两条纪律：

1. **默认值必须与 `_conf_schema.json` 一致**。AstrBot 首次加载会把 schema 的默认值
   写进配置文件，之后**存储值永远优先于 schema**——所以改默认值等于"老用户不跟随"，
   必须写进 CHANGELOG（见 docs/插件化路线.md §9）。
2. **越界值在读取处夹住**。`minimum` / `maximum` 只是给 WebUI 看的，AstrBot 的原生
   配置渲染器不读它们，用户手改配置文件、或旧版本残留值都可能越界（§9）。
   因此渲染参数一律经 `夹取整数()` 落地。

配置键用英文 snake_case（AstrBot 惯例，也便于 WebUI/HTTP 接口处理），
节名与 `_conf_schema.json` 的顶层键一一对应。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 数值字段的夹取范围：(最小, 最大)。**与 _conf_schema.json 的 minimum/maximum 必须一致**。
范围: dict[str, tuple[int, int]] = {
    "left_offset_days": (0, 30),
    "right_offset_days": (7, 60),
    "remind_days": (1, 30),
    "reuse_seconds": (0, 3600),
    "api_limit": (10, 200),
    "future_buffer_hours": (0, 24),
}

真值串 = {"1", "true", "yes", "on", "是", "真", "开"}


@dataclass(frozen=True, slots=True)
class 运行配置:
    """一次出图用得上的全部配置（默认值与 `_conf_schema.json` 逐项一致）。"""

    # render
    标题: str = "近期活动一览"
    左边界天数: int = 3
    右边界天数: int = 22
    提醒天数: int = 3
    复用窗口秒: int = 60
    随机背景: bool = True
    指定背景: str = ""
    # data
    每日自动更新: bool = True
    api上限: int = 50
    未来缓冲小时: int = 4
    # assets
    字体目录: str = ""
    背景目录: str = ""


def 读取节(config: Any, 节名: str) -> dict[str, Any]:
    """安全取一个 object 节：配置项缺失/类型不对时退化成空字典。"""
    节 = config.get(节名, {}) if hasattr(config, "get") else {}
    return 节 if isinstance(节, dict) else {}


def 夹取整数(值: Any, 默认值: int, 最小: int, 最大: int) -> int:
    """读一个整数配置项并夹到 [最小, 最大]；非数字（含 bool）退回默认值。

    bool 被显式排除：`int(True)` 会静默变成 1，而"勾选框被写成数字字段"属于配置错误，
    应当退回默认值而不是变成一个看似合法的数。
    """
    if isinstance(值, bool):
        return 默认值
    try:
        if isinstance(值, str):
            值 = 值.strip()
            if not 值:
                return 默认值
        数字 = int(值)
    except (TypeError, ValueError, OverflowError):
        return 默认值
    return max(最小, min(最大, 数字))


def 读取文本(值: Any, 默认值: str = "") -> str:
    return 值.strip() if isinstance(值, str) else 默认值


def 读取开关(值: Any, 默认值: bool) -> bool:
    if isinstance(值, bool):
        return 值
    if isinstance(值, str):
        return 值.strip().lower() in 真值串
    if 值 is None:
        return 默认值
    return bool(值)


def 读取配置(config: Any) -> 运行配置:
    """把 AstrBotConfig（或任何 dict-like）读成 `运行配置`。

    每次调用都重新读：WebUI 改配置后无需重载插件即可生效（AstrBotConfig 是同一个 dict 实例）。
    """
    默认 = 运行配置()
    render = 读取节(config, "render")
    data = 读取节(config, "data")
    assets = 读取节(config, "assets")

    def 整数(节: dict[str, Any], 键: str, 默认值: int) -> int:
        最小, 最大 = 范围[键]
        return 夹取整数(节.get(键), 默认值, 最小, 最大)

    return 运行配置(
        标题=读取文本(render.get("title"), 默认.标题) or 默认.标题,
        左边界天数=整数(render, "left_offset_days", 默认.左边界天数),
        右边界天数=整数(render, "right_offset_days", 默认.右边界天数),
        提醒天数=整数(render, "remind_days", 默认.提醒天数),
        复用窗口秒=整数(render, "reuse_seconds", 默认.复用窗口秒),
        随机背景=读取开关(render.get("random_background"), 默认.随机背景),
        指定背景=读取文本(render.get("background_file"), 默认.指定背景),
        每日自动更新=读取开关(data.get("auto_refresh_daily"), 默认.每日自动更新),
        api上限=整数(data, "api_limit", 默认.api上限),
        未来缓冲小时=整数(data, "future_buffer_hours", 默认.未来缓冲小时),
        字体目录=读取文本(assets.get("font_dir"), 默认.字体目录),
        背景目录=读取文本(assets.get("bg_dir"), 默认.背景目录),
    )
