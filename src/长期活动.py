"""长期活动（常驻玩法）的**唯一定义**。

2026-09-24 定：剿灭作战 / 保全派驻 / 生息演算 / 集成战略这几个名字不同，但同属一个大类
（甘特图左列统一写「长期」），**判定与命名不该散在三个地方**——此前：

- `解析_公告.章节类型规则` 抄了一遍关键词；
- `解析_API活动.API类型映射` 与 `名称类型规则` 各抄了一遍；
- 命名也是两套：公告走 `解析_公告._长期任务名`（从标题里抽【】），
  ask 走 `解析_API活动` 的 `显示名` 分支（按 api 类型前缀）。

现在这些全部指向本文件：改"哪些算长期""官方叫什么"只改这里。

判据有两副面孔，别混：

- `关键词们` —— **子串**匹配（标题/条目名里出现即可），给类型判定与公告命名用；
- `字面量们` —— **精确**匹配（PRTS 的 SMW「活动类型」属性的取值），给 API 映射用。

两者不一致是数据源造成的：SMW 写 `生息演算`，公告标题里写 `生息`。
"""

from __future__ import annotations

from dataclasses import replace
import re

类型值 = 99
"""长期活动统一的类型编号（类型体系见 `src/活动.py`：0 寻访 / 1 活动 / 2 福利 / 99 长期）。"""

官方名 = {
    "剿灭": "剿灭作战",
    "剿灭作战": "剿灭作战",
    "保全": "保全派驻",
    "保全派驻": "保全派驻",
    "生息": "生息演算",
    "生息演算": "生息演算",
    "集成战略": "集成战略",
    "卫戍协议": "卫戍协议",
}
"""关键词/字面量 → 官方名。同一个玩法的几种写法都收进来：子串匹配要短的，精确匹配要长的。

卫戍协议 2026-10 起改为赛季常驻（活动时间整年），归入长期（2026-10-28）。
"""

关键词们 = tuple(官方名)
"""类型判定用：**出现**就能认出玩法（顺序即匹配优先级）。"""

字面量们 = ("剿灭", "保全", "生息演算", "集成战略", "卫戍协议")
"""API 映射用：PRTS 的 SMW「活动类型」实际出现过的**精确**取值。"""


def 识别(文本: str) -> str | None:
    """文本里命中的玩法 → 官方名；认不出返回 None（调用方据此走各自的兜底）。"""
    for 关键词 in 关键词们:
        if 关键词 in 文本:
            return 官方名[关键词]
    return None


def 前缀名(文本: str) -> str | None:
    """长期条目的显示前缀（官方名，**不带括号**），如 `剿灭作战`；认不出返回 None。

    组装形态是 `官方名「对象名」`（2026-10-29 定，与官方 SideStory「XXX」同构），
    「」由组装方包在对象名上；卡池的【寻访】/【中坚池】是另一族群，不在此列。
    """
    名 = 识别(文本)
    return 名 if 名 else None


轮换类别 = ('剿灭作战', '保全派驻', '生息演算', '集成战略')


def _轮换类别(名称: str) -> str | None:
    # 现行 官方名「主题」与历史 【玩法】主题 / 「玩法」主题。
    for alias, canonical in 官方名.items():
        if canonical not in 轮换类别:
            continue
        if (re.fullmatch(re.escape(alias) + r'「[^「」]+」', 名称)
                or any(名称.startswith(left + alias + right) and 名称[len(alias) + 2:]
                       for left, right in (('【', '】'), ('「', '」')))):
            return canonical
    return None


def 排列序列(记录):
    """同一长期开放玩法（同活动本名）的多个序列：旧序列展示右端截到下一序列开始。

    只改展示副本，不动来源 CSV。占位结束（来源里的整年时间）只用于"存在性"，
    这里用下一序列开始覆盖它——对应"老主题在新主题出现那一刻截止"（2026-10-31）。
    """
    组: dict[str, list[int]] = {}
    for i, item in enumerate(记录):
        if item.类型 == 类型值 and item.时间角色 == '长期开放' and item.活动本名:
            组.setdefault(item.活动本名, []).append(i)
    result = list(记录)
    for 位置们 in 组.values():
        if len(位置们) < 2:
            continue
        位置们.sort(key=lambda i: 记录[i].开始)
        for 前, 后 in zip(位置们, 位置们[1:]):
            if 记录[后].开始 < result[前].结束:
                result[前] = replace(result[前], 结束=记录[后].开始)
    return result


def 排列长期(记录):
    """长期活动的展示排列：先按轮换裁剪，再按序列裁剪。"""
    return 排列序列(排列轮换(记录))


def 排列轮换(记录):
    """同类新主题开始时裁剪旧展示窗口；返回副本，不改来源数据。

    同一开始时刻允许多个关卡/主题并列；只看严格更晚的下一批开始。
    来源结束更早则仍用来源结束，不延长；卫戍协议（赛季序列）由 `排列序列` 处理。
    """
    starts = {}
    for item in 记录:
        kind = _轮换类别(item.名称) if item.类型 == 类型值 else None
        if kind:
            starts.setdefault(kind, set()).add(item.开始)
    timelines = {kind: sorted(values) for kind, values in starts.items()}
    result = []
    for item in 记录:
        kind = _轮换类别(item.名称) if item.类型 == 类型值 else None
        next_start = next((start for start in timelines.get(kind, ()) if start > item.开始), None)
        if next_start is not None and next_start < item.结束:
            item = replace(item, 结束=next_start, 时间角色='长期轮换')
        result.append(item)
    return result
