"""指令元数据 —— 命令名 / 别名 / 参数提示 / 示例 / 帮助条目的**唯一来源**。

照抄参考物 `astrbot_plugin_ark_calendar` 的 `CommandSpec` 模式（其 `main.py:52-79`）：
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
        """带参数提示的调用写法，如 `/甘特图 <日期>`。"""
        串 = f"/{self.name}"
        return f"{串} {self.argument_hint}" if self.argument_hint else 串

    def 帮助条目(self) -> str:
        """帮助页里的一条：调用写法（含别名） + 一行说明。"""
        行 = self.调用串()
        if self.aliases:
            行 += "（别名：" + "、".join(f"/{别名}" for 别名 in self.aliases) + "）"
        return f"{行}\n{self.summary}"


# 指令定义顺序 = 帮助页顺序。新增指令只改这里与 main.py 的 handler 装饰器。
甘特图命令 = CommandSpec(
    name="甘特图",
    aliases=("方舟甘特", "舟甘特"),
    summary="生成明日方舟近期活动甘特图长图；数据与配置都没变时直接复用当天已画好的那张。",
    example="/甘特图",
)

状态命令 = CommandSpec(
    name="甘特图状态",
    aliases=(),
    summary="查看数据更新时间、出图缓存占用、每日推送状态与当前会话标识。",
    example="/甘特图状态",
)

刷新命令 = CommandSpec(
    name="甘特图刷新",
    aliases=("甘特图更新",),
    summary="强制重新抓取数据并重画（管理员）；平时不需要，数据看着不对时用。",
    example="/甘特图刷新",
)

初始化命令 = CommandSpec(
    name="甘特图初始化",
    aliases=("甘特图全量更新",),
    summary="全量重建数据（管理员）：连更老的已结束活动的公告一起扫，补录长期轮换与复刻排期"
            "（等价 cli.py --bootstrap --force）；数据看着缺内容时用一次。",
    example="/甘特图初始化",
)

帮助命令 = CommandSpec(
    name="甘特图帮助",
    aliases=(),
    summary="查看本插件全部指令。",
    example="/甘特图帮助",
)

命令表: tuple[CommandSpec, ...] = (甘特图命令, 状态命令, 刷新命令, 初始化命令, 帮助命令)


def 生成帮助文本(版本: str) -> str:
    """按 `命令表` 生成帮助页（不手写第二份指令清单）。"""
    行们 = [f"明日方舟近期活动甘特图 v{版本}", "", "指令"]
    for 命令 in 命令表:
        行们 += ["", 命令.帮助条目()]
    行们 += [
        "",
        "说明",
        "· 数据来自 PRTS Wiki；每天第一次出图时会自动更新数据，之后直接出图。",
        "· 初次安装会自动做一次全量回溯（补录剿灭轮换、复刻排期）；数据看着缺内容时"
        "可用「/甘特图初始化」再全量重建一次。",
        "· 图上时间窗、底栏面板、背景图、每日推送等可在 AstrBot 插件配置里调整。",
        "· 每日推送会发到「用过 /甘特图 的会话」：先在目标群里发一次指令，再去配置里打开推送。",
    ]
    return "\n".join(行们)
