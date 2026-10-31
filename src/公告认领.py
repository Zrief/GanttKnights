"""本次解析内的纯公告认领；不生成条目，不推断持久身份或同窗归属。

候选先完整构造，再按显式锚点、标题两级同时裁决。同级歧义及竞争
保留其候选板块，低级证据不能捡漏；未认领板块仍应由调用者自生成。
调用者须禁止 ``争议成员`` 的 ask（包括长期 99）兜底。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .公告局部识别 import 局部识别结果
from .公告时间选用 import 选用公告时间


class 板块(Protocol):
    """只读取板块的匹配及时间接管字段，避免导入 API/旧解析器。"""

    标题: str
    窗口: tuple[str, str] | None
    局部识别: 局部识别结果 | None
    是主体: bool


@dataclass(frozen=True)
class 认领结果:
    认领: dict[int, dict]
    已领: set[int]
    争议成员: set[int]
    无时间成员: set[int]
    诊断: tuple[str, ...]


def _成员说明(m: dict) -> str:
    return (f"成员「{m.get('显示名') or m.get('事件名') or ''}」"
            f"（事件名「{m.get('事件名') or ''}」，"
            f"公告页「{m.get('公告页') or ''}」，锚点「{m.get('锚点') or ''}」）")


def 判定公告认领(成员们: list[dict], 全板块: list[tuple[str, 板块]]) -> 认领结果:
    """板块索引 → 原成员对象；id 只用于本次对象关联，不是持久身份。

    显式锚点只在指定页精确匹配。多匹配不得降级；零匹配可使用指定
    页内唯一标题候选并诊断。唯一锚点即使时间不可接管也不改认标题。
    匹配候选不按窗口/可生成性过滤，避免把歧义变成伪唯一。
    时间接管条件为旧窗口存在或新时间选用适用=True；后者空选项也
    接管，以免失败阶段被 ask 掩盖。没有候选的成员不属于争议。
    """
    # 同一对象重复出现不是多个身份；不同对象即使 dict 相等也保留。
    成员表 = {id(m): m for m in 成员们}
    诊断: set[str] = set()
    候选表: dict[int, tuple[int, tuple[int, ...]]] = {}
    认领: dict[int, dict] = {}
    已领: set[int] = set()
    争议: set[int] = set()
    无时间: set[int] = set()

    独立成员 = list(成员表.values())
    for j, m in enumerate(独立成员):
        if any(m == n for n in 独立成员[:j]):
            诊断.add(f"{_成员说明(m)}：多个不同对象内容完全相同；身份别名未确认，不按字典相等折叠")

    for mid, m in 成员表.items():
        页 = m.get('公告页')
        锚点 = m.get('锚点')
        显式 = tuple(i for i, (页名, b) in enumerate(全板块)
                   if 锚点 and 页名 == 页 and b.标题 == 锚点)
        名 = m.get('事件名')
        标题 = tuple(i for i, (页名, b) in enumerate(全板块)
                   if 名 and 名 in b.标题 and (not 页 or 页名 == 页))
        if 显式:
            候选表[mid] = (2, 显式)
        else:
            候选表[mid] = (1, 标题)
            if 锚点:
                诊断.add(f"{_成员说明(m)}：显式锚点零匹配；"
                       + ("采用唯一标题兜底" if len(标题) == 1 else "标题不唯一或无匹配，不认领"))

    # 每个板块仅计算一次接管条件；不反向缩小候选集合。
    可接管 = []
    for _, b in 全板块:
        新时间 = (选用公告时间(b.局部识别, b.是主体)
                 if b.局部识别 is not None else None)
        可接管.append(bool(b.窗口 or (新时间 is not None and 新时间.适用)))

    保留块: set[int] = set()
    for 等级, 方式 in ((2, '显式锚点'), (1, '标题')):
        同级 = {mid: 候选 for mid, (级, 候选) in 候选表.items() if 级 == 等级}
        请求: dict[int, set[int]] = {}
        for mid, 候选 in 同级.items():
            for i in 候选:
                请求.setdefault(i, set()).add(mid)
        for mid, 候选 in 同级.items():
            m = 成员表[mid]
            if len(候选) > 1:
                争议.add(mid)
                诊断.add(f"{_成员说明(m)}：{方式}匹配多个板块（{len(候选)}个），不猜测认领")
                continue
            if not 候选:
                continue
            (i,) = 候选
            页名, b = 全板块[i]
            块说明 = f"公告页「{页名}」板块「{b.标题}」"
            if i in 保留块:
                争议.add(mid)
                诊断.add(f"{_成员说明(m)}：{方式}候选{块说明}已由更强证据认领或保留，不认领")
            elif len(请求[i]) > 1:
                争议.update(请求[i])
                诊断.add(f"{块说明}：{方式}同级竞争（{len(请求[i])}个成员），全部不认领")
            elif not 可接管[i]:
                无时间.add(mid)
                诊断.add(f"{_成员说明(m)}：{方式}唯一候选{块说明}无公告时间接管条件，不认领且禁止ask兜底")
            else:
                认领[i] = m
                已领.add(mid)
        # 包含歧义、多成员竞争和不可接管块，低级证据不准捡漏。
        保留块.update(请求)

    return 认领结果(认领, 已领, 争议, 无时间, tuple(sorted(诊断)))


__all__ = ['认领结果', '判定公告认领']
