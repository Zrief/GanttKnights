"""独立窗口关系检查：只报告，不改日期、不猜整体范围。

检查项与诊断 dict 是内部对照结果，非数据库存储设计。
不导入局部识别/旧公告解析，以结构化协议接受记录。
"""
from __future__ import annotations
from collections.abc import Iterable
from typing import Protocol


class 证据协议(Protocol):
    行: int
    文本: str


class 窗口记录协议(Protocol):
    标签: str
    角色: str
    窗口: tuple[str, str] | None
    时间精度: str
    角色状态: str
    证据: tuple[证据协议, ...]


def 检查窗口一致性(记录们: Iterable[窗口记录协议]) -> tuple[dict, list[dict]]:
    """返回(一致性内部对照, 诊断)，不修改输入。

    输入窗口须为规范 YYYY-MM-DD HH:MM:SS；活动总窗只约束关卡/流程，
    关卡总窗只约束关卡。未知角色不参与比较并使结果不完整。
    不检查阶段连续、互斥、重叠，不证明正文或阶段完整性。
    """
    records = tuple(记录们)
    checks, issues = [], []
    incomplete = False

    def confirmed(r):
        return r.角色状态 == '已确认'

    def precise(r):
        return bool(r.窗口) and r.时间精度 == '精确'

    def evidence_of(rows):
        return [{'行': e.行, '文本': e.文本} for r in rows for e in r.证据]

    for role in ('公告明示活动窗口', '明示关卡窗口'):
        totals = [r for r in records if r.角色 == role and confirmed(r)]
        if not totals:
            continue
        valid = [r for r in totals if precise(r)]
        uncertain = len(valid) != len(totals)
        distinct = {r.窗口 for r in valid}
        if uncertain:
            incomplete = True
        if len(distinct) > 1:
            evidence = evidence_of(totals)
            first = evidence[0] if evidence else {'行': 0, '文本': ''}
            checks.append({'类型': '明示窗口冲突', '口径': role, '状态': '冲突', '证据': evidence})
            issues.append({'类型': '明示窗口冲突', '行': first['行'], '原文': first['文本'],
                           '说明': f'{role}出现多个不同窗口，不选择其中一个', '证据': evidence})
            continue
        if uncertain or not valid:
            checks.append({'类型': '阶段范围检查', '口径': role, '状态': '无法检查',
                           '说明': '明示窗口有未精确解析项，不以其他重复行代替'})
            continue
        total = valid[0]
        stage_roles = {'关卡开放'} if role == '明示关卡窗口' else {'关卡开放', '流程阶段'}
        stages = [r for r in records if r.角色 in stage_roles and confirmed(r)]
        if not stages:
            incomplete = True
            checks.append({'类型': '阶段范围检查', '口径': role, '状态': '无法检查', '说明': '没有可确认的阶段记录'})
        for stage in stages:
            evidence = evidence_of((total, stage))
            if not precise(stage):
                incomplete = True
                checks.append({'类型': '阶段范围检查', '口径': role, '阶段': stage.标签,
                               '状态': '无法检查', '证据': evidence})
                continue
            a, b = stage.窗口
            start, end = total.窗口
            outside = a < start or b > end
            checks.append({'类型': '阶段范围检查', '口径': role, '阶段': stage.标签,
                           '状态': '超出' if outside else '包含', '证据': evidence})
            if outside:
                last = stage.证据[-1] if stage.证据 else None
                issues.append({'类型': '阶段超出明示窗口', '行': last.行 if last else 0,
                               '原文': last.文本 if last else '',
                               '说明': f'{stage.标签}窗口{stage.窗口}超出{role}{total.窗口}；仅报告，不裁剪',
                               '证据': evidence})
    if any(not confirmed(r) or not precise(r) for r in records):
        incomplete = True
    state = ('存在冲突' if issues else '部分无法检查' if incomplete else
             '已检查关系未见冲突' if checks else '无明示窗口可比较')
    return {'状态': state, '检查项': checks,
            '口径': '仅核对本板块已确认的同口径窗口；不检查阶段互斥/连续、不以商店结束替代活动结束、不证明完整性'}, issues


__all__ = ['检查窗口一致性', '窗口记录协议', '证据协议']
