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

**只暴露"用户真的会调"的东西**（2026-09-14 瘦身）：字体不再进配置——自定义字体走两条既有路径
（插件目录 `字体/`，或 AstrBot 约定 `data/font.ttf` / `font-bold.ttf` / `font-mono.ttf`），
见 docs/插件化路线.md §5.4；请求条数与"进行中"宽限小时数也退到内核默认值（GK_* 可覆盖），
它们只会让用户把图配错。阶段四又拿掉了 `render.reuse_seconds`：签名缓存能自己判断
"什么都没变"，不需要用户填窗口秒数；要强行重画走 `/甘特图刷新`（阶段五）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 数值字段的夹取范围：(最小, 最大)。**与 _conf_schema.json 的 minimum/maximum 必须一致**。
范围: dict[str, tuple[int, int]] = {
    "left_offset_days": (0, 30),
    "right_offset_days": (7, 30),   # 上限 30：再长时色条被压窄，名字/刻度判定开始贴边（实测见文档）
    "remind_days": (1, 30),
}

真值串 = {"1", "true", "yes", "on", "是", "真", "开"}

# 底栏三个分区的名字。**必须与 `src/绘图_排版.py` 的 `区名表` 一致**——加载期不能 import
# 那个模块（它会拖进 matplotlib，1s 级阻塞），只能在这里复制一份，靠验证脚本钉住契约。
底栏区名 = ("凭证兑换", "新增时装", "新增模组")


@dataclass(frozen=True, slots=True)
class 运行配置:
    """一次出图用得上的全部配置（默认值与 `_conf_schema.json` 逐项一致）。"""

    # render
    标题: str = "近期活动一览"
    左边界天数: int = 3
    右边界天数: int = 22
    提醒天数: int = 3
    指定背景: str = ""
    背景目录: str = ""
    # panels
    凭证面板: bool = True
    时装面板: bool = True
    模组面板: bool = True
    # data
    每日自动更新: bool = True
    # push
    推送开关: bool = False
    推送时刻: str = "08:00"

    def 底栏分区(self) -> tuple[str, ...] | None:
        """要展示的底栏分区；三个都开时返回 None（走内核默认路径，行为与改造前一致）。"""
        开着 = tuple(名 for 名, 显示 in zip(底栏区名, (self.凭证面板, self.时装面板, self.模组面板),
                                            strict=True) if 显示)
        return None if len(开着) == len(底栏区名) else 开着

    def 推送时点(self) -> tuple[int, int]:
        """推送时刻 → (时, 分)；初始化时已被 `规范化时刻()` 归一，这里不会失败。"""
        时, 分 = self.推送时刻.split(":")
        return int(时), int(分)


推送时刻默认 = "08:00"
"""默认推送时刻。

> 为什么是 08:00 而不是 00:0x：明日方舟在北京时间 **04:00** 日切，`今天写过()` 也按自然日判断，
> 00:00–04:00 之间出图会拿到"还没换日"的数据。提示文案里要写清这一条（§16）。
"""


def 规范化时刻(值: Any) -> str:
    """读 `HH:MM` 形式的配置项，归一成零填充的字符串；坏值一律退回默认。

    `"8:5"` / `" 08:05 "` / `"08:05"` 都得到 `"08:05"`——展示与比较都需要单一形态。
    越界（`"25:00"`）、格式不对、非字符串都退回默认值，绝不让一个坏字符串把调度器搞崩。
    """
    if isinstance(值, str):
        try:
            时文本, 分文本 = 值.strip().split(":", 1)
            时, 分 = int(时文本), int(分文本)
        except (ValueError, TypeError):
            return 推送时刻默认
        if 0 <= 时 <= 23 and 0 <= 分 <= 59:
            return f"{时:02d}:{分:02d}"
    return 推送时刻默认


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
    panels = 读取节(config, "panels")
    data = 读取节(config, "data")
    push = 读取节(config, "push")

    def 整数(节: dict[str, Any], 键: str, 默认值: int) -> int:
        最小, 最大 = 范围[键]
        return 夹取整数(节.get(键), 默认值, 最小, 最大)

    return 运行配置(
        标题=读取文本(render.get("title"), 默认.标题) or 默认.标题,
        左边界天数=整数(render, "left_offset_days", 默认.左边界天数),
        右边界天数=整数(render, "right_offset_days", 默认.右边界天数),
        提醒天数=整数(render, "remind_days", 默认.提醒天数),
        指定背景=读取文本(render.get("background_file"), 默认.指定背景),
        背景目录=读取文本(render.get("background_dir"), 默认.背景目录),
        凭证面板=读取开关(panels.get("voucher"), 默认.凭证面板),
        时装面板=读取开关(panels.get("outfit"), 默认.时装面板),
        模组面板=读取开关(panels.get("module"), 默认.模组面板),
        每日自动更新=读取开关(data.get("auto_refresh_daily"), 默认.每日自动更新),
        推送开关=读取开关(push.get("enabled"), 默认.推送开关),
        推送时刻=规范化时刻(push.get("time")),
    )
