"""隔离纯函数验收，不联网、不修改生产数据。"""
from copy import deepcopy
from hashlib import sha256
import json
import pytest


@pytest.fixture
def store(内核模块):
    return 内核模块('身份存储试验')


def row(name='甲', key=None, **changes):
    result = dict(名称=name, 开始时间='2026-11-01 12:00:00',
                  结束时间='2026-11-15 03:59:00', 类型=1, 子类型='', 来源='公告甲')
    if key is not None:
        result.update(_运行时身份=key, _身份状态='来源内可对应')
    result.update(changes)
    return result


def test_六列canonical哈希不含序号或runtime(store):
    a = row()
    b = dict(reversed(list(a.items())))
    b.update(类型='1', _运行时身份='任意', 身份='别的身份')
    payload = json.dumps([str(a[k]) for k in store.旧列], ensure_ascii=False, separators=(',', ':'))
    assert store.旧行标识(a) == sha256(payload.encode('utf-8')).hexdigest()
    assert store.旧行标识(a) == store.旧行标识(b)
    assert store.旧行标识(a) != store.旧行标识(row('乙'))


def test_同名同类型同来源同日期仍只是候选(store):
    report, = store.预检旧行映射([row()], [row(key='id-a')])
    assert report['状态'] == '待确认'
    assert report['候选身份'] == ('id-a',)
    assert isinstance(report['候选原因'], tuple)
    with pytest.raises(store.身份存储冲突, match='候选关联未确认'):
        store.生成持久快照([row()], [row(key='id-a')], {})


def test_已身份改名日期和重排按key一行更新(store):
    old = [row(身份='a'), row('乙', 身份='b')]
    new = [row('乙新', 'b', 开始时间='2027-01-01 00:00:00'),
           row('甲新', 'a', 结束时间='2027-02-01 00:00:00')]
    reports = store.预检旧行映射(old, new)
    assert all(r['状态'] == '明确同key' for r in reports)
    out = store.生成持久快照(old, new, {})
    assert [(r['身份'], r['名称']) for r in out] == [('a', '甲新'), ('b', '乙新')]
    assert len(out) == 2


def test_同名不同身份不按display_name折叠(store):
    out = store.生成持久快照([], [row(key='a'), row(key='b')], {})
    assert len(out) == 2
    assert {r['身份'] for r in out} == {'a', 'b'}


def test_明确mapping可绑定改名移窗的旧行(store):
    old, new = row(), row('彻底改名', 'a', 开始时间='2027-01-01 00:00:00',
                           结束时间='2027-01-02 00:00:00')
    out = store.生成持久快照([old], [new], {store.旧行标识(old): 'a'})
    assert len(out) == 1 and out[0]['名称'] == '彻底改名'
    assert set(out[0]) == set(store.快照列)


def test_未知旧map或目标不在新输入拒绝(store):
    old = row()
    for mapping, text in [({'不存在': 'a'}, '未知旧行标识'),
                          ({store.旧行标识(old): '不存在'}, '映射目标不在新输入')]:
        with pytest.raises(store.身份存储冲突, match=text):
            store.生成持久快照([old], [row(key='a')], mapping)


def test_一旧总览对多新阶段不能伪绑后静默新增(store):
    old = row('总览', 结束时间='2026-11-30 00:00:00')
    new = [row('阶段甲', 'a', 结束时间='2026-11-10 00:00:00'),
           row('阶段乙', 'b', 开始时间='2026-11-12 00:00:00')]
    report, = store.预检旧行映射([old], new)
    assert report['阻止身份'] == ('a', 'b')
    with pytest.raises(store.身份存储冲突, match='候选关联未确认'):
        store.生成持久快照([old], new, {store.旧行标识(old): 'a'})
    out = store.生成持久快照([old], new, {}, ('a', 'b'))
    assert len(out) == 3 and out[0]['身份'] == ''
    assert out[0]['名称'] == '总览'


def test_多旧对一mapping拒绝(store):
    old = [row('旧甲'), row('旧乙')]
    mapping = {store.旧行标识(r): 'a' for r in old}
    with pytest.raises(store.身份存储冲突, match='多旧行同身份'):
        store.生成持久快照(old, [row('新', 'a')], mapping)


def test_重复payload不补序号且生成拒绝(store):
    old = [row(), row()]
    reports = store.预检旧行映射(old, [])
    assert reports[0]['行标识'] == reports[1]['行标识']
    assert all(r['状态'] == '重复旧行标识' for r in reports)
    with pytest.raises(store.身份存储冲突, match='重复旧行标识'):
        store.生成持久快照(old, [], {})


