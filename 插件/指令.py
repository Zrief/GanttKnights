"""指令元数据 —— 命令名 / 别名 / 参数提示 / 示例 / 帮助条目的**唯一来源**。

沿用参考项目 `astrbot_plugin_ark_calendar` 的 `CommandSpec` 模式（其 `main.py:52-79`）：
`@filter.command(spec.name, alias=spec.alias_set)` 与帮助文本共用同一份定义，
避免"命令改了、帮助没改"。

约定：`name` / `aliases` **不含前导斜杠**（AstrBot 的指令名本来就不带），
`example` 里带斜杠，因为它面向用户。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    """一条指令的元数据。"""

    name: str
    aliases: tuple[str, ...] = ()
    summary: str = ""
    argument_hint: str = ""
    example: str = ""

    @property
    def alias_set(self) -> set[str]:
        """给 `@filter.command(name, alias=...)` 用（框架要求 set）。"""
        return set(self.aliases)

    def 调用串(self) -> str:
        """带参数提示的调用写法，如 `/方舟日程 <日期>`。"""
        串 = f"/{self.name}"
        return f"{串} {self.argument_hint}" if self.argument_hint else 串

    def 帮助条目(self) -> str:
        """帮助页里的一条：调用写法（含别名） + 一行说明。"""
        行 = self.调用串()
        if self.aliases:
            行 += "（别名：" + "、".join(f"/{别名}" for 别名 in self.aliases) + "）"
        return f"{行}\n{self.summary}"


# 指令定义顺序 = 帮助页顺序。新增指令只改这里与 main.py 的 handler 装饰器。
# 主指令叫「方舟日程」而不是「甘特图」：它是给用户看的东西（"今天有什么日程"），
# 而「甘特图」是画法；另外 `/甘特图` 与 `/甘特图状态` 这类子指令挤在同一个前缀下也容易看混。
甘特图命令 = CommandSpec(
    name="方舟日程",
    aliases=("方舟甘特",),
    summary="出图：近期活动一览（首次会抓取数据，之后几秒）。",
    example="/方舟日程",
)

订阅命令 = CommandSpec(
    name="订阅甘特图",
    aliases=(),
    summary="把当前会话加入每日推送（群聊、私聊都可以，多个会话各订各的）。",
    example="/订阅甘特图",
)

退订命令 = CommandSpec(
    name="退订甘特图",
    aliases=(),
    summary="把当前会话移出每日推送。",
    example="/退订甘特图",
)

状态命令 = CommandSpec(
    name="甘特图状态",
    aliases=(),
    summary="数据更新时间、最近一次变化、推送情况、本会话标识。",
    example="/甘特图状态",
)

刷新命令 = CommandSpec(
    name="甘特图刷新",
    aliases=("甘特图更新",),
    summary="强制重新抓取并重画（管理员）。",
    example="/甘特图刷新",
)

初始化命令 = CommandSpec(
    name="甘特图初始化",
    aliases=(),
    summary="全量重建数据（管理员）：补录剿灭轮换、复刻排期，平时用不到。",
    example="/甘特图初始化",
)

帮助命令 = CommandSpec(
    name="甘特图帮助",
    aliases=(),
    summary="这条帮助。",
    example="/甘特图帮助",
)

命令表: tuple[CommandSpec, ...] = (
    甘特图命令, 订阅命令, 退订命令, 状态命令, 刷新命令, 初始化命令, 帮助命令,
)


def 生成帮助文本(版本: str) -> str:
    """按 `命令表` 生成帮助页（不手写第二份指令清单）。"""
    行们 = [f"明日方舟甘特图 v{版本}", "", "指令"]
    for 命令 in 命令表:
        行们 += ["", 命令.帮助条目()]
    行们 += [
        "",
        "说明",
        "· 数据来自 PRTS Wiki，每天第一次出图时自动更新；数据看着缺内容就用「/甘特图初始化」重建。",
        "· 时间窗、底栏面板、背景图、每日推送都在插件配置里改。",
        "· 每日推送发到配置里的推送目标：在要推送的会话里发「/订阅甘特图」加入、「/退订甘特图」移出，也能在设置页里增删。",
    ]
    return "\n".join(行们)
