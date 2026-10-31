"""局部隔离的来源协议匹配；不从显示名称或日期推断关联。"""
from __future__ import annotations

import json

from .公告身份 import 公告条目批次

批次字段 = ('身份问题', '隔离来源', '更新问题', '保留来源父名', '保留兼容键', '保留运行时身份')


def 复制批次元数据(源, 条目们):
    result = 公告条目批次(条目们, getattr(源, '身份问题', ()))
    for field in 批次字段[1:]:
        setattr(result, field, tuple(getattr(源, field, ())))
    return result


def _坐标(value, protocols):
    if not isinstance(value, str) or not value:
        return None
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return None
    if (isinstance(data, list) and len(data) >= 3 and isinstance(data[0], str)
            and data[0] in protocols
            and all(isinstance(x, str) and x for x in data[1:3])):
        return tuple(data[1:3])
    return None


def 来源被隔离(row, 批次):
    isolated = set(getattr(批次, '隔离来源', ()))
    parents = set(getattr(批次, '保留来源父名', ()))
    identity = row.get('_运行时身份', row.get('身份', ''))
    if identity and identity in set(getattr(批次, '保留运行时身份', ())):
        return True
    if not identity and getattr(批次, '保留兼容键', ()):
        from .汇总_活动 import _身份键
        kind = int(row['类型'])
        if (kind, _身份键(row['名称'], kind)) in set(批次.保留兼容键):
            return True
    identity_coord = _坐标(identity, {'公告局部-v1', '公告板块-v1'})
    relation_coord = _坐标(row.get('_活动关联', row.get('活动关联', '')), {'公告活动关联-v1'})
    # 兼容类型的新输出可能只有显式运行时来源坐标。
    explicit = row.get('_来源板块')
    explicit_coord = tuple(explicit) if isinstance(explicit, (tuple, list)) and len(explicit) == 2 else None
    coords = [c for c in (identity_coord, relation_coord, explicit_coord) if c is not None]
    coords.extend(tuple(c) for c in row.get('_来源板块们', ()) if isinstance(c, (tuple, list)) and len(c) == 2)
    if any(c in isolated for c in coords):
        return True
    # 有可解析来源坐标时不扩大到同父公告的正常板块。
    if coords:
        return False
    source = row.get('_parent', row.get('来源', ''))
    return bool(source and source in parents)