def test_新旧identity碰撞均拒绝(store):
    with pytest.raises(store.身份存储冲突, match='新identity碰撞'):
        store.生成持久快照([], [row(key='a'), row('另一个', 'a')], {})
    with pytest.raises(store.身份存储冲突, match='旧identity碰撞'):
        store.生成持久快照([row(身份='a'), row('另一个', 身份='a')], [], {})


def test_缺runtime待确认和空批次问题拒绝(store):
    class Batch(list):
        身份问题 = ('认领争议',)
    for new, text in [([row()], '_运行时身份'),
                      ([row(key='a', _身份状态='阶段身份待确认')], '待确认'),
                      (Batch(), '批次身份问题')]:
        with pytest.raises(store.身份存储冲突, match=text):
            store.生成持久快照([], new, {})


def test_输入不变成功失败和返回无共享可变值(store):
    old, new = [row()], [row(key='a')]
    before = deepcopy((old, new))
    store.预检旧行映射(old, new)
    with pytest.raises(store.身份存储冲突):
        store.生成持久快照(old, new, {})
    out = store.生成持久快照(old, new, {store.旧行标识(old[0]): 'a'})
    out[0]['名称'] = '外部修改'
    assert (old, new) == before


def test_未抓到已身份和过期legacy全部保留(store):
    old = [row('已身份', 身份='missing'),
           row('过期', 开始时间='2000-01-01 00:00:00', 结束时间='2000-01-02 00:00:00')]
    out = store.生成持久快照(old, [], {})
    assert len(out) == 2
    assert {r['名称'] for r in out} == {'已身份', '过期'}
    assert [r for r in out if not r['身份']][0]['身份状态'] == '未确认'


def test_低置信同parent同类型不阻止独立窗口新增(store):
    new = row('独立活动', 'a', 开始时间='2027-01-01 00:00:00',
              结束时间='2027-01-02 00:00:00')
    report, = store.预检旧行映射([row()], [new])
    assert report['状态'] == '低置信候选'
    assert report['候选身份'] == ('a',) and report['阻止身份'] == ()
    assert len(store.生成持久快照([row()], [new], {})) == 2
    # parent 明确矛盾或不同类型连候选都不列。
    for other in [row(key='a', 来源='公告乙'), row(key='a', 类型=2)]:
        assert store.预检旧行映射([row()], [other])[0]['候选身份'] == ()


def test_无来源卡池长期legacy本步不迁移且不折叠(store):
    old = [row('普通卡池', 类型=0, 来源=''), row('长期', 类型=99, 来源='')]
    new = [row('普通卡池', 'a', 类型=0, 来源='')]
    assert all(r['状态'] == 'legacy保留不迁移' for r in store.预检旧行映射(old, new))
    out = store.生成持久快照(old, new, {})
    assert len(out) == 3 and sum(not r['身份'] for r in out) == 2
    with pytest.raises(store.身份存储冲突, match='本步不迁移'):
        store.生成持久快照(old, new, {store.旧行标识(old[0]): 'a'})


def test_legacy候选不能静默更新已有identity(store):
    old = [row('身份行', 身份='a'), row('未确认')]
    new = [row('未确认', 'a')]
    with pytest.raises(store.身份存储冲突, match='候选关联未确认'):
        store.生成持久快照(old, new, {})
    with pytest.raises(store.身份存储冲突, match='已属于另一旧身份行'):
        store.生成持久快照(old, new, {store.旧行标识(old[1]): 'a'})


def test_新增批准未知重复冲突均拒绝(store):
    old = row()
    for approved, text in [(('未知',), '不在新输入'), (('a', 'a'), '重复')]:
        with pytest.raises(store.身份存储冲突, match=text):
            store.生成持久快照([old], [row(key='a')], {}, approved)
    with pytest.raises(store.身份存储冲突, match='矛盾'):
        store.生成持久快照([old], [row(key='a')], {store.旧行标识(old): 'a'}, ('a',))


def test_明确来源_parent和既有身份不能改绑(store):
    old = row(来源='显示来源甲', 来源_parent='公告稳定parent')
    new = row('改名', 'a', 来源='显示来源乙', 来源_parent='公告稳定parent')
    assert store.预检旧行映射([old], [new])[0]['阻止身份'] == ('a',)
    with pytest.raises(store.身份存储冲突, match='不可重新绑定'):
        store.生成持久快照([row(身份='old')], [row(key='new')],
                        {store.旧行标识(row()): 'new'})
