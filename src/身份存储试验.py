"""隔离身份存储试验：纯函数、不读写文件、不导入生产汇总。

持久对应键仅来自 _运行时身份，不是永久事件ID；六列 SHA256 只定位待确认旧行。
候选分级：同类型且 parent 不冲突的同名，或同 parent 同类型且有效窗口
相等/包含，逐个阻止隐式更新/新增；仅同 parent 同类型为低置信提示，
不阻止独立活动。改名且时间完全移出旧窗只有低置信提示，需要人工审核。
总览拆阶段时绑定一个阶段不会批准其他阶段。无来源类型0/99的旧行不迁移。
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json

旧列 = ('名称', '开始时间', '结束时间', '类型', '子类型', '来源')
快照列 = (*旧列, '身份', '身份状态')

# 异常类归正式模块（`身份存储错误`），这里反向复用，避免生产链路依赖试验代码。
from .身份存储错误 import 身份存储冲突  # noqa: E402


def _文本(value: object) -> str:
    if value is None:
        return ''
    if not isinstance(value, (str, int, float, bool, datetime)):
        raise 身份存储冲突('六列值必须是标量文本或日期')
    return str(value)


def 旧行标识(行: dict) -> str:
    """固定列序 canonical JSON UTF-8 SHA256，无身份/序号；int与CSV文本同值。"""
    payload = json.dumps([_文本(行.get(k, '')) for k in 旧列],
                         ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return sha256(payload.encode('utf-8')).hexdigest()


def _身份(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise 身份存储冲突(f'{label}必须是非空字符串')
    return value


def _检查新行(行们: list[dict]) -> dict[str, dict]:
    if getattr(行们, '身份问题', ()):
        raise 身份存储冲突('新输入批次身份问题')
    result = {}
    for 行 in 行们:
        if any('待确认' in _文本(行.get(k, '')) for k in ('_身份状态', '身份状态')):
            raise 身份存储冲突('新输入身份待确认')
        if 行.get('_身份问题'):
            raise 身份存储冲突('新输入行身份问题')
        key = _身份(行.get('_运行时身份'), '新输入_运行时身份')
        if 行.get('身份') and 行['身份'] != key:
            raise 身份存储冲突('新输入身份与运行时身份矛盾')
        if key in result:
            raise 身份存储冲突('新identity碰撞：运行时身份重复')
        旧行标识(行)
        result[key] = 行
    return result


def _parent(行: dict) -> str:
    explicit = {_文本(行.get(k)).strip() for k in ('_parent', '来源_parent') if 行.get(k)}
    if len(explicit) > 1:
        raise 身份存储冲突('来源parent字段互相矛盾')
    return next(iter(explicit), '') or _文本(行.get('来源', ''))


def _保留不迁移(行: dict) -> bool:
    return not _parent(行) and _文本(行.get('类型')) in ('0', '99')


def _窗口(行: dict) -> tuple[datetime, datetime] | None:
    try:
        a = datetime.fromisoformat(_文本(行.get('开始时间')))
        b = datetime.fromisoformat(_文本(行.get('结束时间')))
        if a <= b:
            return a, b
    except (ValueError, TypeError):
        pass
    return None


def _包含(旧: dict, 新: dict) -> bool:
    a, b = _窗口(旧), _窗口(新)
    if a is None or b is None:
        return False
    try:
        return (a[0] <= b[0] <= b[1] <= a[1] or
                b[0] <= a[0] <= a[1] <= b[1])
    except TypeError:
        return False


def _候选原因(旧: dict, 新: dict) -> tuple[tuple[str, ...], bool]:
    if _文本(旧.get('类型')) != _文本(新.get('类型')):
        return (), False
    a, b = _parent(旧), _parent(新)
    if a and b and a != b:
        return (), False
    reasons = []
    same_parent = bool(a and a == b)
    same_name = bool(旧.get('名称') and 旧.get('名称') == 新.get('名称'))
    if same_name:
        reasons.append('同名同类型（仅候选）')
    if same_parent:
        reasons.append('同来源_parent同类型（低置信）')
    contained = same_parent and _包含(旧, 新)
    if contained:
        reasons.append('同来源_parent且时间窗相等或包含（仅候选）')
    return tuple(reasons), same_name or contained


def 预检旧行映射(旧行: list[dict], 新行: list[dict]) -> tuple[dict, ...]:
    """每旧行一报告；候选原因tuple按候选身份tuple对齐，绝不自动确认。

    已有身份只明确同key；只有阻止身份需显式裁决。重复payload同标识，
    不补序号。新批次问题/身份碰撞直接拒绝，不输出可确认候选集。
    """
    new = _检查新行(新行)
    ids = [旧行标识(row) for row in 旧行]
    counts = Counter(ids)
    reports = []
    for row, row_id in zip(旧行, ids):
        candidates, reasons, blockers = [], [], []
        identity = row.get('身份')
        if identity:
            key = _身份(identity, '旧身份')
            status = '明确同key' if key in new else '已有身份未出现'
            if key in new:
                candidates.append(key)
                reasons.append(('旧有身份值明确同key',))
        elif _保留不迁移(row):
            status = 'legacy保留不迁移'
        else:
            for key in sorted(new):
                why, blocks = _候选原因(row, new[key])
                if why:
                    candidates.append(key)
                    reasons.append(why)
                if blocks:
                    blockers.append(key)
            status = '待确认' if blockers else ('低置信候选' if candidates else '无候选')
        if counts[row_id] > 1:
            status = '重复旧行标识'
        reports.append(dict(行标识=row_id, 状态=status, 候选身份=tuple(candidates),
                            候选原因=tuple(reasons), 阻止身份=tuple(blockers)))
    return tuple(reports)


def _记录(row: dict, identity: str = '') -> dict:
    result = {k: row.get(k, '') for k in 旧列}
    result['来源'] = _parent(row)
    result.update(身份=identity, 身份状态='已确认' if identity else '未确认')
    return result


def 生成持久快照(旧行: list[dict], 新行: list[dict], 确认映射: dict[str, str],
              作为新增: tuple[str, ...] = (),
              排除关联: tuple[tuple[str, str], ...] = ()) -> list[dict]:
    """按身份增量更新，未出现/过期行全部保留；只返回六列+身份+身份状态。

    mapping可人工确认候选外改名/移窗，不能改绑已身份行或迁移无来源0/99。
    作为新增使用新身份，批准后保留相关legacy。两种裁决不能同一目标。
    排除关联显式否决旧行-新身份候选边，不删除旧行，不改绑身份。
    legacy独立保留不进identity dict，不按名称折叠。
    """
    new = _检查新行(新行)
    reports = 预检旧行映射(旧行, 新行)
    ids = [r['行标识'] for r in reports]
    if len(ids) != len(set(ids)):
        raise 身份存储冲突('重复旧行标识，不能使用序号消歧')
    old_by_id = dict(zip(ids, 旧行))
    identities = [r['身份'] for r in 旧行 if r.get('身份')]
    for key in identities:
        _身份(key, '旧身份')
    if len(identities) != len(set(identities)):
        raise 身份存储冲突('旧identity碰撞：多旧行同身份')
    targets = []
    for row_id, key in 确认映射.items():
        if row_id not in old_by_id:
            raise 身份存储冲突('未知旧行标识')
        _身份(key, '映射身份')
        if key not in new:
            raise 身份存储冲突('映射目标不在新输入')
        old = old_by_id[row_id]
        if _保留不迁移(old) and not old.get('身份'):
            raise 身份存储冲突('无来源卡池/长期legacy本步不迁移')
        if old.get('身份') and old['身份'] != key:
            raise 身份存储冲突('已有身份不可重新绑定其他key')
        if key in identities and old.get('身份') != key:
            raise 身份存储冲突('映射目标已属于另一旧身份行')
        targets.append(key)
    if len(targets) != len(set(targets)):
        raise 身份存储冲突('多旧行同身份：确认映射不是一对一')
    for key in 作为新增:
        _身份(key, '作为新增身份')
        if key not in new:
            raise 身份存储冲突('作为新增目标不在新输入')
        if key in identities or key in targets:
            raise 身份存储冲突('作为新增与已有身份/确认映射矛盾')
    if len(作为新增) != len(set(作为新增)):
        raise 身份存储冲突('作为新增身份重复')
    excluded = set()
    candidate_edges = {(r['行标识'], key) for r in reports for key in r['候选身份']}
    for edge in 排除关联:
        if (not isinstance(edge, tuple) or len(edge) != 2
                or not all(isinstance(x, str) for x in edge) or edge not in candidate_edges):
            raise 身份存储冲突('排除关联必须是已列出的旧行-新身份候选')
        if edge in excluded or 确认映射.get(edge[0]) == edge[1]:
            raise 身份存储冲突('排除关联重复或与确认映射矛盾')
        excluded.add(edge)
    approved = set(作为新增)
    for report in reports:
        for key in report['阻止身份']:
            if ((report['行标识'], key) not in excluded
                    and 确认映射.get(report['行标识']) != key and key not in approved):
                raise 身份存储冲突(f'候选关联未确认：{report["行标识"]} -> {key}')
    legacy, by_identity = [], {}
    for row_id, old in zip(ids, 旧行):
        key = old.get('身份') or 确认映射.get(row_id, '')
        if key:
            by_identity[key] = _记录(old, key)
        else:
            legacy.append(_记录(old))
    for key, row in new.items():
        by_identity[key] = _记录(row, key)
    return legacy + [by_identity[key] for key in sorted(by_identity)]


__all__ = ['旧列', '快照列', '身份存储冲突', '旧行标识', '预检旧行映射', '生成持久快照']
