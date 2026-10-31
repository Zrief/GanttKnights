"""运行时身份与旧CSV碰撞护栏，不使用真实数据。"""
from datetime import datetime
import pytest


def parse(api, notice, text, members=()):
    return api.认领与生成(list(members), {notice: api.抽板块(text, datetime(2026, 11, 1))})


def stage_text(order):
    return '==SideStory「例子」==\n活动关卡开放时间：\n' + '\n'.join(
        f'◆【{name}】开启时间：11月01日 12:00 - 11月22日 03:59' for name in order)


def test_改图名日期与阶段重排不改对象身份(内核模块):
    api = 内核模块('解析_API活动')
    before = parse(api, '例子/活动公告', stage_text(['甲', '乙']))
    after = parse(api, '例子/活动公告', stage_text(['丙', '乙', '甲']).replace('11月22日', '11月23日'))
    keys = lambda rows: {r['_原对象']: r['_运行时身份'] for r in rows}
    assert keys(before)[('甲',)] == keys(after)[('甲',)]
    assert keys(before)[('乙',)] == keys(after)[('乙',)]
    assert before[0]['名称'] != after[2]['名称']


def test_认领前后名字变化身份不变(内核模块):
    api = 内核模块('解析_API活动')
    text = stage_text(['甲', '乙'])
    m = dict(事件名='例子', 显示名='官方显示名', 公告页='例子/活动公告', 锚点=None,
             开始='2026-11-01 12:00:00', 结束='2026-11-22 03:59:00', 类型=1, 已结束=False)
    before = parse(api, '例子/活动公告', text)
    after = parse(api, '例子/活动公告', text, [m])
    assert [r['_运行时身份'] for r in before] == [r['_运行时身份'] for r in after]
    assert before[0]['名称'] != after[0]['名称']


def test_不同公告同名同窗不吞行且拒旧CSV键(tmp_path, 内核模块):
    api, store = 内核模块('解析_API活动'), 内核模块('汇总_活动')
    rows = parse(api, '例子/公告甲', stage_text(['甲'])) + parse(api, '例子/公告乙', stage_text(['甲']))
    for r in rows:
        r['名称'] = '同一图名'
    assert len(store.去重排序(rows)) == 2
    path = tmp_path / 'x.csv'
    path.write_text('原始内容', encoding='utf-8')
    with pytest.raises(store.身份冲突, match='旧格式'):
        store.合并保存CSV(rows, path, '2026-11-01 12:00:00')
    assert path.read_text(encoding='utf-8') == '原始内容'


def test_无对象纯编号允许生成但拒写(tmp_path, 内核模块):
    api, store = 内核模块('解析_API活动'), 内核模块('汇总_活动')
    text = '==SideStory「例子」==\n活动关卡开放时间：\n◆第一段\n开放时间：11月01日 12:00 - 11月22日 03:59'
    rows = parse(api, '例子/活动公告', text)
    assert rows == [] and rows.隔离来源 == (('例子/活动公告', 'SideStory「例子」'),)
    assert rows.更新问题 and not rows.身份问题
    assert store.去重排序(rows).隔离来源 == rows.隔离来源
    path = tmp_path / 'x.csv'
    store.检查身份写回(rows)
    assert not path.exists()


def test_重复对象同窗不靠去重掩盖(tmp_path, 内核模块):
    api, store = 内核模块('解析_API活动'), 内核模块('汇总_活动')
    rows = parse(api, '例子/活动公告', stage_text(['甲', '甲']))
    assert rows == [] and rows.隔离来源
    assert any('身份重复' in p for p in rows.更新问题)
    assert store.去重排序(rows).隔离来源 == rows.隔离来源
    store.检查身份写回(rows)


def test_重复标题不补序号身份(tmp_path, 内核模块):
    api, store = 内核模块('解析_API活动'), 内核模块('汇总_活动')
    rows = parse(api, '例子/活动公告', stage_text(['甲']) + '\n' + stage_text(['乙']))
    assert rows == [] and rows.隔离来源 == (('例子/活动公告', 'SideStory「例子」'),)
    assert any('重复来源标题' in p for p in rows.更新问题)
    store.检查身份写回(rows)


def test_无来源直接阶段调用不能写盘(tmp_path, 内核模块):
    notice, store = 内核模块('解析_公告'), 内核模块('汇总_活动')
    b, = notice.抽板块(stage_text(['甲']), datetime(2026, 11, 1))
    rows = notice.板块条目(b, '例子')
    with pytest.raises(store.身份冲突):
        store.合并保存CSV(rows, tmp_path / 'x.csv', '2026-11-01 12:00:00')


def test_空输出争议仍阻止其他正常条目保存(内核模块):
    api, store = 内核模块('解析_API活动'), 内核模块('汇总_活动')
    text = ('==SideStory「例子」==\n活动关卡开放时间：\n◆第一段\n'
            '开放时间：11月01日版本更新后 - 11月22日 03:59\n'
            '==【普通登录】活动开启==\n活动时间：11月01日 12:00 - 11月22日 03:59')
    members = [dict(事件名='例子', 显示名=n, 公告页='例子/活动公告', 锚点=None,
                    开始='2026-11-01 12:00:00', 结束='2026-11-22 03:59:00', 类型=1, 已结束=False)
               for n in ['甲', '乙']]
    rows = parse(api, '例子/活动公告', text, members)
    assert rows and not rows.身份问题 and rows.更新问题
    rows = store.去重排序(store.合并商店(rows))
    assert rows.隔离来源 == (('例子/活动公告', 'SideStory「例子」'),)
    assert [r['名称'] for r in rows] == ['普通登录']
    store.检查身份写回(rows)


def test_争议礼包合并后仍拒写(内核模块):
    api, store = 内核模块('解析_API活动'), 内核模块('汇总_活动')
    text = ('==组合包限时上架==\n售卖时间：11月01日 12:00 - 11月22日 03:59\n'
            '==组合包限时上架==\n售卖时间：11月01日 12:00 - 11月22日 03:59')
    rows = parse(api, '例子/活动公告', text)
    rows = store.去重排序(store.合并商店(rows))
    assert rows == [] and not rows.身份问题
    assert rows.隔离来源 == (('例子/活动公告', '组合包限时上架'),)
    assert rows.更新问题
    store.检查身份写回(rows)


def test_成员同级争议源条目生成但拒写(内核模块):
    api, store = 内核模块('解析_API活动'), 内核模块('汇总_活动')
    members = [dict(事件名='例子', 显示名=n, 公告页='例子/活动公告', 锚点=None,
                    开始='2026-11-01 12:00:00', 结束='2026-11-22 03:59:00', 类型=1, 已结束=False)
               for n in ['甲', '乙']]
    rows = parse(api, '例子/活动公告', stage_text(['区域']), members)
    assert rows == [] and not rows.身份问题
    assert rows.隔离来源 == (('例子/活动公告', 'SideStory「例子」'),)
    assert any('认领身份争议' in p for p in rows.更新问题)
    store.检查身份写回(rows)


def test_争议长期成员不能ask兜底(内核模块):
    api = 内核模块('解析_API活动')
    text = '==【共享活动】活动开启==\n活动时间：11月01日 12:00 - 11月22日 03:59'
    members = [dict(事件名='共享活动', 显示名=name, 公告页='例子/活动公告', 锚点=None,
                    开始='2026-01-01 12:00:00', 结束='2027-01-01 12:00:00', 类型=99, 已结束=False)
               for name in ['甲', '乙']]
    rows = parse(api, '例子/活动公告', text, members)
    assert not any(r['名称'] in {'甲', '乙'} for r in rows)
