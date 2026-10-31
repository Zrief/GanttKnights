"""初始化（/方舟日程 初始化、cli.py --bootstrap）＝覆盖重建（2026-10-31 定）。

语义：
- 重建不读旧文件：本次全量扫描结果就是全部内容，旧行与旧六列格式一并被替换；
- 日常刷新仍走增量合并（未抓到的不删除），两条路径不能混；
- 失败时原文件不动（原子替换只在全部校验通过后发生）。
"""
from __future__ import annotations

import csv
import json

import pytest


def 行(名, 起='2026-11-01 12:00:00', 止='2026-11-22 03:59:00', *, 类型=1, 身份=None):
    d = dict(名称=名, 开始时间=起, 结束时间=止, 类型=类型, _parent='父')
    if 身份 is not None:
        d['_运行时身份'] = 身份
    return d


旧六列 = ('名称,开始时间,结束时间,类型,子类型,来源\n'
         '旧活动,2026-10-01 12:00:00,2026-10-20 03:59:00,1,,\n'
         '旧长期,2026-05-15 16:00:00,2027-05-15 03:59:00,99,,\n')


def 读(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def test_重建直接覆盖旧六列并写成十二列(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    path.write_text(旧六列, encoding='utf-8')
    diff = store.合并保存CSV([行('新活动', 身份='new-1')], path, '2026-10-31 12:00:00', 重建=True)
    rows = 读(path)
    assert [r['名称'] for r in rows] == ['新活动']          # 旧行不再保留
    assert '身份' in rows[0] and '阶段序号' in rows[0]       # 已是新格式
    assert diff.原有条数 == 0                              # 重建不看旧文件


def test_日常刷新仍拒绝旧六列(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    path.write_text(旧六列, encoding='utf-8')
    with pytest.raises(store.身份冲突, match='旧格式'):
        store.合并保存CSV([行('新活动', 身份='new-1')], path, '2026-10-31 12:00:00')
    assert path.read_text(encoding='utf-8') == 旧六列


def test_重建只落有效期内的条目(tmp_path, 内核模块):
    """回溯扫描会带出早就结束的活动；它们不能落盘——否则下一次日常刷新会把它们

    当成待清理存量，触发 50% 清理保护（2026-10-31 宿主实测：177 条里 146 条过期）。
    长期/复刻这类仍在有效期内的条目不受影响。
    """
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    store.合并保存CSV([
        行('很早就结束', '2026-01-01 12:00:00', '2026-01-05 03:59:00', 身份='old-1'),
        行('刚结束仍在保留期', '2026-10-28 12:00:00', '2026-10-29 03:59:00', 身份='recent-1'),
        行('当前活动', 身份='now-1'),
    ], path, '2026-10-31 12:00:00', 重建=True)
    assert {r['名称'] for r in 读(path)} == {'刚结束仍在保留期', '当前活动'}


def test_重建后日常刷新不会触发大幅清理(tmp_path, 内核模块):
    """重建出来的存量必须能直接接住下一次日常刷新（不许一刷新就报 82% 清理）。"""
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    store.合并保存CSV([行('当前活动', 身份='now-1')], path, '2026-10-31 12:00:00', 重建=True)
    # 日常刷新：同样的输入，应视为"无变化"而不是"要清掉一大半"
    store.合并保存CSV([行('当前活动', 身份='now-1')], path, '2026-10-31 12:00:00')
    assert [r['名称'] for r in 读(path)] == ['当前活动']


def test_重建失败不动原文件(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / '活动.csv'
    path.write_text(旧六列, encoding='utf-8')
    原样 = path.read_bytes()
    with pytest.raises(store.身份冲突):
        # 类型 1 的普通行没有运行时身份 → 校验失败；失败必须不改原文件
        store.合并保存CSV([行('无身份普通行')], path, '2026-10-31 12:00:00', 重建=True)
    assert path.read_bytes() == 原样


def test_初始化与日常刷新的写回参数不同(内核模块):
    """接线检查：`更新数据(回溯已结束=True)` 必须把重建传递到存储层。"""
    import inspect
    源 = inspect.getsource(内核模块('流水线').更新数据)
    assert '重建=回溯已结束' in 源
