"""公告真实写法缩减回归：省略结束日期与交换所角色，不按活动名修补。"""
from datetime import datetime
import pytest


def test_除夕24点规范到次日零点(内核模块):
    parser = 内核模块('解析_公告')
    text = '==辞旧迎新，除夕夜特别登录奖励开启==\n活动时间：02月16日 20:00 - 24:00\n活动说明：玩家可在活动期间不同时段领取来自不同干员的邮件赠礼\n'
    blocks = parser.抽板块(text, datetime(2026, 2, 16))
    assert blocks[0].窗口 == ('2026-02-16 20:00:00', '2026-02-17 00:00:00')
    batch = 内核模块('解析_API活动').认领与生成([], {'辞岁行/活动公告': blocks})
    assert len(batch) == 1 and not batch.隔离来源


@pytest.mark.parametrize('端点', ['24:01', '25:00'])
def test_非法小时不伪造窗口(内核模块, 端点):
    parser = 内核模块('解析_公告')
    block = parser.抽板块('==「活动」活动开启==\n活动时间：02月16日 20:00 - ' + 端点, datetime(2026, 2, 16))[0]
    assert block.窗口 is None


def test_卡池交换所窗口不覆盖卡池总窗(内核模块):
    parser = 内核模块('解析_公告')
    text = ('==「庆典」，【卡池】限定寻访开启==\n'
            '活动时间：08月01日 12:00 - 08月15日 03:59\n'
            '{{color|#c0392b|★★★★★★：干员甲 [限定] \\ 干员乙}}（占6★出率的70%）\n'
            '寻访数据契约交换所开启时间：08月01日 12:00 - 08月18日 03:59\n')
    block = parser.抽板块(text, datetime(2026, 8, 1))[0]
    assert block.窗口 == ('2026-08-01 12:00:00', '2026-08-15 03:59:00')
    assert [s.角色 for s in block.时间段们] == ['总窗口', '兑换期']
    batch = 内核模块('解析_API活动').认领与生成([], {'庆典/活动公告': [block]})
    assert len(batch) == 1 and batch[0]['结束时间'] == '2026-08-15 03:59:00' and not batch.隔离来源
