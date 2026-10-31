"""正式保存入口格式分流的隔离验证。"""
import csv
from datetime import datetime
from pathlib import Path
import pytest


def test_初始化网络失败保留CSV与日差(tmp_path, 内核模块, monkeypatch):
    pipeline = 内核模块('流水线')
    path = tmp_path / 'old.csv'
    daily = tmp_path / '最近数据变化.json'
    path.write_text('原CSV', encoding='utf-8')
    daily.write_text('原日差', encoding='utf-8')
    monkeypatch.setattr(pipeline.settings, 'all_data_path', str(path))
    monkeypatch.setattr(pipeline.settings, '数据目录', tmp_path)
    def fail(*args, **kwargs):
        raise OSError('离线模拟')
    monkeypatch.setattr(pipeline, '获取事件列表', fail)
    assert pipeline.更新数据('2026-11-01 12:00:00', 回溯已结束=True) is None
    assert path.read_text(encoding='utf-8') == '原CSV'
    assert daily.read_text(encoding='utf-8') == '原日差'


def test_旧格式遇来源身份拒绝自动迁移(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    path = tmp_path / 'old.csv'
    original = '名称,开始时间,结束时间,类型,子类型,来源\n旧总览,2026-11-01 12:00:00,2026-11-22 03:59:00,1,,父\n'
    path.write_text(original, encoding='utf-8')
    new = dict(名称='阶段', 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-22 03:59:00', 类型=1, _运行时身份='source-stage')
    with pytest.raises(store.身份冲突, match='旧格式'):
        store.合并保存CSV([new], path, '2026-11-01 12:00:00')
    assert path.read_text(encoding='utf-8') == original


def test_修正后快照走正式入口仅改阶段显示名日期(tmp_path, 内核模块):
    store = 内核模块('汇总_活动')
    sample = Path(__file__).parents[1] / 'tests' / 'fixtures' / '身份快照_19行.csv'
    path = tmp_path / 'new.csv'
    path.write_bytes(sample.read_bytes())
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    stage = next(r for r in rows if r['名称'].endswith('·一阶段'))
    update = dict(名称='SideStory「时间啊，向前！」·调整阶段', 开始时间=stage['开始时间'],
                  结束时间='2026-11-23 03:59:00', 类型=1, _parent=stage['来源'], _运行时身份=stage['身份'])
    diff = store.合并保存CSV([update], path, '2026-11-01 12:00:00')
    with path.open(encoding='utf-8-sig', newline='') as f:
        current = list(csv.DictReader(f))
    assert len(current) == 19
    assert diff.新增 == () and diff.改动 == (update['名称'],)
    assert next(r for r in current if r['身份'] == stage['身份'])['名称'] == update['名称']
    assert not any(r['名称'] == stage['名称'] for r in current)
