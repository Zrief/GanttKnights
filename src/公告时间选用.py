"""公告时间纯选择层；适用=True即接管，空选项也禁止回退旧窗口/包络。

主体身份由调用者提供，流程由正文声明。不处理名称、类型、条目或CSV。
"""
from __future__ import annotations

from dataclasses import dataclass
from .公告局部识别 import 原文证据, 局部记录, 局部识别结果


@dataclass(frozen=True)
class 时间选项:
    后缀: str
    窗口: tuple[str, str]
    依据: str
    证据: tuple[原文证据, ...]
    角色: str = ""
    对象: tuple[str, ...] = ()
    原标签: str = ""


@dataclass(frozen=True)
class 时间选用结果:
    选项: tuple[时间选项, ...]
    适用: bool
    原因: tuple[str, ...]


_阶段阻断诊断 = frozenset({
    '缺时间', '未处理日期', '未知分组标题', '未知关卡段内容',
    '时间角色冲突', '时间角色未确定', '未确认阶段时间依据',
    '未知时间标签', '未关联时间候选', '未关联关卡内容',
    '阶段声明未识别', '未声明阶段', '阶段组边界未确定',
    '阶段声明未对应', '多组流程窗口口径未确定',
})
_窗口冲突诊断 = frozenset({'明示窗口冲突', '阶段超出明示窗口'})


