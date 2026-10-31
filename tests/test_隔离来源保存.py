"""来源局部隔离：正常行保存，受影响旧行既不更新也不自动清理。"""
import csv
import json

import pytest


def identity(protocol, page, title):
    return json.dumps([protocol, page, title], ensure_ascii=False)


def row(name, key='', parent='', end='2026-12-01 03:59:00', kind=1):
    result = dict(名称=name, 开始时间='2026-09-01 12:00:00', 结束时间=end,
                  类型=kind, _parent=parent)
    if key:
        result['_运行时身份'] = key
    return result


def batch(内核模块, rows=(), *, sources=(('页', '坏块'),), parents=('父',), issues=()):
    result = 内核模块('公告身份').公告条目批次(rows, issues)
    result.隔离来源 = sources
    result.更新问题 = ('坏块未更新',)
    result.保留来源父名 = parents
    return result


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize('protocol', ['公告局部-v1', '公告板块-v1'])
def test_隔离过期旧行不更新正常同父板块更新(tmp_path, 内核模块, protocol):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    bad = identity(protocol, '页', '坏块')
    good = identity('公告板块-v1', '页', '好块')
    store.合并保存CSV([row('坏旧', bad, '父', '2026-09-10 03:59:00'), row('好旧', good, '父')], path, '2026-09-01 12:00:00')
    diff = store.合并保存CSV(batch(内核模块, [row('坏新', bad, '父'), row('好新', good, '父')]), path, '2026-10-30 12:00:00')
    current = {r['身份']: r for r in read(path)}
    assert current[bad]['名称'] == '坏旧'
    assert current[bad]['结束时间'] == '2026-09-10 03:59:00'
    assert current[good]['名称'] == '好新'
    assert diff.改动 == ('好新',) and diff.过期清理 == 0


