"""旧字段兼容门禁：第二步允许条目改用新阶段，板块既有字段不变。"""
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parent / 'fixtures' / '局部识别'


def legacy_snapshot(module, blocks, parent):
    return [
        (b.标题, b.窗口, b.关卡各段, b.类型, b.是主体, b.干员们,
         [(s.标签, s.角色, s.原文, s.窗口) for s in b.时间段们],
         b.解析问题, b.窗口来源)
        for b in blocks
    ]


@pytest.mark.parametrize('name,year', [
    ('感谢庆典2026', 2026), ('感谢庆典2025', 2025), ('生路', 2024),
    ('生路2025', 2025), ('孤星', 2023), ('孤星2024', 2024),
])
def test_局部识别不影响旧字段和条目(内核模块, monkeypatch, name, year):
    module = 内核模块('解析_公告')
    text = (ROOT / f'{name}.wikitext').read_text(encoding='utf-8')
    reference = datetime(year, 6, 1)
    actual = module.抽板块(text, reference)
    assert actual
    assert all(b.局部识别 is not None for b in actual)
    with monkeypatch.context() as patch:
        patch.setattr(module, '识别局部记录', lambda *args, **kwargs: None)
        old = module.抽板块(text, reference)
    assert legacy_snapshot(module, actual, name) == legacy_snapshot(module, old, name)
    assert actual == old  # 对照字段不参与兼容板块的相等比较。


def test_没有旧时间段的板块仍不新增(内核模块):
    module = 内核模块('解析_公告')
    text = '==SideStory「新活动」==\n活动关卡将分段开启：\n◆序章\n挑战时间：11月01日 12:00 - 11月22日 03:59\n开放关卡：【甲】'
    assert module.抽板块(text, datetime(2026, 11, 1)) == []


def test_深层章节保留局部证据不改变旧切块(内核模块):
    module = 内核模块('解析_公告')
    text = '\n==SideStory「样本」==\n活动时间：11月01日 12:00 - 11月29日 03:59\n===子说明===\n【商店甲】\n开放时间：11月01日 12:00 - 11月29日 03:59\n兑换说明：消耗代币兑换\n==另一活动==\n活动时间：12月01日 12:00 - 12月10日 03:59'
    blocks = module.抽板块(text, datetime(2026, 11, 1))
    result = blocks[0].局部识别
    assert any(r.对象 == ('商店甲',) for r in result.局部记录)
    assert not any('12月01日' in e.文本 for r in result.局部记录 for e in r.证据)
    for r in result.局部记录:
        for e in r.证据:
            assert text.splitlines()[e.行 - 1] == e.文本


def test_手工旧板块构造无需新字段(内核模块):
    module = 内核模块('解析_公告')
    b = module.板块('标题', ('2026-11-01 12:00:00', '2026-11-22 03:59:00'), [], 1, False)
    assert b.局部识别 is None