def _中文数词(数: int) -> str:
    """正整数阶段序号，支持十以上（百、千、万）。"""
    字 = '零一二三四五六七八九'
    if 数 < 1:
        raise ValueError('阶段序号必须是正整数')
    if 数 < 10:
        return 字[数]
    for 位, 单位 in ((10000, '万'), (1000, '千'), (100, '百'), (10, '十')):
        if 数 >= 位:
            商, 余 = divmod(数, 位)
            前 = ('' if 位 == 10 and 商 == 1 else _中文数词(商)) + 单位
            if not 余:
                return 前
            后 = '一' + _中文数词(余) if 10 <= 余 < 20 else _中文数词(余)
            return 前 + ('零' if 余 < 位 // 10 else '') + 后
    raise ValueError('无效阶段序号')


def _精确已确认(记录: 局部记录) -> bool:
    return (记录.窗口 is not None and 记录.时间精度 == '精确'
            and 记录.角色状态 == '已确认')


def _诊断原因(诊断: dict) -> str:
    类型 = str(诊断.get('类型', '未知诊断'))
    行 = 诊断.get('行')
    位置 = f'（行{行}）' if 行 is not None else ''
    说明 = 诊断.get('说明', '')
    return f'{类型}{位置}' + (f'：{说明}' if 说明 else '')


def _唯一原因(原因: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(原因))


def _阶段问题(识别: 局部识别结果) -> list[str]:
    问题 = []
    for 诊断 in 识别.诊断:
        类型 = 诊断.get('类型')
        if 类型 in _阶段阻断诊断:
            问题.append(_诊断原因(诊断))
        elif 类型 == '时间未确定':
            # 明确独立的兑换/子对象不生成，其模糊时间不破坏阶段完整性。
            关联 = [r for r in 识别.局部记录
                  if any(e.行 == 诊断.get('行') for e in r.证据)]
            if not 关联 or any(r.角色 not in {'兑换开放', '子对象开放'}
                                 or r.角色状态 != '已确认' for r in 关联):
                问题.append(_诊断原因(诊断))
    return 问题


def _明示总窗(记录们: tuple[局部记录, ...]) -> tuple[时间选项 | None, list[str]]:
    总们 = [r for r in 记录们 if r.角色 == '公告明示活动窗口']
    if not 总们:
        return None, ['未识别到公告明示活动总窗；不以关卡包络或兑换窗口代替']
    if not all(_精确已确认(r) for r in 总们):
        return None, ['公告明示活动总窗有模糊时间或角色待确认，不选精确重复行代替']
    if len({r.窗口 for r in 总们}) != 1:
        return None, ['公告明示活动总窗不唯一，不选择其中一个']
    # 同口径同窗口重复声明合并，保留每份原文证据。
    return 时间选项('', 总们[0].窗口, '公告明示活动窗口（非关卡包络）',
                tuple(e for r in 总们 for e in r.证据), '公告明示活动窗口'), []


def 选用公告时间(识别: 局部识别结果, 是主体: bool) -> 时间选用结果:
    """按原文记录顺序选用，不排序日期、不推断年份、不修改输入。

    非主体且无流程声明返回适用False。失败的正文流程声明也属新路径，
    不退旧总览。窗口冲突整体不选；主体阶段不完整可只保留独立精确
    明示总窗；流程不完整则连总窗也不选。关卡覆盖范围永不使用。
    """
    if not isinstance(识别, 局部识别结果):
        raise TypeError('识别必须为局部识别结果')
    if not isinstance(是主体, bool):
        raise TypeError('是主体必须为 bool')
    声明失败 = any(d.get('类型') == '阶段声明未识别' for d in 识别.诊断)
    有流程 = bool(识别.阶段分组) or 声明失败
    if not 是主体 and not 有流程:
        return 时间选用结果((), False, ('非主体且无正文流程阶段声明，暂沿旧普通路径',))

    冲突 = [_诊断原因(d) for d in 识别.诊断 if d.get('类型') in _窗口冲突诊断]
    检查 = 识别.窗口一致性
    if 检查.get('状态') == '存在冲突' or any(
            c.get('状态') in {'冲突', '超出'} for c in 检查.get('检查项', ())):
        冲突.append('窗口一致性检查存在冲突，整体不选且禁止退旧路径')
    # 也防止手工构造的结果未检查重复明示窗口。
    for 角色 in ('公告明示活动窗口', '明示关卡窗口'):
        窗们 = {r.窗口 for r in 识别.局部记录 if r.角色 == 角色 and _精确已确认(r)}
        if len(窗们) > 1:
            冲突.append(f'{角色}存在不同精确窗口，整体不选')
    if 冲突:
        return 时间选用结果((), True, _唯一原因(冲突))

    问题 = _阶段问题(识别)
    if 有流程:
        if len(识别.阶段分组) != 1:
            问题.append('流程阶段声明缺失或多组作用域未知，整体不选')
        else:
            组 = 识别.阶段分组[0]
            标签们 = tuple(组.get('声明标签', ()))
            段们 = tuple(r for r in 识别.局部记录 if r.角色 == '流程阶段')
            实际 = tuple(r.标签 for r in 段们)
            if 组.get('类型') != '流程阶段':
                问题.append('未知阶段分组类型，不猜阶段作用域')
            if (not 标签们 or any(not isinstance(s, str) or not s for s in 标签们)
                    or len(set(标签们)) != len(标签们)):
                问题.append('流程声明标签缺失、重复或无效')
            if (组.get('状态') != '本份声明已对应' or 组.get('缺失标签')
                    or 组.get('重复标签') or len(实际) != len(标签们)
                    or set(实际) != set(标签们) or len(set(实际)) != len(实际)):
                问题.append('流程声明与阶段记录未完整一一对应')
            if not all(_精确已确认(r) for r in 段们):
                问题.append('流程阶段有模糊时间或角色待确认')
            if any(r.角色 == '关卡开放' for r in 识别.局部记录):
                问题.append('流程与关卡阶段同时出现，作用域未确认')
            if any(r.角色 == '角色未确定' or r.角色状态 != '已确认'
                   for r in 识别.局部记录):
                问题.append('存在角色待确认记录，流程阶段完整性未确认')
        if 问题:
            return 时间选用结果((), True, _唯一原因(
                问题 + ['流程阶段不完整，整体不选且不回退总览']))
        映射 = {'预选期': '预选', '招募期': '招募'}
        return 时间选用结果(tuple(
            时间选项('·' + 映射.get(r.标签, r.标签), r.窗口,
                 '正文声明的完整流程阶段：' + r.标签, r.证据, r.角色, r.对象, r.标签)
            for r in 段们), True, ('流程声明已完整对应；按原文记录顺序选用，不生成总览',))

    总窗, 总窗原因 = _明示总窗(识别.局部记录)
    段们 = tuple(r for r in 识别.局部记录 if r.角色 == '关卡开放')
    if not all(_精确已确认(r) for r in 段们):
        问题.append('关卡阶段有模糊时间或角色待确认，不能只选后续精确阶段')
    if any(r.角色 == '角色未确定' or r.角色状态 != '已确认'
           for r in 识别.局部记录):
        问题.append('存在时间角色未确认记录，关卡阶段完整性未确认')
    if 问题:
        选项 = (总窗,) if 总窗 is not None else ()
        return 时间选用结果(选项, True, _唯一原因(
            问题 + 总窗原因 + ['关卡阶段不完整，所有阶段均不选；'
                           + ('仅保留独立精确明示总窗，不把它当关卡' if 总窗 else '无精确独立总窗可保留')]))

    选项 = ([总窗] if 总窗 is not None else []) + [
        时间选项('·' + _中文数词(i) + '阶段', r.窗口,
             '关卡开放记录（按原文记录顺序）：' + r.标签, r.证据, r.角色, r.对象, r.标签)
        for i, r in enumerate(段们, 1)
    ]
    原因 = 总窗原因 + (['每条关卡开放记录为一阶段；多个区域共用一条记录不拆分']
                     if 段们 else ['本份文本无关卡阶段记录；只选确凿的明示活动总窗'])
    return 时间选用结果(tuple(选项), True, _唯一原因(原因))


__all__ = ['时间选项', '时间选用结果', '选用公告时间']
