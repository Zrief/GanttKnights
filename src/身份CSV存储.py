"""正式十二列身份存储（兼容旧八列）：不猜身份，不自动迁移旧行。"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
import io
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

from .CSV事务 import CSV写事务, 校验CSV原文
from .数据保护 import 校验写回
from .身份存储错误 import 身份存储冲突
from .身份存储试验 import 快照列, 预检旧行映射
from .隔离来源 import 来源被隔离

业务列 = ('活动关联', '活动本名', '时间角色', '阶段序号')
保存列 = (*快照列, *业务列)
过期保留天数 = 7
兼容类型 = frozenset((0, 99, -1))
日期格式 = '%Y-%m-%d %H:%M:%S'
核心列 = frozenset(('名称', '开始时间', '结束时间', '类型'))


@dataclass(frozen=True)
class 身份CSV差异:
    新增: tuple[str, ...] = ()
    改动: tuple[str, ...] = ()
    过期清理: int = 0
    原有条数: int = 0

    @property
    def 有变化(self) -> bool:
        return bool(self.新增 or self.改动 or self.过期清理)

    @property
    def 首次(self) -> bool:
        return self.原有条数 == 0


def _日期(value: object, label: str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.microsecond:
            raise 身份存储冲突(f'{label}必须为无时区的整秒日期')
        value = value.strftime(日期格式)
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        raise 身份存储冲突(f'{label}日期格式错误')
    try:
        parsed = datetime.strptime(value, 日期格式)
    except ValueError as exc:
        raise 身份存储冲突(f'{label}日期无效') from exc
    if parsed.strftime(日期格式) != value:
        raise 身份存储冲突(f'{label}日期格式错误')
    return value


def _文本(value: object, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise 身份存储冲突(f'{label}必须为字符串（且非空字段不得为空白）')
    return value


def _记录(raw: dict, *, old: bool) -> dict:
    if not isinstance(raw, dict) or not 核心列.issubset(raw):
        raise 身份存储冲突('行缺少旧核心四列')
    kind = raw['类型']
    if old:
        if not isinstance(kind, str) or not re.fullmatch(r'-?(?:0|[1-9]\d*)', kind):
            raise 身份存储冲突('旧行类型必须为整数文本')
        kind = int(kind)
    elif type(kind) is not int:
        raise 身份存储冲突('新行类型必须严格为int（不能为bool）')
    start, end = _日期(raw['开始时间'], '开始时间'), _日期(raw['结束时间'], '结束时间')
    if end < start:
        raise 身份存储冲突('结束时间早于开始时间')
    identity = raw.get('身份', '') if old else raw.get('_运行时身份', '')
    identity = _文本(identity, '身份')
    if identity and not identity.strip():
        raise 身份存储冲突('身份不得为空白')
    status = '已确认' if identity else '未确认'
    if old and raw.get('身份状态') != status:
        raise 身份存储冲突('旧行身份状态与身份不一致')
    if not old:
        if raw.get('_身份问题') or any('待确认' in str(raw.get(k, '')) for k in ('_身份状态', '身份状态')):
            raise 身份存储冲突('新行身份待确认或存在争议')
        if '身份' in raw and raw['身份'] != identity:
            raise 身份存储冲突('身份与运行时身份不一致')
        if '身份状态' in raw and raw['身份状态'] != status:
            raise 身份存储冲突('新行身份状态与身份不一致')
        if not identity and (kind not in 兼容类型 or '_局部身份依据' in raw):
            raise 身份存储冲突('普通新行缺少_运行时身份，禁止用显示名造身份')
    source = raw.get('来源', '')
    if not old and '_parent' in raw:
        if source and source != raw['_parent']:
            raise 身份存储冲突('来源与_parent不一致')
        source = raw['_parent']
    relation = raw.get('活动关联', '') if old else raw.get('_活动关联', raw.get('活动关联', ''))
    base = raw.get('活动本名', '') if old else raw.get('_活动本名', raw.get('活动本名', ''))
    role = raw.get('时间角色', '') if old else raw.get('_原角色', raw.get('时间角色', ''))
    if role == '公告明示活动窗口':
        role = '活动总窗'
    sequence = raw.get('阶段序号', '0') if old else raw.get('_阶段序号', raw.get('阶段序号', 0))
    if isinstance(sequence, str) and re.fullmatch(r'0|[1-9]\d*', sequence):
        sequence = int(sequence)
    if type(sequence) is not int or sequence < 0:
        raise 身份存储冲突('阶段序号必须为非负整数')
    relation, base, role = (_文本(relation, '活动关联'), _文本(base, '活动本名'), _文本(role, '时间角色'))
    if role and (not identity or not relation or not base):
        raise 身份存储冲突('时间角色须有身份、明确活动关联与本名')
    if role == '关卡开放' and sequence < 1:
        raise 身份存储冲突('关卡开放须有明确阶段序号')
    if sequence and role != '关卡开放':
        raise 身份存储冲突('非关卡开放不能带阶段序号')
    return dict(名称=_文本(raw['名称'], '名称', nonempty=True), 开始时间=start,
                结束时间=end, 类型=kind, 子类型=_文本(raw.get('子类型', ''), '子类型'),
                来源=_文本(source, '来源'), 身份=identity, 身份状态=status,
                活动关联=relation, 活动本名=base, 时间角色=role, 阶段序号=sequence)


def _读旧行(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.reader(stream, strict=True)
        try:
            fields = next(reader, [])
            if len(fields) != len(set(fields)) or not 核心列.issubset(fields):
                raise 身份存储冲突('CSV schema缺少核心列或重复列')
            if {'身份', '身份状态'} & set(fields) != {'身份', '身份状态'}:
                raise 身份存储冲突('CSV必须已有完整身份列；部分身份列或旧格式拒绝')
            if set(fields) - set(保存列):
                raise 身份存储冲突('CSV schema存在未知列')
            rows = []
            for values in reader:
                if len(values) != len(fields):
                    raise 身份存储冲突('CSV坏行：列数与表头不一致')
                rows.append(_记录(dict(zip(fields, values)), old=True))
            return rows
        except (csv.Error, UnicodeError) as exc:
            raise 身份存储冲突('CSV编码或解析失败') from exc


def _键(row: dict, legacy_key: Callable[[str, int], str] | None) -> tuple:
    if row['身份']:
        return ('identity', row['身份'])
    if legacy_key is None:
        raise 身份存储冲突('legacy行需要调用方提供legacy_key')
    value = legacy_key(row['名称'], row['类型'])
    return ('legacy', row['类型'], _文本(value, 'legacy_key', nonempty=True))


def 保存身份CSV(
    新活动列表: list[dict], 输出路径: str | Path, 现在时间: str | datetime,
    允许大幅清理: bool = False, *, legacy_key: Callable[[str, int], str] | None = None,
    重建: bool = False,
) -> 身份CSV差异:
    """整批验证后增量原子保存；失败不改原文件，不删除未抓到行。

    `重建=True` 时**不读旧文件**：本次输入就是全部内容（初始化/`--bootstrap` 用），
    旧行与旧六列格式都不再保留；仍是先写临时文件再原子替换，失败则原文件不动。
    重建仍按过期线过滤（只落有效期内条目），否则下一次日常刷新会把它当成待清理存量、
    触发大幅清理保护。日常刷新不要传 `重建`，否则会丢掉本次没抓到但仍在有效期内的行。

    其余既有约束：新文件须有 runtime 输入，可混 0/99/-1 兼容行；普通旧空身份行只保留或
    过期清理；有阻止候选须外部先迁好身份。相同 legacy 旧行保留行数。
    legacy_key(名称, 类型) 由调用方注入，另加类型并与身份键隔离。
    跨进程同路径读合并写全程持锁；正在写回立即拒绝。崩溃残留锁不会
    自动删除，须用户确认没有写入者后手动清理。replace 前比较原文字节，
    不覆盖事务期间检测到的外部编辑。
    """
    path = Path(输出路径).resolve()
    with CSV写事务(path) as original:
        return _保存身份CSV(新活动列表, path, 现在时间, 允许大幅清理,
                        legacy_key=legacy_key, _原始字节=original, 重建=重建)


def _保存身份CSV(
    新活动列表: list[dict], 输出路径: str | Path, 现在时间: str | datetime,
    允许大幅清理: bool = False, *, legacy_key: Callable[[str, int], str] | None = None,
    _原始字节: bytes | None,
    重建: bool = False,
) -> 身份CSV差异:
    if type(允许大幅清理) is not bool:
        raise 身份存储冲突('允许大幅清理必须为bool')
    now = _日期(现在时间, '现在时间')
    if getattr(新活动列表, '身份问题', ()):
        raise 身份存储冲突('本次批次身份存在争议')
    path = Path(输出路径)
    old = [] if 重建 else _读旧行(path)
    old_metadata = {row['身份']: row for row in old if row['身份']}
    prepared = []
    for raw in 新活动列表:
        item = dict(raw)
        previous = old_metadata.get(raw.get('_运行时身份'))
        if previous is not None:
            for k, runtime in zip(业务列, ('_活动关联', '_活动本名', '_原角色', '_阶段序号')):
                if k not in item and runtime not in item:
                    item[k] = previous[k]
        prepared.append(item)
    validated = [_记录(raw, old=False) for raw in prepared]
    protected_keys = {_键(row, legacy_key) for row in old if 来源被隔离(row, 新活动列表)}

    def 带来源(row: dict, raw: dict) -> dict:
        """判定隔离用"持久化行 + 输入行里的来源标记"。

        兼容类型（0/99/-1）的新输入可以没有运行时身份，只带 `_来源板块`；
        持久化后的行没有这个键，单看它就只能退回父来源判断——同父的其它板块
        一旦被隔离（如卫戍协议），这些本来正常的卡池/礼包会被一起丢掉。
        """
        视图 = dict(row)
        for k in ('_来源板块', '_来源板块们', '_运行时身份', '_parent'):
            值 = raw.get(k)
            if 值:
                视图[k] = 值
        return 视图

    accepted = [(raw, row) for raw, row in zip(新活动列表, validated)
                if not 来源被隔离(带来源(row, raw), 新活动列表)
                and _键(row, legacy_key) not in protected_keys]
    new = [row for _, row in accepted]
    if not path.exists() and not any(row['身份'] for row in new):
        raise 身份存储冲突('不存在的CSV必须有运行时身份输入')
    old_groups: dict[tuple, list[int]] = {}
    for index, row in enumerate(old):
        key = _键(row, legacy_key)
        indices = old_groups.setdefault(key, [])
        if indices and (row['身份'] or old[indices[0]] != row):
            raise 身份存储冲突('旧身份重复或同键legacy多行冲突')
        indices.append(index)
    new_by_key = {}
    for row in new:
        key = _键(row, legacy_key)
        if key in new_by_key:
            raise 身份存储冲突('同源运行时身份重复或新legacy同键重复')
        new_by_key[key] = row
    ordinary = [row for row in old if not row['身份'] and row['类型'] not in 兼容类型
                and not 来源被隔离(row, 新活动列表)]
    runtime = [dict(row, _运行时身份=row['身份']) for row in new if row['身份']]
    if any(report['阻止身份'] for report in 预检旧行映射(ordinary, runtime)):
        raise 身份存储冲突('普通旧legacy存在候选关联，必须外部预先迁好身份')
    supplied_metadata = {}
    for raw, row in accepted:
        supplied_metadata[_键(row, legacy_key)] = {
            k for k, runtime in zip(业务列, ('_活动关联', '_活动本名', '_原角色', '_阶段序号'))
            if k in raw or runtime in raw}
    merged = [dict(row) for row in old]
    for key, row in new_by_key.items():
        if key in old_groups:
            for index in old_groups[key]:
                update = dict(row)
                if row['身份']:
                    for k in 业务列:
                        if k not in supplied_metadata[key]:
                            update[k] = old[index][k]
                merged[index] = update
                new_by_key[key] = update
        else:
            merged.append(dict(row))
    # 校验保留旧元数据后的最终状态，而不仅是更新前的输入。
    stage_keys = set()
    for row in merged:
        _记录(dict(row, 类型=str(row['类型'])), old=True)
        if row['时间角色'] == '关卡开放':
            stage_key = (row['活动关联'], row['阶段序号'])
            if stage_key in stage_keys:
                raise 身份存储冲突('同一活动关联的阶段序号重复，需确认旧阶段映射')
            stage_keys.add(stage_key)
    cutoff = (datetime.strptime(now, 日期格式) - timedelta(days=过期保留天数)).strftime(日期格式)
    # 重建同样按过期线过滤：初始化会做全量回溯扫描，但只有**有效期内**的条目才落盘。
    # 否则旧条目会在下一次日常刷新时被当成"要清理的存量"，直接触发 50% 清理保护、
    # 让刷新一直失败（2026-10-31 宿主实测：177 条里 146 条过期）。
    survivors = [row for row in merged if row['结束时间'] >= cutoff
                 or _键(row, legacy_key) in protected_keys]
    survivor_keys = {_键(row, legacy_key) for row in survivors}
    added = tuple(row['名称'] for key, row in new_by_key.items()
                  if key in survivor_keys and key not in old_groups)
    changed = tuple(row['名称'] for key, row in new_by_key.items()
                    if key in survivor_keys and key in old_groups and row != old[old_groups[key][0]])
    removed = sum(len(indices) for key, indices in old_groups.items() if key not in survivor_keys)
    if not old:
        added = changed = ()
    if not 允许大幅清理:
        校验写回(len(old), len(survivors))
    survivors.sort(key=lambda row: row['开始时间'])
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=保存列)
    writer.writeheader()
    writer.writerows(survivors)
    payload = buffer.getvalue().encode('utf-8-sig')
    parent = path.parent.resolve()
    owned_temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, dir=parent,
                                         prefix=f'.{path.name}.', suffix='.tmp') as stream:
            owned_temp = Path(stream.name).resolve()
            if owned_temp.parent != parent or not owned_temp.name.startswith(f'.{path.name}.'):
                raise RuntimeError('临时文件路径校验失败')
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        校验CSV原文(path, _原始字节)
        os.replace(owned_temp, path)
    finally:
        if owned_temp is not None:
            # 只清理由本次调用创建且已核对目录的唯一路径。
            if owned_temp.parent != parent or not owned_temp.name.startswith(f'.{path.name}.'):
                raise RuntimeError('临时文件路径校验失败')
            owned_temp.unlink(missing_ok=True)
    return 身份CSV差异(added, changed, removed, len(old))


__all__ = ['保存身份CSV', '身份CSV差异', '身份存储冲突']
