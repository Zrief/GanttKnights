"""SideStory活动本名与父来源、身份分开。"""
from datetime import datetime
import pytest


@pytest.mark.parametrize('title,expected', [
    ('2026「感谢庆典」，SideStory「时间啊，向前！」活动限时开启', 'SideStory「时间啊，向前！」'),
    ('全新SideStory「生路」，活动关卡开启', 'SideStory「生路」'),
    ('SideStory【含「内引号」的名字】限时复刻开启', 'SideStory「含「内引号」的名字」'),
    ('SideStory“别的引号”限时开启', 'SideStory「别的引号」'),
    ('2026「系列」，故事集「另一个活动」开启', None),
    ('SideStory活动关卡开启', None),
])
def test_明确标识后取本名不误用系列(title, expected, 内核模块):
    assert 内核模块('解析_公告').SideStory本名(title) == expected


def test_未认领与正确成员显示名一致且父来源不变(内核模块):
    api = 内核模块('解析_API活动')
    text = ('==2026「感谢庆典」，SideStory「时间啊，向前！」活动限时开启==\n'
            '活动关卡开放时间：\n◆【残照终尽】开启时间：11月01日 12:00 - 11月22日 03:59')
    b, = api.抽板块(text, datetime(2026, 11, 1))
    page = '感谢庆典2026/活动公告'
    unclaimed = api.认领与生成([], {page: [b]})
    member = dict(事件名='时间啊，向前！', 显示名='SideStory「时间啊，向前！」', 公告页=page,
                  锚点=None, 类型=1, 已结束=False, 开始='', 结束='')
    claimed = api.认领与生成([member], {page: [b]})
    assert unclaimed == claimed
    assert unclaimed[0]['名称'] == 'SideStory「时间啊，向前！」·一阶段'
    assert unclaimed[0]['_parent'] == '感谢庆典2026'


def test_已确认成员显示名仍优先(内核模块):
    notice = 内核模块('解析_公告')
    text = '==SideStory「活动」==\n活动时间：11月01日 12:00 - 11月22日 03:59'
    b, = notice.抽板块(text, datetime(2026, 11, 1))
    assert notice.局部时间条目(b, '系列', '用户显示名')[0]['名称'] == '用户显示名'
