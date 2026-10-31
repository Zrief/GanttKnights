"""用户确认页名范围API来源对应，不假装永久ID。"""
import json


def member(page, name='同图名'):
    return dict(事件名=page, API来源页=page, 显示名=name, 公告页=None, 锚点=None,
                类型=1, 已结束=False, 开始='2026-11-01 12:00:00', 结束='2026-11-22 03:59:00')


def test_两成员同名同组不同页身份分开(内核模块):
    api = 内核模块('解析_API活动')
    rows = api.认领与生成([member('矢量突破/03'), member('矢量突破/04')], {})
    assert len(rows) == 2 and rows[0]['名称'] == rows[1]['名称']
    assert rows[0]['_运行时身份'] != rows[1]['_运行时身份']
    assert json.loads(rows[0]['_运行时身份']) == ['PRTS事件页-v1','prts.wiki','矢量突破/03']


def test_改图名日期仍同页改页名则不同身份(内核模块):
    api = 内核模块('解析_API活动')
    m = member('活动/01')
    a = api.认领与生成([m], {})[0]
    m.update(显示名='新图名', 结束='2026-11-23 03:59:00')
    b = api.认领与生成([m], {})[0]
    assert a['_运行时身份'] == b['_运行时身份']
    m['API来源页'] = '活动/改页名'
    assert api.认领与生成([m], {})[0]['_运行时身份'] != b['_运行时身份']


def test_API原始fulltext优先保留(内核模块, monkeypatch):
    api = 内核模块('解析_API活动')
    monkeypatch.setattr(api, '获取页面wikitext', lambda p: None)
    data = [('显示短名', {'fulltext':'完整事件/01','printouts':{
        '活动开始时间cn':[{'raw':'2026-11-01 12:00:00'}],
        '活动结束时间':[{'raw':'2026-11-22 03:59:00'}], '活动类型':['其他活动']}})]
    # 当前API时间解析期望 raw UNIX/date格式，使用真实接口的文本字段。
    monkeypatch.setattr(api, '提取API时间', lambda attrs,key: '2026-11-01 12:00:00' if '开始' in key else '2026-11-22 03:59:00')
    rows = api.API转活动列表(data, '2026-11-01 12:00:00')
    assert rows[0]['_API来源页'] == '完整事件/01'


def test_已有身份礼包不降级聚合且问题保留(内核模块):
    store = 内核模块('汇总_活动')
    a = dict(名称='礼包甲',类型=-1,开始时间='2026-11-01 12:00:00',结束时间='2026-11-22 03:59:00',_parent='父',_运行时身份='pack-a')
    b = {**a,'名称':'礼包乙','_运行时身份':'pack-b'}
    assert len(store.合并商店([a,b])) == 2
    a.pop('_运行时身份'); b.pop('_运行时身份'); a['_身份问题']='异常'
    assert store.合并商店([a,b])[0]['_身份问题']
