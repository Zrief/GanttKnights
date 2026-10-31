"""身份正式存储的隔离验收：只读指定快照，全部写入tmp_path。"""
from copy import deepcopy
import csv
from datetime import datetime
from pathlib import Path
import shutil

import pytest

NOW = '2026-11-02 00:00:00'
FIELDS = ('名称', '开始时间', '结束时间', '类型', '子类型', '来源', '身份', '身份状态')
OUTPUT_FIELDS = (*FIELDS, '活动关联', '活动本名', '时间角色', '阶段序号')


@pytest.fixture
def store(内核模块):
    return 内核模块('身份CSV存储')


def row(name='甲', key='a', **changes):
    result = dict(名称=name, 开始时间='2026-11-01 12:00:00',
                  结束时间='2026-11-15 03:59:00', 类型=1, 子类型='', _parent='公告甲')
    if key is not None:
        result.update(_运行时身份=key, _身份状态='来源内可对应')
    result.update(changes)
    return result


def oldrow(name='甲', key='a', **changes):
    result = dict(名称=name, 开始时间='2026-11-01 12:00:00',
                  结束时间='2026-11-15 03:59:00', 类型=1, 子类型='', 来源='公告甲',
                  身份=key, 身份状态='已确认' if key else '未确认')
    result.update(changes)
    return result


def write_old(path, rows, fields=FIELDS):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def legacy_key(name, kind):
    if kind == 0 and ' · ' in name:
        return ' / '.join(sorted(name.split(' · ', 1)[1].split(' / ')))
    return name.replace('长期「', '').replace('」', '') if kind == 99 else name


def save(store, rows, path, now=NOW, **kwargs):
    return store.保存身份CSV(rows, path, now, legacy_key=legacy_key, **kwargs)


def test_19行隔离快照同身份改名改窗仍19行(store, tmp_path):
    source = Path(__file__).resolve().parents[1] / 'tests/fixtures/身份快照_19行.csv'
    path = tmp_path / 'isolated.csv'
    shutil.copyfile(source, path)
    original = read_rows(path)
    old = next(r for r in original if r['名称'].endswith('·一阶段'))
    diff = save(store, [row('新版阶段名', old['身份'], 开始时间='2026-11-02 12:00:00',
                           结束时间='2026-11-24 03:59:00', _parent=old['来源'])], path)
    result = read_rows(path)
    assert len(result) == 19 and len({r['身份'] for r in result if r['身份']}) == 13
    assert sum(r['身份'] == old['身份'] for r in result) == 1
    assert diff.改动 == ('新版阶段名',) and diff.新增 == () and diff.原有条数 == 19


def test_新文件runtime兼容混合八列和首次(store, tmp_path):
    path = tmp_path / 'new.csv'
    diff = save(store, [row(), row('礼包', None, 类型=-1)], path)
    result = read_rows(path)
    assert tuple(result[0]) == OUTPUT_FIELDS and len(result) == 2
    assert diff.首次 and not diff.有变化
    assert {r['身份状态'] for r in result} == {'已确认', '未确认'}


def test_卡池长期礼包兼容更新且类型隔离(store, tmp_path):
    path = tmp_path / 'old.csv'
    write_old(path, [oldrow('池旧 · 乙 / 甲', '', 类型=0),
                     oldrow('长期「对象」', '', 类型=99), oldrow('对象', '', 类型=-1)])
    diff = save(store, [row('池新 · 甲 / 乙', None, 类型=0),
                        row('对象', None, 类型=99), row('对象', None, 类型=-1, 子类型='礼包')], path)
    assert len(read_rows(path)) == 3
    assert diff.改动 == ('池新 · 甲 / 乙', '对象', '对象')


def test_同名不同来源身份可并存(store, tmp_path):
    path = tmp_path / 'same.csv'
    write_old(path, [oldrow()])
    diff = save(store, [row(key='b', _parent='公告乙')], path)
    assert len(read_rows(path)) == 2 and diff.新增 == ('甲',)


def test_旧legacy与identity同名同key不混并(store, tmp_path):
    path = tmp_path / 'same.csv'
    write_old(path, [oldrow('礼包', '', 类型=-1)])
    save(store, [row('礼包', '礼包', 类型=-1)], path)
    assert [r['身份'] for r in read_rows(path)] == ['', '礼包']


