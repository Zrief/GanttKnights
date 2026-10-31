"""活动更新状态：跨 CLI/插件出图保留部分失败提示，不影响 CSV 事务。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .日志 import logger


def 记录更新状态(目录, 时间: str, 问题=(), *, 成功: bool = True) -> None:
    path = Path(目录) / '活动更新状态.json'
    payload = dict(时间=时间, 成功=成功, 问题=list(dict.fromkeys(问题)))
    owned = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.活动更新状态.', suffix='.tmp', delete=False) as stream:
            owned = Path(stream.name).resolve()
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(owned, path)
    except OSError:
        logger.exception('记录活动更新状态失败（不影响已有CSV）')
    finally:
        if owned is not None:
            if owned.parent != path.parent.resolve() or not owned.name.startswith('.活动更新状态.'):
                raise RuntimeError('更新状态临时文件路径不一致')
            owned.unlink(missing_ok=True)


def 读取更新提示(目录) -> str:
    path = Path(目录) / '活动更新状态.json'
    if not path.exists():
        return ''
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        problems = state['问题']
        if not isinstance(problems, list) or not all(isinstance(p, str) for p in problems):
            raise ValueError('问题格式错误')
        if not problems and state['成功'] is True:
            return ''
        title = '部分活动未更新' if state['成功'] is True else '活动数据更新失败，沿用可读取的旧数据'
        details = '\n'.join('• ' + p for p in problems)
        return f'⚠ {title}（最近尝试：{state["时间"]}）' + ('\n' + details if details else '')
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception('读取活动更新状态失败')
        return '⚠ 活动更新状态无法读取，请查看日志；不能确认本次数据完整。'
