"""甘特行规则：铺满全图的常驻条并成一行，快结束的单独起行。

2026-09-24：长期活动不再各占一行（那几条条长得一模一样），这条规则是"哪几条并、哪条单起"
的唯一定义，用不上 matplotlib。
"""

from __future__ import annotations

from datetime import datetime

from src.活动 import 活动
from src.甘特行 import 分行, 铺满全图

左 = datetime(2026, 9, 24)
右 = datetime(2026, 10, 12)


def 常驻(名: str, 止: datetime = datetime(2027, 5, 15)) -> 活动:
    return 活动(名, datetime(2026, 5, 15), 止, 99)


def test_铺满全图() -> None:
    assert 铺满全图(常驻("甲"), 左, 右)
    # 结束时刻在窗口**之外**（看不见右端）→ 照样算常驻，仍然并
    assert 铺满全图(常驻("甲", datetime(2026, 10, 26)), 左, 右)
    # 右端落进窗口 → 图上看得见它要结束了 → 不再并
    assert not 铺满全图(常驻("甲", datetime(2026, 10, 5)), 左, 右)


def test_相邻的常驻条并成一行() -> None:
    行们 = 分行([常驻("甲"), 常驻("乙"), 常驻("丙")], 左, 右)
    assert [len(行) for 行 in 行们] == [3]
    assert [e.名称 for e in 行们[0]] == ["甲", "乙", "丙"]


def test_快结束的单独起一行() -> None:
    行们 = 分行([常驻("甲"), 常驻("快结束", datetime(2026, 10, 5)), 常驻("丙")], 左, 右)
    assert [len(行) for 行 in 行们] == [1, 1, 1]
    assert [行[0].名称 for 行 in 行们] == ["甲", "快结束", "丙"]


def test_普通条各自一行() -> None:
    行们 = 分行([
        活动("活动甲", datetime(2026, 9, 25), datetime(2026, 10, 5), 1),
        活动("活动乙", datetime(2026, 9, 26), datetime(2026, 10, 6), 1),
    ], 左, 右)
    assert [len(行) for 行 in 行们] == [1, 1]


def test_混合顺序保持() -> None:
    """铺满的两条并一行、快结束的另起一行、普通条各自一行 —— 自上而下的次序不变。"""
    行们 = 分行([
        常驻("甲"), 常驻("乙"), 常驻("丙", datetime(2026, 10, 4)),
        活动("活动甲", datetime(2026, 9, 25), datetime(2026, 10, 5), 1),
    ], 左, 右)
    assert [len(行) for 行 in 行们] == [2, 1, 1]
    assert [行[0].名称 for 行 in 行们] == ["甲", "丙", "活动甲"]
