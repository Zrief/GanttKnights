"""来源板块局部隔离机制测试；构造变体、零网络。"""
from datetime import datetime

import pytest


def parse(内核模块, text):
    return 内核模块('解析_公告').抽板块(text, datetime(2026, 11, 1))


def generate(内核模块, text, members=()):
    return 内核模块('解析_API活动').认领与生成(list(members), {'公告/活动公告': parse(内核模块, text)})


GOOD = '==「正常活动」活动开启==\n活动时间：11月01日 12:00 - 11月22日 03:59\n'


def test_重复标题整块隔离正常标题仍生成(内核模块):
    duplicate = '==「重复活动」活动开启==\n活动时间：11月01日 12:00 - 11月22日 03:59\n'
    batch = generate(内核模块, duplicate + GOOD + duplicate)
    assert [a['名称'] for a in batch] == ['正常活动']
    assert batch.隔离来源 == (('公告/活动公告', '「重复活动」活动开启'),)
    assert batch.更新问题 and not batch.身份问题
    assert batch.保留来源父名 == ('公告',)


def test_空时间未认领块隔离且其他活动正常(内核模块):
    batch = generate(内核模块, GOOD + '==「不完整活动」活动开启==\n活动开启时间：11月01日 12:00\n')
    assert [a['名称'] for a in batch] == ['正常活动']
    assert batch.隔离来源 == (('公告/活动公告', '「不完整活动」活动开启'),)
    assert not batch.身份问题


def test_阶段身份待确认整块隔离不留可生成总窗(内核模块):
    # 角色有明确时间但没有稳定对象，不允许仅保留同块总窗来遮掩阶段身份问题。
    bad = ('==SideStory「阶段活动」活动关卡开启==\n'
           '活动时间：11月01日 12:00 - 11月22日 03:59\n'
           '◆主线关卡：11月01日 12:00 - 11月15日 03:59\n')
    batch = generate(内核模块, bad + GOOD)
    assert [a['名称'] for a in batch] == ['正常活动']
    assert batch.隔离来源 == (('公告/活动公告', 'SideStory「阶段活动」活动关卡开启'),)
    assert any('身份待确认' in d for d in batch.更新问题)


def test_批次合并保留四类元数据并去重(内核模块):
    cls = 内核模块('公告身份').公告条目批次
    left = cls([{'名称': '甲'}], ('global',), 隔离来源=(('页', '块'),), 更新问题=('partial',), 保留来源父名=('父',))
    right = cls([{'名称': '乙'}], ('global',), 隔离来源=(('页', '块'), ('页', '另块')), 更新问题=('other',), 保留来源父名=('父',))
    left.合并批次(right)
    assert len(left) == 2
    assert left.身份问题 == ('global',)
    assert left.隔离来源 == (('页', '块'), ('页', '另块'))
    assert left.更新问题 == ('partial', 'other')
    assert left.保留来源父名 == ('父',)


def test_API跨组隔离来源不会由另一组回灌(内核模块, monkeypatch):
    api = 内核模块('解析_API活动')
    cls = 内核模块('公告身份').公告条目批次
    monkeypatch.setattr(api, '获取页面wikitext', lambda page: None)
    count = iter([cls([{'名称': '正常', '类型': 1, '_来源板块': ('页', '块')}]),
                  cls([], 隔离来源=(('页', '块'),), 更新问题=('时间缺失',), 保留来源父名=('父',))])
    monkeypatch.setattr(api, '认领与生成', lambda *args: next(count))
    raw = {'printouts': {'活动开始时间': [{'raw': '1/2026/11/1/4/0/0/0'}],
                        '活动结束时间': [{'raw': '1/2026/11/21/19/59/0/0'}]}}
    batch = api.API转活动列表([('甲', raw), ('乙', raw)], '2026-10-30 17:00:00')
    assert batch == []
    assert batch.隔离来源 == (('页', '块'),)
    assert batch.更新问题 == ('时间缺失',)
    assert batch.保留来源父名 == ('父',)
