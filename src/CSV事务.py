"""CSV 跨进程读合并写事务（标准库，争用立即拒绝，不等待）。

同一规范路径使用同目录 .<文件名>.lock 的独占创建锁。必须从读取旧行前
到最终 replace 后一直持锁。进程崩溃可能留下锁：保守拒绝后续写入，须用户
确认没有写入者后手动清理；绝不按锁龄自动删除。原文比较另拦截不遵循锁的
外部编辑，但普通文件系统不提供 compare-and-replace，比较与 replace 之间
仍有极短窗口；外部写入者也应遵循该锁协议。
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterator
from uuid import uuid4


def _冲突(message: str):
    # 延迟导入：旧存储分支复用本模块时不形成模块导入循环。
    from .身份存储错误 import 身份存储冲突
    return 身份存储冲突(message)


def _读原文(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def 校验CSV原文(path: str | Path, original: bytes | None) -> None:
    """在持有 CSV写事务 锁时，紧邻 replace 前检查原始字节（含不存在状态）。"""
    if _读原文(Path(path)) != original:
        raise _冲突('CSV原文已被外部修改，拒绝覆盖')


@contextmanager
def CSV写事务(path: str | Path) -> Iterator[bytes | None]:
    """独占整个读→合并→写事务，yield 加锁后捕获的原始字节或 None。

    相对路径、.. 和符号链接别名统一 resolve；争用立即抛身份存储冲突。
    只清理本次创建且身份仍一致的锁，不删除他人锁或崩溃残留锁。
    """
    target = Path(path).resolve()
    lock = target.with_name(f'.{target.name}.lock')
    parent = target.parent
    token = uuid4().hex.encode('ascii')
    try:
        stream = lock.open('xb')
    except FileExistsError as exc:
        raise _冲突('正在写回（或存在崩溃残留锁；请确认后手动清理）') from exc
    owned = os.fstat(stream.fileno())
    initialized = False
    try:
        stream.write(token)
        stream.flush()
        initialized = True
        yield _读原文(target)
    finally:
        stream.close()
        # lstat 不跟随符号链接；核对本次独占创建的 inode，不删被替换的锁。
        if lock.parent != parent or lock.name != f'.{target.name}.lock':
            raise RuntimeError('锁文件路径校验失败')
        try:
            current = lock.lstat()
        except FileNotFoundError:
            pass
        else:
            if (stat.S_ISREG(current.st_mode)
                    and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino)
                    and (not initialized or lock.read_bytes() == token)):
                lock.unlink()


def 原子写CSV(path: str | Path, payload: bytes, original: bytes | None) -> None:
    """调用方须持有 CSV写事务；同目录临时文件 fsync、原文CAS、replace。

    本函数不另取锁（避免嵌套锁），original 必须来自当前事务。异常仅清理
    本次创建且核对过路径的临时文件，不触碰别人的临时文件或锁。
    """
    target = Path(path).resolve()
    parent = target.parent
    owned_temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, dir=parent,
                                         prefix=f'.{target.name}.', suffix='.tmp') as stream:
            owned_temp = Path(stream.name).resolve()
            if owned_temp.parent != parent or not owned_temp.name.startswith(f'.{target.name}.'):
                raise RuntimeError('临时文件路径校验失败')
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        校验CSV原文(target, original)
        os.replace(owned_temp, target)
    finally:
        if owned_temp is not None:
            if owned_temp.parent != parent or not owned_temp.name.startswith(f'.{target.name}.'):
                raise RuntimeError('临时文件路径校验失败')
            owned_temp.unlink(missing_ok=True)


__all__ = ['CSV写事务', '原子写CSV', '校验CSV原文']
