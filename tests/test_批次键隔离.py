"""正式合流卡池07:00/12:00竞争离线机制回归，不用活动名补丁。"""
import csv
import pytest


def test_公告优先后同来源被隔离仍保留旧卡池键(内核模块):
    cls = 内核模块('公告身份').公告条目批次
    table = dict(名称='【寻访】池 · 甲', 类型=0, 开始时间='2026-11-01 07:00:00', 结束时间='2026-11-15 03:59:00', _卡池来源='卡池一览')
    notice = dict(table, 开始时间='2026-11-01 12:00:00', _卡池来源='公告', _来源板块=('页', '块'))
    collision = dict(名称='争议', 类型=1, _运行时身份='same', _来源板块=('页', '块'))
    batch = 内核模块('批次隔离').隔离批次冲突(cls([table, notice, collision, dict(collision)]))
    assert not batch and (0, '甲') in batch.保留兼容键
    assert 内核模块('隔离来源').来源被隔离(table, batch)


def test_API后备身份竞争保留旧过期行(tmp_path, 内核模块):
    cls = 内核模块('公告身份').公告条目批次
    identity = '["PRTS事件页-v1","prts.wiki","事件页"]'
    old = dict(名称='后备活动', 类型=1, 开始时间='2026-01-01 12:00:00', 结束时间='2026-01-15 03:59:00', _运行时身份=identity)
    good = dict(名称='正常活动', 类型=1, 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-22 03:59:00', _运行时身份='normal')
    batch = 内核模块('批次隔离').隔离批次冲突(cls([old, dict(old), good]))
    assert batch.保留运行时身份 == (identity,) and list(batch) == [good]
    store = 内核模块('汇总_活动')
    batch = store.去重排序(store.合并商店(batch))
    assert batch.保留运行时身份 == (identity,)
    path = tmp_path / '活动.csv'
    store.合并保存CSV([old, good], path, '2026-01-01 18:00:00')
    store.合并保存CSV(batch, path, '2026-10-30 18:00:00')
    with path.open(encoding='utf-8-sig', newline='') as f:
        saved = list(csv.DictReader(f))
    assert any(r['身份'] == identity for r in saved)


def test_卡池冲突隔离双方并保留旧记录(tmp_path, 内核模块):
    cls = 内核模块('公告身份').公告条目批次
    row = dict(名称='【寻访】测试 · 干员甲', 类型=0, 子类型='限时', 开始时间='2026-03-10 07:00:00', 结束时间='2026-03-24 03:59:00')
    other = dict(row, 开始时间='2026-03-10 12:00:00', _parent='公告父', _来源板块=('公告父/活动公告', '寻访开启'))
    good = dict(名称='正常活动', 类型=1, 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-22 03:59:00', _运行时身份='normal')
    batch = 内核模块('批次隔离').隔离批次冲突(cls([row, other, good]))
    assert [r['名称'] for r in batch] == ['正常活动']
    assert batch.保留兼容键 == ((0, '干员甲'),)
    assert batch.隔离来源 == (('公告父/活动公告', '寻访开启'),)
    assert batch.更新问题
    path = tmp_path / '活动.csv'
    store = 内核模块('汇总_活动')
    store.合并保存CSV([good, row], path, '2026-03-10 17:00:00')
    store.合并保存CSV(batch, path, '2026-10-30 17:00:00')
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert next(r for r in rows if r['类型'] == '0')['开始时间'] == row['开始时间']


def test_同卡池同时间同内容仅父来源缺省不误隔离(内核模块):
    cls = 内核模块('公告身份').公告条目批次
    row = dict(名称='【寻访】测试 · 干员甲', 类型=0, 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-15 03:59:00')
    other = dict(row, _parent='公告父', _来源板块=('公告父/活动公告', '寻访开启'))
    batch = 内核模块('批次隔离').隔离批次冲突(cls([row, other]))
    assert len(batch) == 1 and not batch.隔离来源 and not batch.更新问题


@pytest.mark.parametrize('反序', [False, True])
def test_同干员时间冲突公告优先不隔离(tmp_path, 内核模块, 反序):
    cls = 内核模块('公告身份').公告条目批次
    table = dict(名称='【寻访】某池 · 乙 / 甲', 类型=0, 子类型='限时', 开始时间='2026-11-01 07:00:00',
                 结束时间='2026-11-15 03:59:00', _卡池来源='卡池一览')
    notice = dict(table, 名称='【寻访】公告名称 · 甲 / 乙', 开始时间='2026-11-01 12:00:00',
                  结束时间='2026-11-16 03:59:00', _卡池来源='公告', _来源板块=('页', '池公告'), _parent='父')
    inputs = [table, notice]
    if 反序:
        inputs.reverse()
    batch = 内核模块('批次隔离').隔离批次冲突(cls(inputs))
    assert list(batch) == [notice] and not batch.更新问题 and not batch.隔离来源
    good = dict(名称='活动', 类型=1, 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-22 03:59:00', _运行时身份='normal')
    batch.append(good)
    path = tmp_path / '活动.csv'
    store = 内核模块('汇总_活动')
    store.合并保存CSV([table, good], path, '2026-10-30 18:00:00')
    store.合并保存CSV(batch, path, '2026-10-30 18:00:00')
    with path.open(encoding='utf-8-sig', newline='') as f:
        saved = next(r for r in csv.DictReader(f) if r['类型'] == '0')
    assert saved['开始时间'] == notice['开始时间'] and saved['结束时间'] == notice['结束时间']


@pytest.mark.parametrize('情形', ['多公告', '多期一览'])
def test_同干员多个期次来源不靠公告优先猜配对(内核模块, 情形):
    cls = 内核模块('公告身份').公告条目批次
    table = dict(名称='【寻访】某池 · 甲', 类型=0, 子类型='限时', 开始时间='2026-11-01 07:00:00',
                 结束时间='2026-11-15 03:59:00', _卡池来源='卡池一览')
    notice = dict(table, 开始时间='2026-11-01 12:00:00', _卡池来源='公告', _来源板块=('页', '池公告'))
    extra = dict(notice, _来源板块=('页', '另期公告')) if 情形 == '多公告' else dict(table, 开始时间='2026-10-01 12:00:00')
    batch = 内核模块('批次隔离').隔离批次冲突(cls([table, notice, extra]))
    assert not batch and batch.更新问题


def test_运行时身份冲突只隔离相关块(内核模块):
    cls = 内核模块('公告身份').公告条目批次
    row = dict(名称='冲突', 类型=1, _运行时身份='same', _来源板块=('页', '块'))
    good = dict(名称='正常', 类型=1, _运行时身份='good', _来源板块=('页', '其他块'))
    batch = 内核模块('批次隔离').隔离批次冲突(cls([row, dict(row), good]))
    assert list(batch) == [good] and batch.隔离来源 == (('页', '块'),)
