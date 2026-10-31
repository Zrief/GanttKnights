"""运行时来源身份：不是永久ID，不修改CSV格式，也不从日期/显示名猜身份。"""
from __future__ import annotations
import json


def 局部身份依据(角色: str, 对象: tuple[str, ...], 原标签: str) -> tuple[str, ...] | None:
    if 角色 == '公告明示活动窗口':
        return (角色,)
    if 对象:
        return (角色, '对象', *sorted(set(对象)))
    if 角色 == '流程阶段' and 原标签:
        return (角色, '标签', 原标签)
    # 编号/序章等易随增删重排改变，没有对象不可声称稳定。
    return None


def 附加来源身份(条目: dict, 公告页: str, 板块标题: str) -> dict:
    """返副本；作用域沿真实来源，不因认领到成员/改显示名而变化。"""
    result = dict(条目)
    result['_来源板块'] = (公告页, 板块标题)
    basis = result.get('_局部身份依据')
    if basis:
        result['_运行时身份'] = json.dumps(
            ['公告局部-v1', 公告页, 板块标题, *basis], ensure_ascii=False, separators=(',', ':'))
        result['_身份状态'] = '来源内可对应'
    elif '_局部身份依据' in result:
        result['_身份状态'] = '阶段身份待确认'
    else:
        result['_运行时身份'] = json.dumps(
            ['公告板块-v1', 公告页, 板块标题], ensure_ascii=False, separators=(',', ':'))
        result['_身份状态'] = '来源板块依据'
    return result


class 公告条目批次(list):
    """兼容list；身份问题为全局错误，局部异常通过隔离来源及更新问题携带。"""
    def __init__(self, iterable=(), 身份问题=(), *, 隔离来源=(), 更新问题=(), 保留来源父名=()):
        super().__init__(iterable)
        self.身份问题 = tuple(身份问题)
        self.隔离来源 = tuple(dict.fromkeys(隔离来源))
        self.更新问题 = tuple(dict.fromkeys(更新问题))
        self.保留来源父名 = tuple(dict.fromkeys(保留来源父名))
        self.保留兼容键 = ()
        self.保留运行时身份 = ()

    def 合并批次(self, 批次):
        """追加条目与批次元数据；普通list也可接收。"""
        self.extend(批次)
        for 字段 in ('身份问题', '隔离来源', '更新问题', '保留来源父名', '保留兼容键', '保留运行时身份'):
            setattr(self, 字段, tuple(dict.fromkeys((*getattr(self, 字段), *getattr(批次, 字段, ())))))


__all__ = ['局部身份依据', '附加来源身份', '公告条目批次']
