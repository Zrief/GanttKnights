"""最终运行批次局部冲突隔离；使用既有存储键，不按日期挑赢家。"""
from __future__ import annotations

from .隔离来源 import 复制批次元数据, 来源被隔离
from .汇总_活动 import _身份键


def 隔离批次冲突(rows):
    batch = 复制批次元数据(rows, rows)
    groups = {}
    for row in batch:
        key = ('identity', row['_运行时身份']) if row.get('_运行时身份') else ('legacy', row['类型'], _身份键(row['名称'], row['类型']))
        groups.setdefault(key, []).append(row)
    blocked_ids = set()
    isolated = set(batch.隔离来源)
    parents = set(batch.保留来源父名)
    compatibility = set(batch.保留兼容键)
    runtime = set(batch.保留运行时身份)
    problems = list(batch.更新问题)
    selected_pools = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        if key[0] == 'legacy' and key[1] == 0 and ' · ' in items[0]['名称']:
            announcements = [r for r in items if r.get('_卡池来源') == '公告']
            tables = [r for r in items if r.get('_卡池来源') == '卡池一览']
            if announcements and tables and len(announcements) + len(tables) == len(items):
                # 名单为对应依据；同批仅一个公告来源才可覆盖一览时间。
                # 多个一览期次或多个公告板块不按时间猜配对。
                coords = {tuple(r.get('_来源板块', ())) for r in announcements}
                fields = ('开始时间', '结束时间', '子类型')
                signatures = {tuple(r.get(f, '') for f in fields) for r in announcements}
                if (len(coords) == 1 and all(coords) and len(signatures) == 1 and len(tables) == 1):
                    winner = announcements[0]
                    selected_pools.append((winner, (key[1], key[2])))
                    blocked_ids.update(id(r) for r in items if r is not winner)
                    continue
        # 完全相同兼容观测可消重；身份重复保守隔离。
        if key[0] == 'legacy' and all({k: r.get(k, '') for k in ('名称', '开始时间', '结束时间', '类型', '子类型')} ==
                                   {k: items[0].get(k, '') for k in ('名称', '开始时间', '结束时间', '类型', '子类型')} for r in items):
            blocked_ids.update(id(r) for r in items[1:])
            continue
        blocked_ids.update(id(r) for r in items)
        for row in items:
            if row.get('_来源板块'):
                isolated.add(tuple(row['_来源板块']))
            isolated.update(tuple(c) for c in row.get('_来源板块们', ()))
            if row.get('_parent'):
                parents.add(row['_parent'])
        if key[0] == 'legacy':
            compatibility.add((key[1], key[2]))
        else:
            runtime.add(key[1])
        problems.append(f'存储键竞争：{items[0]["名称"]}（{len(items)}条来源记录），相关来源已隔离，不按日期选择赢家')
    batch.隔离来源 = tuple(sorted(isolated))
    batch.保留来源父名 = tuple(sorted(parents))
    batch.保留兼容键 = tuple(sorted(compatibility))
    batch.保留运行时身份 = tuple(sorted(runtime))
    for winner, pool_key in selected_pools:
        if 来源被隔离(winner, batch):
            compatibility.add(pool_key)
    batch.保留兼容键 = tuple(sorted(compatibility))
    batch.更新问题 = tuple(dict.fromkeys(problems))
    batch[:] = [r for r in batch if id(r) not in blocked_ids and not 来源被隔离(r, batch)]
    return batch
