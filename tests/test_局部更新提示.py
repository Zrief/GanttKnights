"""局部隔离经共享流水线正常保存，并独立展示不完整更新提示。"""
import csv
from datetime import datetime
from types import SimpleNamespace


def test_部分批次经流水线保存正常条目(tmp_path, 内核模块, monkeypatch):
    pipeline = 内核模块('流水线')
    batch_type = 内核模块('公告身份').公告条目批次
    path = tmp_path / '活动.csv'
    monkeypatch.setattr(pipeline.settings, '数据目录', tmp_path)
    monkeypatch.setattr(pipeline.settings, 'all_data_path', str(path))
    good = dict(名称='正常活动', 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-22 03:59:00',
                类型=1, _运行时身份='good-source')
    batch = batch_type([good], 隔离来源=(('公告', '坏板块'),), 更新问题=('坏板块时间不完整',))
    monkeypatch.setattr(pipeline, '获取事件列表', lambda *a: ['api'])
    monkeypatch.setattr(pipeline, 'API转活动列表', lambda *a, **k: batch)
    monkeypatch.setattr(内核模块('解析_卡池'), '抓取卡池一览', lambda: [])
    pipeline.更新数据('2026-10-30 17:00:00', 回溯已结束=True)
    with path.open(encoding='utf-8-sig', newline='') as f:
        assert [r['名称'] for r in csv.DictReader(f)] == ['正常活动']
    warning = 内核模块('更新状态').读取更新提示(tmp_path)
    assert '部分活动未更新' in warning and '坏板块时间不完整' in warning


def test_更新状态成功清除上次警告(tmp_path, 内核模块):
    state = 内核模块('更新状态')
    state.记录更新状态(tmp_path, '2026-10-30 17:00:00', ('锁冲突',), 成功=False)
    assert '沿用可读取的旧数据' in state.读取更新提示(tmp_path)
    state.记录更新状态(tmp_path, '2026-10-30 18:00:00')
    assert state.读取更新提示(tmp_path) == ''


def test_空图或部分更新不使用正常无提醒回落(tmp_path, 内核模块, monkeypatch, capsys):
    pipeline = 内核模块('流水线')
    monkeypatch.setattr(pipeline.settings, '数据目录', tmp_path)
    monkeypatch.setattr(pipeline.settings, 'warning_path', str(tmp_path / '警告.txt'))
    monkeypatch.setattr(pipeline, 'preprocess_data', lambda **kwargs: [])
    monkeypatch.setattr(pipeline, '读取新增内容', lambda: {})
    monkeypatch.setattr(pipeline, '挑选背景图', lambda *a: 'dummy')
    monkeypatch.setattr(pipeline, '布置头像', lambda *a: None)
    drawing = 内核模块('绘图_排版')
    monkeypatch.setattr(drawing, '建分区', lambda *a: [])
    monkeypatch.setattr(drawing, '绘制甘特图', lambda *a, **k: '占位图')
    monkeypatch.setattr(内核模块('绘图_主题'), '建主题', lambda *a: None)
    内核模块('更新状态').记录更新状态(tmp_path, '2026-10-30 17:00:00', ('某板块被隔离',))
    result = pipeline.render_once(现在时间=datetime(2026, 10, 30, 17), 输出路径=tmp_path / '图.jpg')
    assert not result.有提醒
    assert '部分活动未更新' in result.更新提示
    assert '仅有底栏' in result.更新提示
    assert pipeline.无提醒文案 not in result.提醒
    assert '某板块被隔离' in capsys.readouterr().out
    assert '某板块被隔离' in (tmp_path / '警告.txt').read_text(encoding='utf-8')


def test_插件推送更新提示不冒充节点命中(插件模块):
    service = 插件模块('推送').推送服务
    result = SimpleNamespace(有提醒=False, 更新提示='部分活动未更新', 提醒='不应发送的回落')
    assert service._文案(result) == '部分活动未更新'
    result.有提醒 = True
    result.提醒 = '今天开启：正常活动'
    assert service._文案(result) == '部分活动未更新\n今天开启：正常活动'
