from datetime import datetime
import pytest


@pytest.mark.parametrize('方式', ['合并', '身份存储'])
def test_坏编码拒写并保留字节(tmp_path, 内核模块, 方式):
    path = tmp_path / '活动.csv'
    original = b'\xff\xfe\xffinvalid'
    path.write_bytes(original)
    good = dict(名称='正常活动', 类型=1, 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-22 03:59:00', _运行时身份='normal')
    if 方式 == '合并':
        mod = 内核模块('汇总_活动')
        with pytest.raises(mod.身份冲突, match='编码'):
            mod.合并保存CSV([good], path, '2026-10-30 18:00:00')
    else:
        mod = 内核模块('身份CSV存储')
        with pytest.raises(mod.身份存储冲突, match='编码'):
            mod.保存身份CSV([good], path, '2026-10-30 18:00:00')
    assert path.read_bytes() == original


def test_坏编码更新记录失败提示(tmp_path, 内核模块, monkeypatch):
    pipeline = 内核模块('流水线')
    cls = 内核模块('公告身份').公告条目批次
    path = tmp_path / '活动.csv'
    path.write_bytes(b'\xffinvalid')
    good = dict(名称='正常活动', 类型=1, 开始时间='2026-11-01 12:00:00', 结束时间='2026-11-22 03:59:00', _运行时身份='normal')
    monkeypatch.setattr(pipeline.settings, 'all_data_path', str(path))
    monkeypatch.setattr(pipeline.settings, '数据目录', tmp_path)
    monkeypatch.setattr(pipeline, '获取事件列表', lambda *args: ['mock'])
    monkeypatch.setattr(pipeline, 'API转活动列表', lambda *args, **kwargs: cls([good]))
    monkeypatch.setattr(内核模块('解析_卡池'), '抓取卡池一览', lambda: [])
    pipeline.更新数据('2026-10-30 18:00:00')
    warning = 内核模块('更新状态').读取更新提示(tmp_path)
    assert '更新失败' in warning and '编码' in warning
    assert path.read_bytes() == b'\xffinvalid'
