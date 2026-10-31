"""扫描窗口：初始化半年、日常 7 天（2026-10-31 定，按负载重新分配）。

- 日常只扫「进行中 + 最近 7 天内结束」的活动：与 CSV 过期保留期（7 天）一致，
  不再出现“扫 30 天、只留 7 天”的浪费；
- 初始化扫最近半年：够覆盖当季活动挂在较早公告页上的原文，又不再无差别扫全站历史。
"""
from __future__ import annotations

from datetime import datetime, timedelta

现在 = '2026-10-31 12:00:00'


def 若干天前(天: float) -> str:
    return (datetime.strptime(现在, '%Y-%m-%d %H:%M:%S') - timedelta(days=天)
            ).strftime('%Y-%m-%d %H:%M:%S')


def 若干天后(天: float) -> str:
    return (datetime.strptime(现在, '%Y-%m-%d %H:%M:%S') + timedelta(days=天)
            ).strftime('%Y-%m-%d %H:%M:%S')


def test_日常窗口是7天(内核模块):
    api = 内核模块('解析_API活动')
    assert api.日常窗口天 == 7
    assert api.扫描窗口天(回溯已结束=False) == 7
    assert api.在扫描窗口内(若干天前(6), 现在, False)
    assert not api.在扫描窗口内(若干天前(8), 现在, False)
    assert api.在扫描窗口内(若干天后(20), 现在, False)   # 未来结束（进行中）永远在窗口


def test_初始化窗口是半年(内核模块):
    api = 内核模块('解析_API活动')
    assert api.初始化窗口天 == 180
    assert api.扫描窗口天(回溯已结束=True) == 180
    assert api.在扫描窗口内(若干天前(100), 现在, True)
    assert not api.在扫描窗口内(若干天前(200), 现在, True)


def test_窗口线与CSV过期线一致(内核模块):
    """日常窗口（7 天）不能比 CSV 过期保留期更短，否则“刚过期就再也扫不到”。"""
    store = 内核模块('身份CSV存储')
    api = 内核模块('解析_API活动')
    assert api.日常窗口天 >= store.过期保留天数
