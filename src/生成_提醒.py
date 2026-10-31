"""生成"节点提醒"文本 — 只在配置的天数节点上说话（供聊天推送 / 控制台输出）。

## 判据：只看今天，不看历史

`偏移 = (今天 - 边界日).days`（负数 = 边界还没到），命中配置里的天数就提醒：

- **结束侧**（`结束偏移们`，默认 `(-3, -1)`）：`-3` = 结束前 3 天、`-1` = 最后一天（即"明天结束"）、
  `0` = 结束当天；
- **开始侧**（`开始偏移们`，默认 `(0,)`）：`0` = 开启当天、`-1` = 开启前一天。

没命中就一个字都不说——不再每天播报"3 天内即将结束"的清单（每天都列同一批，属于噪音），
也不播报首页上新（凭证/时装/模组）与数据日差（那些信息图里本来就有）。2026-09-15 定。

## 为什么不需要台账

命中与否只取决于"今天的日期 + 活动时间窗 + 配置"，是**当天的状态**而不是"和昨天比"：
同一天里渲染多少次都是同一份文案，跨天自然只响一次。停机几天错过的节点**不补报**。

## 排序与限行

组按"离今天由近到远"排（结束组在前、开始组在后：今天结束 → 明天结束 → … → 今天开启），
组内结束按精确结束时刻、名字；开始在旧排序基础上，同一显式关联按阶段序号排。
只将同关联、同结束时刻的多个关卡开放阶段合为一个共同结束节点，再计算总行数；
总行数上限与所有措辞都在 `提醒文案`（改文风只改那个文件）。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .活动 import 活动
from . import 长期活动
from .提醒文案 import (
    条目行, 组头, 省略行, 最多列几行, 提醒名, 共同结束名, 结束说明,
)

结束偏移默认: tuple[int, ...] = (-3, -1)
开始偏移默认: tuple[int, ...] = (0,)

偏移下限, 偏移上限 = -30, 0
"""配置里的偏移会被夹到这个范围：正数没意义——活动结束后已被清理、开始后也不该再报。"""


def _开始节点(命中: list[活动]) -> list[tuple[活动, bool]]:
    """沿旧排序放置组间位置，同一显式关联的阶段槽位再按整数序号排列。"""
    有序 = sorted(命中, key=lambda e: (e.结束, e.名称))
    槽位: dict[str, list[int]] = {}
    for i, e in enumerate(有序):
        if e.活动关联 and e.阶段序号 > 0:
            槽位.setdefault(e.活动关联, []).append(i)
    for 位置们 in 槽位.values():
        阶段们 = sorted((有序[i] for i in 位置们), key=lambda e: e.阶段序号)
        for i, e in zip(位置们, 阶段们):
            有序[i] = e
    return [(e, False) for e in 有序]


def _结束节点(命中: list[活动]) -> list[tuple[活动, bool]]:
    """只合并同一显式来源块、精确结束时刻相同的至少两条关卡开放记录。"""
    有序 = sorted(命中, key=lambda e: (e.结束, e.名称))
    关卡组: dict[tuple[str, datetime], list[活动]] = {}
    for e in 有序:
        if e.时间角色 == "关卡开放" and e.活动关联 and e.活动本名:
            关卡组.setdefault((e.活动关联, e.结束), []).append(e)
    可合并 = {
        键: 阶段们 for 键, 阶段们 in 关卡组.items()
        if (len(阶段们) >= 2 and len({e.活动本名 for e in 阶段们}) == 1
            and all(e.阶段序号 > 0 for e in 阶段们)
            and len({e.阶段序号 for e in 阶段们}) == len(阶段们))
    }
    已合并: set[tuple[str, datetime]] = set()
    节点们: list[tuple[活动, bool]] = []
    for e in 有序:
        键 = (e.活动关联, e.结束)
        if e.时间角色 == "关卡开放" and e.活动本名 and 键 in 可合并:
            if 键 not in 已合并:
                节点们.append((replace(e, 名称=共同结束名(e.活动本名)), True))
                已合并.add(键)
        else:
            节点们.append((e, False))
    return sorted(节点们, key=lambda 项: (项[0].结束, 项[0].名称))


def 生成提醒(
    记录: list[活动],
    现在时间: datetime | None = None,
    结束偏移们: tuple[int, ...] = 结束偏移默认,
    开始偏移们: tuple[int, ...] = 开始偏移默认,
) -> str:
    """今天的节点提醒；没有任何节点命中时返回空字符串。

    参数:
        记录: 过滤后的活动列表（list[活动]）
        现在时间: 判定基准（测试注入用；默认 `datetime.now()`）
        结束偏移们 / 开始偏移们: 命中即提醒的天数偏移（空元组 = 这一类不提醒）
    """
    if not 记录:
        return ""

    今天 = (现在时间 or datetime.now()).date()
    组: list[tuple[int, int, str, list[tuple[活动, bool]]]] = []
    for 侧序, (侧, 偏移们) in enumerate((("结束", 结束偏移们), ("开始", 开始偏移们))):
        for 偏移 in sorted(set(偏移们), reverse=True):
            命中 = [
                e for e in 记录
                # 偏移 = 边界距今的天数：负数表示"还没到"（-3 = 3 天后结束）
                if (今天 - (e.结束 if 侧 == "结束" else e.开始).date()).days == 偏移
                # 长期玩法（剿灭/保全/生息/演算/卫戍）的结束不是"活动关闭"，
                # 只是轮换/占位；结束提醒一律不发，只保留开始提醒（2026-10-31 定）。
                and not (侧 == "结束" and e.类型 == 长期活动.类型值)
            ]
            if 命中:
                节点们 = _结束节点(命中) if 侧 == "结束" else _开始节点(命中)
                组.append((侧序, 偏移, 组头(偏移, 侧), 节点们))

    if not 组:
        return ""
    组.sort(key=lambda 项: (项[0], -项[1]))

    行们: list[str] = []
    已列 = 0
    省略 = 0
    for 侧序, 偏移, 组头文本, 事件们 in 组:
        该组: list[str] = []
        for 事件, 共同结束 in 事件们:
            if 已列 >= 最多列几行:
                省略 += 1
                continue
            名称 = 提醒名(事件.名称, 事件.子类型)
            if 侧序 == 0:
                if 事件.时间角色 == '长期轮换':
                    名称 += '（轮换截止，非玩法关闭）'
                名称 += 结束说明(事件.结束, 偏移, 共同结束=共同结束)
            该组.append(条目行(名称, 事件.类型))
            已列 += 1
        if 该组:
            行们.append(组头文本)
            行们.extend(该组)
    if 省略:
        行们.append(省略行(省略))
    return "\n".join(行们)