def test_未抓到不删除普通legacy也不刷新(store, tmp_path):
    path = tmp_path / 'missing.csv'
    old = [oldrow(), oldrow('未知普通', '', 类型=2)]
    write_old(path, old)
    before = read_rows(path)
    diff = save(store, [], path)
    current = read_rows(path)
    assert [{k:r[k] for k in FIELDS} for r in current] == before and not diff.有变化
    assert all(r['活动关联'] == '' and r['阶段序号'] == '0' for r in current)


def test_过期清理7天边界且新过期不报新增(store, tmp_path):
    path = tmp_path / 'expiry.csv'
    write_old(path, [oldrow('边界', 'edge', 开始时间='2026-10-20 00:00:00',
                            结束时间='2026-10-26 00:00:00'),
                     oldrow('旧过期', '', 类型=2, 开始时间='2026-10-20 00:00:00',
                            结束时间='2026-10-25 23:59:59')])
    diff = save(store, [row('新过期', 'expired', 开始时间='2026-10-20 00:00:00',
                           结束时间='2026-10-21 00:00:00')], path)
    assert [r['名称'] for r in read_rows(path)] == ['边界']
    assert diff.过期清理 == 1 and diff.新增 == ()


def test_普通旧legacy同名或含窗候选必须外部迁移(store, tmp_path):
    path = tmp_path / 'candidate.csv'
    write_old(path, [oldrow(key='')])
    before = path.read_bytes()
    for new in [row(), row('改名同窗'), row('局部阶段', 开始时间='2026-11-03 00:00:00')]:
        with pytest.raises(store.身份存储冲突, match='外部预先迁好'):
            save(store, [new], path)
        assert path.read_bytes() == before


def test_普通旧legacy低置信或不同来源可新增(store, tmp_path):
    path = tmp_path / 'independent.csv'
    write_old(path, [oldrow(key='')])
    diff = save(store, [row('不同窗', 'b', 开始时间='2026-12-01 00:00:00',
                           结束时间='2026-12-02 00:00:00'), row(key='c', _parent='公告乙')], path)
    assert len(read_rows(path)) == 3 and len(diff.新增) == 2


def test_新旧重复身份拒绝原文不变(store, tmp_path):
    path = tmp_path / 'dupes.csv'
    write_old(path, [oldrow()])
    before = path.read_bytes()
    with pytest.raises(store.身份存储冲突, match='重复'):
        save(store, [row(), row('乙')], path)
    assert path.read_bytes() == before
    write_old(path, [oldrow(), oldrow('乙')])
    before = path.read_bytes()
    with pytest.raises(store.身份存储冲突, match='重复'):
        save(store, [], path)
    assert path.read_bytes() == before


def test_同键legacy冲突拒绝且完全相同行不吞(store, tmp_path):
    path = tmp_path / 'legacy.csv'
    write_old(path, [oldrow('礼包', '', 类型=-1), oldrow('礼包', '', 类型=-1, 来源='另一公告')])
    before = path.read_bytes()
    with pytest.raises(store.身份存储冲突, match='冲突'):
        save(store, [], path)
    assert path.read_bytes() == before
    write_old(path, [oldrow('礼包', '', 类型=-1)] * 2)
    diff = save(store, [], path)
    assert len(read_rows(path)) == diff.原有条数 == 2


def test_schema旧格式部分身份缺核心重复未知列拒绝(store, tmp_path):
    path = tmp_path / 'schema.csv'
    for header in [FIELDS[:6], FIELDS[:7], FIELDS[1:], (*FIELDS, '名称'), (*FIELDS, '未知')]:
        path.write_text(','.join(header) + '\n', encoding='utf-8-sig')
        before = path.read_bytes()
        with pytest.raises(store.身份存储冲突):
            save(store, [row()], path)
        assert path.read_bytes() == before


def test_核心四列加身份列可补可选两列(store, tmp_path):
    path = tmp_path / 'minimal.csv'
    fields = ('名称', '开始时间', '结束时间', '类型', '身份', '身份状态')
    write_old(path, [{k: v for k, v in oldrow().items() if k in fields}], fields)
    save(store, [], path)
    assert tuple(read_rows(path)[0]) == OUTPUT_FIELDS


