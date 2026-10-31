"""旧CSV严格读取、合并事务及失败不伤原文；仅使用临时数据。"""
import csv
import io

import pytest

from src import 汇总_活动 as store
from src.CSV事务 import CSV写事务


NOW = '2026-11-01 12:00:00'
FIELDS = ['名称', '开始时间', '结束时间', '类型', '子类型', '来源']


def event(name='普通旧姓名', **changes):
    row = {'名称': name, '开始时间': '2026-10-01 12:00:00',
           '结束时间': '2026-11-20 12:00:00', '类型': 1}
    row.update(changes)
    return row


def old_bytes(rows, fields=FIELDS):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(fields)
    writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')


def values(name='普通旧姓名', **changes):
    row = event(name, **changes)
    return [row.get(k, '') for k in FIELDS]


def save(path, rows=(), **kwargs):
    return store.合并保存CSV(list(rows), path, NOW, **kwargs)


@pytest.mark.parametrize('fields', [
    ['名称', '开始时间', '结束时间'],
    FIELDS + ['未知'],
    FIELDS + ['名称'],
])
def test_拒绝缺失未知重复表头(tmp_path, fields):
    path = tmp_path / 'old.csv'
    original = old_bytes([], fields)
    path.write_bytes(original)
    with pytest.raises(store.身份冲突, match='表头'):
        save(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('row', [values()[:-1], values() + ['多余'], [], values('   ')])
def test_坏列空行空名不被吞掉(tmp_path, row):
    path = tmp_path / 'old.csv'
    original = old_bytes([values('甲'), row])
    path.write_bytes(original)
    with pytest.raises(store.身份冲突):
        save(path, [event('乙')], 允许大幅清理=True)
    assert path.read_bytes() == original


def test_严格reader拒绝损坏引号(tmp_path):
    path = tmp_path / 'old.csv'
    original = old_bytes([]) + b'"unterminated'
    path.write_bytes(original)
    with pytest.raises(store.身份冲突, match='语法'):
        save(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('changes', [
    {'开始时间': '2026-02-30 12:00:00'},
    {'开始时间': '2026-1-01 12:00:00'},
    {'结束时间': '2026-09-30 12:00:00'},
    {'类型': '1.0'}, {'类型': 'True'},
])
def test_旧数据非法日期顺序类型拒写(tmp_path, changes):
    path = tmp_path / 'old.csv'
    original = old_bytes([values(**changes)])
    path.write_bytes(original)
    with pytest.raises(store.身份冲突):
        save(path, 允许大幅清理=True)
    assert path.read_bytes() == original


@pytest.mark.parametrize('rows', [
    [values(), values()],
    [values('【生息演算】例子', 类型=99), values('生息演算「例子」', 类型=99)],
    [values('池甲 · 甲 / 乙', 类型=0), values('池乙 · 乙 / 甲', 类型=0)],
])
def test_旧文件同身份键多行一律拒绝(tmp_path, rows):
    path = tmp_path / 'old.csv'
    original = old_bytes(rows)
    path.write_bytes(original)
    with pytest.raises(store.身份冲突, match='身份冲突'):
        save(path, 允许大幅清理=True)
    assert path.read_bytes() == original


@pytest.mark.parametrize('changes', [
    {'开始时间': True}, {'结束时间': '2026-09-01 00:00:00'},
    {'类型': True}, {'类型': 1.0}, {'类型': '1'}, {'名称': ''},
])
def test_新活动日期类型严格校验(tmp_path, changes):
    path = tmp_path / 'old.csv'
    original = old_bytes([values('甲')])
    path.write_bytes(original)
    with pytest.raises(store.身份冲突):
        save(path, [event(**changes)])
    assert path.read_bytes() == original


@pytest.mark.parametrize('changes', [
    {'结束时间': '2026-11-21 12:00:00'}, {'子类型': '变更'}, {'_parent': '另一来源'},
])
def test_新输入同键不同有效载荷拒绝(tmp_path, changes):
    path = tmp_path / 'old.csv'
    with pytest.raises(store.身份冲突, match='身份冲突'):
        save(path, [event(), event(**changes)])
    assert not path.exists()


def test_新输入归一键冲突不覆盖(tmp_path):
    path = tmp_path / 'old.csv'
    with pytest.raises(store.身份冲突):
        save(path, [event('池甲 · 甲 / 乙', 类型=0), event('池乙 · 乙 / 甲', 类型=0)])
    assert not path.exists()


def test_完全相同新输入允许去重(tmp_path):
    path = tmp_path / 'old.csv'
    diff = save(path, [event(), event()])
    assert diff.首次 and not diff.有变化
    rows = list(csv.DictReader(io.StringIO(path.read_bytes().decode('utf-8-sig'))))
    assert len(rows) == 1 and rows[0]['名称'] == '普通旧姓名'


def test_四列旧格式与普通姓名可安全增量保存(tmp_path):
    path = tmp_path / 'old.csv'
    path.write_bytes(old_bytes([values()[:4]], FIELDS[:4]))
    diff = save(path, [event('第二条')])
    assert diff.原有条数 == 1 and diff.新增 == ('第二条',)
    rows = list(csv.DictReader(io.StringIO(path.read_bytes().decode('utf-8-sig'))))
    assert {r['名称'] for r in rows} == {'普通旧姓名', '第二条'}
    assert rows[0]['子类型'] == rows[0]['来源'] == ''


def test_护栏使用完整旧记录数(tmp_path, monkeypatch):
    path = tmp_path / 'old.csv'
    path.write_bytes(old_bytes([values('甲'), values('乙'), values('丙')]))
    calls = []
    monkeypatch.setattr(store, '校验写回', lambda before, after: calls.append((before, after)))
    diff = save(path, [event('丁')])
    assert calls == [(3, 4)] and diff.原有条数 == 3


def test_保留七天边界与原差异政策(tmp_path):
    path = tmp_path / 'old.csv'
    path.write_bytes(old_bytes([
        values('清理', 结束时间='2026-10-25 11:59:59'),
        values('边界', 结束时间='2026-10-25 12:00:00'),
        values('修改'),
    ]))
    diff = save(path, [event('修改', 结束时间='2026-11-21 12:00:00'), event('新增')])
    assert diff.原有条数 == 3 and diff.过期清理 == 1
    assert diff.新增 == ('新增',) and diff.改动 == ('修改',)


def test_替换失败保留原文清理临时文件(tmp_path, monkeypatch):
    path = tmp_path / 'old.csv'
    original = old_bytes([values()])
    path.write_bytes(original)
    def fail(src, dst):
        assert src.parent == path.parent
        assert src.read_bytes().startswith(b'\xef\xbb\xbf')
        raise OSError('replace failed')
    monkeypatch.setattr(store.os, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        save(path, [event('新增')])
    assert path.read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))
    assert not list(tmp_path.glob('*.lock'))


def test_序列化失败不触碰目标(tmp_path, monkeypatch):
    path = tmp_path / 'old.csv'
    original = old_bytes([values()])
    path.write_bytes(original)
    def fail(self, rows):
        raise OSError('serialize failed')
    monkeypatch.setattr(store.csv.DictWriter, 'writerows', fail)
    with pytest.raises(OSError, match='serialize failed'):
        save(path, [event('新增')])
    assert path.read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))


def test_锁内检测外部字节改动不覆盖(tmp_path, monkeypatch):
    path = tmp_path / 'old.csv'
    path.write_bytes(old_bytes([values()]))
    external = old_bytes([values('外部编辑')])
    original_guard = store.校验写回
    def edit_during_merge(before, after):
        assert (tmp_path / '.old.csv.lock').exists()
        path.write_bytes(external)
        original_guard(before, after)
    monkeypatch.setattr(store, '校验写回', edit_during_merge)
    with pytest.raises(store.身份冲突, match='修改'):
        save(path, [event('新增')])
    assert path.read_bytes() == external
    assert not list(tmp_path.glob('*.tmp'))


def test_共享锁争用拒写且不删除对方锁(tmp_path):
    path = tmp_path / 'old.csv'
    original = old_bytes([values()])
    path.write_bytes(original)
    with CSV写事务(path):
        with pytest.raises(store.身份冲突, match='正在写回'):
            save(path, [event('新增')])
        assert (tmp_path / '.old.csv.lock').exists()
        assert path.read_bytes() == original
    assert not (tmp_path / '.old.csv.lock').exists()
