"""2026-10-30 CLI 阻止点：离线复现与局部隔离回归。

完整庆典文本取自既有固定样本；卫戍协议的单行片段取自本次CLI日志，
不是完整新抓取快照。正常兜底不污染更新问题，异常只隔离相关来源。
"""
from datetime import datetime
from pathlib import Path

import pytest


PAGE = '感谢庆典2026/活动公告'
TITLE = '2026「感谢庆典」，SideStory「时间啊，向前！」活动限时开启'
OLD_ANCHOR = '2026「感谢庆典」限时活动 Part.1'


def member(name, **overrides):
    row = dict(事件名=name, 显示名=name, 公告页=PAGE, 锚点=None,
               类型=1, 开始='2099-01-01 00:00:00', 结束='2099-12-31 23:59:00', 已结束=False)
    row.update(overrides)
    return row


def boards(内核模块):
    text = (Path(__file__).parent / 'fixtures' / '局部识别' / '感谢庆典2026.wikitext').read_text(encoding='utf-8')
    return [b for b in 内核模块('解析_公告').抽板块(text, datetime(2026, 10, 30)) if b.标题 == TITLE]


def side():
    return member('时间啊，向前！', 显示名='SideStory「时间啊，向前！」', 锚点=OLD_ANCHOR)


def no_time_board(内核模块):
    # CLI日志中的原文：只有开启时刻，未提供截止，不能伪造可接管窗口。
    text = ('==2026「感谢庆典」，「卫戍协议·规程·序列I」活动开启==\n'
            '活动开启时间：11月08日 16:00（赛季更新时间请参照后续官方公告）\n')
    return 内核模块('解析_公告').抽板块(text, datetime(2026, 10, 30))


def test_旧锚点指向一级章节不在板块候选但唯一标题可认领保存(tmp_path, 内核模块):
    bs, m = boards(内核模块), side()
    assert len(bs) == 1 and bs[0].标题 != OLD_ANCHOR
    result = 内核模块('公告认领').判定公告认领([m], [(PAGE, b) for b in bs])
    assert result.认领 == {0: m} and not result.争议成员
    assert any('零匹配' in d and '唯一标题兜底' in d for d in result.诊断)
    batch = 内核模块('解析_API活动').认领与生成([m], {PAGE: bs})
    assert not batch.身份问题
    assert [r['名称'] for r in batch] == (['SideStory「时间啊，向前！」·' + s + '阶段' for s in '一二三']
                                           + ['SideStory「时间啊，向前！」·商店'])
    assert [r['开始时间'] for r in batch] == ['2026-11-01 12:00:00', '2026-11-08 16:00:00', '2026-11-15 16:00:00', '2026-11-01 12:00:00']
    assert {r['结束时间'] for r in batch[:3]} == {'2026-11-22 03:59:00'}
    assert batch[3]['结束时间'] == '2026-11-29 03:59:00'
    assert batch[3]['_原角色'] == '兑换开放' and batch[3]['_阶段序号'] == 0
    assert '炮火所掩埋的' in batch[3]['_运行时身份']
    内核模块('汇总_活动').合并保存CSV(batch, tmp_path / '活动.csv', '2026-10-30 17:00:00')
    assert (tmp_path / '活动.csv').exists()


def test_长期赛季板块只有开启也能认领并占位结束(内核模块):
    """卫戍协议式公告：只写开启时刻、没有截止 → 长期(99) 允许用 API 窗口占位。"""
    m = member('卫戍协议·规程', 显示名='卫戍协议「规程」', 公告页=None, 类型=99)
    bs = no_time_board(内核模块)
    result = 内核模块('公告认领').判定公告认领([m], [(PAGE, b) for b in bs])
    assert result.认领 == {0: m} and not result.争议成员 and not result.无时间成员
    batch = 内核模块('解析_API活动').认领与生成([m], {PAGE: bs})
    assert len(batch) == 1 and not batch.身份问题
    条 = batch[0]
    assert 条['名称'] == '卫戍协议「规程·序列I」' and 条['类型'] == 99
    assert 条['开始时间'] == '2026-11-08 16:00:00'
    assert 条['结束时间'] == m['结束']              # 占位：API 窗口
    assert 条['时间角色'] == '长期开放'
    assert 条['活动本名'] == '卫戍协议·规程'          # 序列滚动用同一本名


def mixed_batch(内核模块):
    ms = [side(), member('卫戍协议·规程', 公告页=None, 类型=99)]
    return 内核模块('解析_API活动').认领与生成(ms, {PAGE: boards(内核模块) + no_time_board(内核模块)})


def test_混合批次长期赛季与正常阶段都能保存(tmp_path, 内核模块):
    batch = mixed_batch(内核模块)
    assert len(batch) == 5 and not batch.身份问题
    assert [r['_原角色'] for r in batch[:4]] == ['关卡开放'] * 3 + ['兑换开放']
    assert batch[4]['类型'] == 99 and not batch.隔离来源
    内核模块('汇总_活动').合并保存CSV(batch, tmp_path / '活动.csv', '2026-10-30 17:00:00')
    assert (tmp_path / '活动.csv').exists()


def test_成功兜底警告不得污染局部更新问题(内核模块):
    batch = mixed_batch(内核模块)
    assert not batch.身份问题
    assert not any('时间啊，向前！' in d for d in batch.更新问题)
    assert not any('无公告时间接管条件' in d for d in batch.更新问题)


@pytest.mark.parametrize('反序', [False, True])
def test_真实同级竞争整块隔离不影响其他块(内核模块, 反序):
    ms = [side(), side()]
    ms[1]['显示名'] = '未经确认的另一个名称'
    if 反序:
        ms.reverse()
    batch = 内核模块('解析_API活动').认领与生成(ms, {PAGE: boards(内核模块)})
    assert batch == [] and not batch.身份问题
    assert batch.隔离来源 == ((PAGE, TITLE),)
    assert any('认领身份争议' in d for d in batch.更新问题)