def test_坏行空名短行长行非法类型状态拒绝(store, tmp_path):
    path = tmp_path / 'bad.csv'
    for change in [dict(名称=''), dict(类型='True'), dict(身份=' '), dict(身份状态='未确认'),
                   dict(开始时间='2026-11-1 12:00:00'), dict(结束时间='2026-10-01 00:00:00')]:
        write_old(path, [oldrow(**change)])
        before = path.read_bytes()
        with pytest.raises(store.身份存储冲突):
            save(store, [], path)
        assert path.read_bytes() == before
    for values in ['甲,2026', ','.join(['x'] * 9), '']:
        path.write_text(','.join(FIELDS) + '\n' + values + '\n', encoding='utf-8-sig')
        with pytest.raises(store.身份存储冲突):
            save(store, [], path)


def test_新普通无runtime日期类型状态矛盾拒绝(store, tmp_path):
    path = tmp_path / 'invalid.csv'
    for new in [row(key=None), row(类型=True), row(类型='1'), row(类型=1.0),
                row(开始时间='2026-11-1 12:00:00'), row(结束时间='2026-02-30 00:00:00'),
                row(结束时间='2026-10-01 00:00:00'), row(身份='b'), row(身份状态='未确认'),
                row(_运行时身份=' ')]:
        with pytest.raises(store.身份存储冲突):
            save(store, [new], path)
        assert not path.exists()
    with pytest.raises(store.身份存储冲突, match='必须有运行时'):
        save(store, [row('礼包', None, 类型=-1)], path)


def test_待确认同源和空批次争议拒绝(store, tmp_path):
    class Batch(list):
        身份问题 = ('认领争议',)
    path = tmp_path / 'pending.csv'
    for rows in [[row(_身份状态='阶段身份待确认')], [row(_身份问题='重复认领')],
                 [row('礼包', None, 类型=-1, _身份状态='合并来源身份待确认')], Batch()]:
        with pytest.raises(store.身份存储冲突):
            save(store, rows, path)
        assert not path.exists()


def test_日期datetime规范化子类型来源单改也报改动输入不变(store, tmp_path):
    path = tmp_path / 'changes.csv'
    write_old(path, [oldrow()])
    new = [row(开始时间=datetime(2026, 11, 1, 12), 子类型='阶段', _parent='新来源')]
    before = deepcopy(new)
    diff = save(store, new, path, now=datetime(2026, 11, 2))
    assert diff.改动 == ('甲',) and new == before
    diff = save(store, [row(子类型='阶段', _parent='第三来源')], path)
    assert diff.改动 == ('甲',)


def test_数据保护校验在写盘前且显式允许清理(store, tmp_path, 内核模块):
    path = tmp_path / 'guard.csv'
    write_old(path, [oldrow()])
    before = path.read_bytes()
    with pytest.raises(内核模块('数据保护').数据保护拦截):
        save(store, [], path, now='2030-01-01 00:00:00')
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
    diff = save(store, [], path, now='2030-01-01 00:00:00', 允许大幅清理=True)
    assert read_rows(path) == [] and diff.过期清理 == 1


def test_atomic_replace失败保持原文件清理自己temp(store, tmp_path, monkeypatch):
    path = tmp_path / 'atomic.csv'
    write_old(path, [oldrow()])
    before = path.read_bytes()
    unrelated = tmp_path / '.atomic.csv.other.tmp'
    unrelated.write_text('不能删', encoding='utf-8')
    def fail(source, target):
        assert Path(source).parent == tmp_path.resolve()
        assert Path(source).exists() and Path(target) == path
        assert read_rows(source)[0]['名称'] == '新版'
        raise OSError('replace simulated failure')
    monkeypatch.setattr(store.os, 'replace', fail)
    with pytest.raises(OSError, match='simulated'):
        save(store, [row('新版')], path)
    assert path.read_bytes() == before
    assert set(tmp_path.iterdir()) == {path, unrelated}


def test_序列化失败不触碰原文件也不留temp(store, tmp_path, monkeypatch):
    path = tmp_path / 'serialize.csv'
    write_old(path, [oldrow()])
    before = path.read_bytes()
    def fail(*args, **kwargs):
        raise ValueError('serialization simulated failure')
    monkeypatch.setattr(store.csv.DictWriter, 'writerows', fail)
    with pytest.raises(ValueError, match='serialization'):
        save(store, [row('新版')], path)
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
