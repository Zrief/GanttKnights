"""事务验收仅在 tmp_path 写入，不访问生产数据或网络。"""
import csv
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread

import pytest


@pytest.fixture
def tx(内核模块):
    return 内核模块('CSV事务')


@pytest.fixture
def store(内核模块):
    return 内核模块('身份CSV存储')


def row(key):
    return dict(名称=key, 开始时间='2026-11-01 12:00:00',
                结束时间='2026-11-15 03:59:00', 类型=1, _运行时身份=key)


def save(store, path, key):
    return store.保存身份CSV([row(key)], path, '2026-11-02 00:00:00')


def identities(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return {r['身份'] for r in csv.DictReader(stream)}


def lockpath(path):
    target = path.resolve()
    return target.with_name(f'.{target.name}.lock')


def test_原文字节不存在与同目录原子写(tx, tmp_path):
    path = tmp_path / 'a.csv'
    with tx.CSV写事务(path) as original:
        assert original is None and lockpath(path).exists()
        tx.原子写CSV(path, b'first', original)
    assert path.read_bytes() == b'first' and not lockpath(path).exists()
    with tx.CSV写事务(path) as original:
        assert original == b'first'
        tx.原子写CSV(path, b'second', original)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('initial', [None, b'old'])
def test_外部编辑CAS拒绝保留外部原文(tx, store, tmp_path, initial):
    path = tmp_path / 'a.csv'
    if initial is not None:
        path.write_bytes(initial)
    unrelated = tmp_path / '.a.csv.foreign.tmp'
    unrelated.write_bytes(b'keep')
    with pytest.raises(store.身份存储冲突, match='外部修改'):
        with tx.CSV写事务(path) as original:
            path.write_bytes(b'foreign')
            tx.原子写CSV(path, b'would overwrite', original)
    assert path.read_bytes() == b'foreign'
    assert set(tmp_path.iterdir()) == {path, unrelated}


def test_外部删除CAS拒绝(tx, store, tmp_path):
    path = tmp_path / 'a.csv'
    path.write_bytes(b'old')
    with pytest.raises(store.身份存储冲突, match='外部修改'):
        with tx.CSV写事务(path) as original:
            path.unlink()
            tx.原子写CSV(path, b'new', original)
    assert not path.exists() and list(tmp_path.iterdir()) == []


def test_异常释放自己的锁(tx, tmp_path):
    path = tmp_path / 'a.csv'
    with pytest.raises(RuntimeError, match='body'):
        with tx.CSV写事务(path):
            raise RuntimeError('body')
    assert list(tmp_path.iterdir()) == []
    with tx.CSV写事务(path):
        pass


def test_replace失败只清自己temp(tx, tmp_path, monkeypatch):
    path = tmp_path / 'a.csv'
    path.write_bytes(b'old')
    unrelated = tmp_path / '.a.csv.foreign.tmp'
    unrelated.write_bytes(b'keep')
    def fail(source, target):
        assert Path(source).parent == path.parent.resolve()
        assert Path(target) == path.resolve()
        raise OSError('replace failure')
    monkeypatch.setattr(tx.os, 'replace', fail)
    with pytest.raises(OSError, match='replace failure'):
        with tx.CSV写事务(path) as original:
            tx.原子写CSV(path, b'new', original)
    assert path.read_bytes() == b'old'
    assert set(tmp_path.iterdir()) == {path, unrelated}


def test_残留锁立即拒绝且不自动清理(tx, store, tmp_path):
    path = tmp_path / 'a.csv'
    lock = lockpath(path)
    lock.write_bytes(b'crashed owner')
    os.utime(lock, (1, 1))
    with pytest.raises(store.身份存储冲突, match='正在写回'):
        with tx.CSV写事务(path):
            pytest.fail('must not enter')
    assert lock.read_bytes() == b'crashed owner' and not path.exists()


def test_锁被外部替换不删外部锁(tx, tmp_path):
    path = tmp_path / 'a.csv'
    lock = lockpath(path)
    # Windows 不允许删除尚有打开句柄的文件；改写 token 仍须保留。
    with tx.CSV写事务(path):
        lock.write_bytes(b'foreign owner')
    assert lock.read_bytes() == b'foreign owner'


def test_锁路径为符号链接不跟随不删除(tx, store, tmp_path):
    path = tmp_path / 'a.csv'
    foreign = tmp_path / 'foreign'
    foreign.write_bytes(b'keep')
    try:
        lockpath(path).symlink_to(foreign)
    except OSError:
        pytest.skip('host does not allow symlinks')
    with pytest.raises(store.身份存储冲突, match='正在写回'):
        with tx.CSV写事务(path):
            pytest.fail('must not enter')
    assert lockpath(path).is_symlink() and foreign.read_bytes() == b'keep'


def test_锁路径为目录不删除(tx, store, tmp_path):
    path = tmp_path / 'a.csv'
    lock = lockpath(path)
    lock.mkdir()
    marker = lock / 'foreign'
    marker.write_bytes(b'keep')
    with pytest.raises((store.身份存储冲突, PermissionError, IsADirectoryError)):
        with tx.CSV写事务(path):
            pytest.fail('must not enter')
    assert marker.read_bytes() == b'keep'


def test_身份事务持锁直到replace结束(store, tmp_path, monkeypatch):
    path = tmp_path / 'a.csv'
    native_replace = store.os.replace
    calls = []
    def guarded_replace(source, target):
        with pytest.raises(store.身份存储冲突, match='正在写回'):
            save(store, path, 'second')
        calls.append(True)
        native_replace(source, target)
        assert lockpath(path).exists()
    monkeypatch.setattr(store.os, 'replace', guarded_replace)
    save(store, path, 'first')
    assert calls == [True] and identities(path) == {'first'}
    assert not lockpath(path).exists()


def test_同路径别名也争用(tx, store, tmp_path):
    path = tmp_path / 'a.csv'
    nested = tmp_path / 'child'
    nested.mkdir()
    alias = nested / '..' / 'a.csv'
    with tx.CSV写事务(path):
        with pytest.raises(store.身份存储冲突, match='正在写回'):
            with tx.CSV写事务(alias):
                pytest.fail('alias bypassed lock')
    assert not lockpath(path).exists()


@pytest.mark.parametrize('prior', [False, True])
def test_线程读合并期间第二调用拒绝后重试无丢行(store, tmp_path, monkeypatch, prior):
    path = tmp_path / 'a.csv'
    if prior:
        save(store, path, 'prior')
    entered, release = Event(), Event()
    failures = []
    native_read = store._读旧行
    def blocked_read(target):
        result = native_read(target)
        entered.set()
        if not release.wait(10):
            raise RuntimeError('test release timeout')
        return result
    monkeypatch.setattr(store, '_读旧行', blocked_read)
    def first():
        try:
            save(store, path, 'first')
        except BaseException as exc:
            failures.append(exc)
    thread = Thread(target=first)
    thread.start()
    try:
        assert entered.wait(10)
        with pytest.raises(store.身份存储冲突, match='正在写回'):
            save(store, path, 'second')
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and failures == []
    monkeypatch.setattr(store, '_读旧行', native_read)
    save(store, path, 'second')
    assert identities(path) == ({'prior'} if prior else set()) | {'first', 'second'}
    assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize('prior', [False, True])
def test_子进程保存争用拒绝并可随后合并(tx, store, tmp_path, prior):
    path = tmp_path / 'a.csv'
    if prior:
        save(store, path, 'prior')
    code = '''import importlib, pathlib, sys, types
pkg = types.ModuleType('gk')
pkg.__path__ = [sys.argv[1]]
sys.modules['gk'] = pkg
store = importlib.import_module('gk.src.身份CSV存储')
row = dict(名称='child', 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-15 03:59:00', 类型=1, _运行时身份='child')
try:
    store.保存身份CSV([row], pathlib.Path(sys.argv[2]), '2026-11-02 00:00:00')
except store.身份存储冲突 as exc:
    if '正在写回' not in str(exc):
        raise
    sys.exit(23)
'''
    args = [sys.executable, '-c', code, str(Path(__file__).resolve().parents[1]), str(path)]
    with tx.CSV写事务(path):
        result = subprocess.run(args, timeout=15, check=False)
        assert result.returncode == 23
        assert identities(path) == {'prior'} if prior else not path.exists()
    save(store, path, 'parent')
    result = subprocess.run(args, timeout=15, check=False)
    assert result.returncode == 0
    assert identities(path) == ({'prior'} if prior else set()) | {'parent', 'child'}


def test_身份模块CAS检测序列化期间外部编辑(store, tmp_path, monkeypatch):
    path = tmp_path / 'a.csv'
    save(store, path, 'prior')
    native = store.csv.DictWriter.writerows
    def external_edit(writer, rows):
        native(writer, rows)
        path.write_bytes(b'foreign')
    monkeypatch.setattr(store.csv.DictWriter, 'writerows', external_edit)
    with pytest.raises(store.身份存储冲突, match='外部修改'):
        save(store, path, 'new')
    assert path.read_bytes() == b'foreign' and set(tmp_path.iterdir()) == {path}