def test_活动关联匹配未知身份及保留legacy父名(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    protected = row('关系旧', 'opaque', '其他父', '2026-09-10 03:59:00')
    protected['_活动关联'] = identity('公告活动关联-v1', '页', '坏块')
    legacy = row('旧礼包', parent='父', end='2026-09-10 03:59:00', kind=-1)
    unknown = row('未知旧', 'unknown-source', '父', '2026-09-10 03:59:00')
    normal = row('正常', identity('公告板块-v1', '页', '好块'), '父')
    store.合并保存CSV([protected, legacy, unknown, normal], path, '2026-09-01 12:00:00')
    incoming = row('尝试覆盖', 'opaque')  # 无来源字段，仍须按原同键保护。
    store.合并保存CSV(batch(内核模块, [incoming, row('新正常', normal['_运行时身份'], '父')]), path, '2026-10-30 12:00:00')
    assert {r['名称'] for r in read(path)} == {'关系旧', '旧礼包', '未知旧', '新正常'}


def test_隔离新来源不新增并正常首次建文件(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    store.合并保存CSV(batch(内核模块, [row('拒绝新增', identity('公告板块-v1', '页', '坏块')),
                                             row('正常新增', identity('公告板块-v1', '页', '好块'))]),
                    path, '2026-10-30 12:00:00')
    assert [r['名称'] for r in read(path)] == ['正常新增']


def test_旧格式隔离父名保留过期行并不更新(tmp_path, 内核模块):
    path = tmp_path / '活动.csv'
    path.write_text('名称,开始时间,结束时间,类型,子类型,来源\n旧礼包,2026-09-01 12:00:00,2026-09-10 03:59:00,-1,,父\n', encoding='utf-8')
    store = 内核模块('汇总_活动')
    diff = store.合并保存CSV(batch(内核模块, [row('旧礼包', parent='父', kind=-1), row('正常池', kind=0)]), path, '2026-10-30 12:00:00')
    assert {r['名称'] for r in read(path)} == {'旧礼包', '正常池'}
    assert next(r for r in read(path) if r['名称'] == '旧礼包')['结束时间'] == '2026-09-10 03:59:00'
    assert diff.过期清理 == 0 and diff.改动 == ()


@pytest.mark.parametrize('transform', ['合并商店', '去重排序'])
def test_汇总操作传播全部元数据(内核模块, transform):
    source = batch(内核模块, [row('甲', kind=-1, parent='父'), row('乙', kind=-1, parent='父')], issues=('全局问题',))
    result = getattr(内核模块('汇总_活动'), transform)(source)
    for field in ('身份问题', '隔离来源', '更新问题', '保留来源父名'):
        assert getattr(result, field) == getattr(source, field)


@pytest.mark.parametrize('fault', ['身份状态', '日期', '列数'])
def test_隔离父名不能绕过旧坏行校验(tmp_path, 内核模块, fault):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    store.合并保存CSV([row('旧', 'unknown', '父')], path, '2026-09-01 12:00:00')
    content = path.read_text(encoding='utf-8-sig')
    if fault == '身份状态':
        content = content.replace('已确认', '未确认')
    elif fault == '日期':
        content = content.replace('2026-12-01 03:59:00', '损坏日期')
    else:
        content += '坏行\n'
    path.write_text(content, encoding='utf-8-sig')
    original = path.read_bytes()
    with pytest.raises(store.身份冲突):
        store.合并保存CSV(batch(内核模块, [row('正常', 'good')]), path, '2026-10-30 12:00:00')
    assert path.read_bytes() == original


def test_全局身份问题仍拒绝(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    with pytest.raises(store.身份冲突):
        store.合并保存CSV(batch(内核模块, [row('正常', 'good')], issues=('未隔离的全局身份问题',)),
                        tmp_path / '活动.csv', '2026-10-30 12:00:00')



def test_隔离元数据不绕过写锁(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    lock = tmp_path / '.活动.csv.lock'
    lock.write_bytes(b'other writer')
    with pytest.raises(store.身份冲突, match='正在写回'):
        store.合并保存CSV(batch(内核模块, [row('正常', 'good')]), path, '2026-10-30 12:00:00')
    assert lock.read_bytes() == b'other writer'
    assert not path.exists()


def test_不同父未知身份照常清理解析正常坐标不受父名误保护(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    store.合并保存CSV([row('保护', 'opaque', '父', '2026-09-10 03:59:00'),
                    row('不同父', 'another', '其他父', '2026-09-10 03:59:00'),
                    row('正常坐标', identity('公告板块-v1', '页', '好块'), '父', '2026-09-10 03:59:00'),
                    row('正常存活', 'still-good')], path, '2026-09-01 12:00:00')
    diff = store.合并保存CSV(batch(内核模块, []), path, '2026-10-30 12:00:00', 允许大幅清理=True)
    assert {r['名称'] for r in read(path)} == {'保护', '正常存活'}
    assert diff.过期清理 == 2


def test_隔离新行仍不能隐藏待确认或损坏字段(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    incoming = row('坏行', identity('公告板块-v1', '页', '坏块'))
    incoming['_身份状态'] = '待确认'
    with pytest.raises(store.身份冲突):
        store.合并保存CSV(batch(内核模块, [incoming]), tmp_path / '活动.csv', '2026-10-30 12:00:00')

def test_同父被隔离不吞掉正常无身份的卡池与礼包(tmp_path, 内核模块):
    """兼容类型（0/-1）可以没有运行时身份，只带 `_来源板块`。

    持久化行没有这个键，若只用持久化行判隔离，就会退回父来源判断，
    把同父的正常卡池/礼包一起丢掉（2026-10-31 实测：卫戍协议板块被隔离后，
    【将雪投火】、【卫戍寻访】、中坚甄选、联合行动、组合包全部未落盘）。
    """
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    store.合并保存CSV([row('底行', 'normal', end='2027-01-01 03:59:00')], path, '2026-09-01 12:00:00')
    pool = dict(名称='【寻访】将雪投火 · 塔露拉 / 冻河', 开始时间='2026-11-01 12:00:00',
                结束时间='2026-11-15 03:59:00', 类型=0, _parent='父',
                _来源板块=('页', '好块'))
    gift = dict(名称='父 礼包', 开始时间='2026-11-01 12:00:00',
                结束时间='2027-05-01 11:59:00', 类型=-1, _parent='父',
                _来源板块=('页', '好块'))
    # 坏块不进入本批（解析阶段就按来源隔离），批次只带"该来源已隔离"的元数据。
    diff = store.合并保存CSV(batch(内核模块, [pool, gift]), path, '2026-10-31 03:00:00')
    assert {r['名称'] for r in read(path)} == {'底行', '【寻访】将雪投火 · 塔露拉 / 冻河', '父 礼包'}
    assert set(diff.新增) == {'【寻访】将雪投火 · 塔露拉 / 冻河', '父 礼包'}


def test_旧格式不能通过隔离runtime绕过迁移(tmp_path, 内核模块):
    path = tmp_path / '活动.csv'
    path.write_text('名称,开始时间,结束时间,类型,子类型,来源\n旧池,2026-09-01 12:00:00,2026-12-01 03:59:00,0,,父\n', encoding='utf-8')
    original = path.read_bytes()
    store = 内核模块('汇总_活动')
    with pytest.raises(store.身份冲突, match='旧格式'):
        store.合并保存CSV(batch(内核模块, [row('坏块', identity('公告板块-v1', '页', '坏块'))]), path, '2026-10-30 12:00:00')
    assert path.read_bytes() == original
