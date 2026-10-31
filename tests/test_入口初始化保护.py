"""CLI / AstrBot 初始化同走安全刷新，不在入口预删用户数据。"""
import ast
from datetime import datetime
from pathlib import Path

import pytest


@pytest.mark.parametrize('失败方式', ['网络', '身份'])
def test_插件初始化失败保留CSV与日差(tmp_path, 插件模块, 内核模块, monkeypatch, 失败方式):
    plugin = 插件模块('渲染')
    pipeline = 内核模块('流水线')
    settings = 内核模块('config').Settings(数据目录=tmp_path)
    csv_path = Path(settings.all_data_path)
    daily = tmp_path / '最近数据变化.json'
    csv_path.write_bytes(b'original csv')
    daily.write_bytes(b'original daily')
    monkeypatch.setattr(pipeline.settings, 'all_data_path', str(csv_path))
    monkeypatch.setattr(pipeline.settings, '数据目录', tmp_path)
    calls = []
    if 失败方式 == '网络':
        def fetch(*args):
            raise OSError('模拟网络失败')
        monkeypatch.setattr(pipeline, '获取事件列表', fetch)
    else:
        monkeypatch.setattr(pipeline, '获取事件列表', lambda *args: ['模拟API'])
        batch = 内核模块('公告身份').公告条目批次([], ('模拟认领争议',))
        monkeypatch.setattr(pipeline, 'API转活动列表', lambda *args, **kwargs: batch)
    def update(now, *, 回溯已结束):
        calls.append(回溯已结束)
        return pipeline.更新数据(now, 回溯已结束=回溯已结束)
    monkeypatch.setattr(plugin, '更新数据', update)
    monkeypatch.setattr(plugin, '更新增预告', lambda *args: None)
    service = plugin.渲染服务(插件目录=tmp_path, 数据目录=tmp_path)
    service._刷新数据(datetime(2026, 10, 30, 17), '2026-10-30 17:00:00', settings,
                      强制=True, 回溯已结束=True)
    assert calls == [True]
    assert csv_path.read_bytes() == b'original csv'
    assert daily.read_bytes() == b'original daily'
    assert not hasattr(service, '重建数据')


def test_插件命令初始化只委托刷新流程():
    # 宿主不可在离线测试里导入；直接检查真实命令函数的 AST，防止预删除调用回归。
    root = Path(__file__).parents[1]
    tree = ast.parse((root / 'main.py').read_text(encoding='utf-8'))
    command = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == '方舟日程')
    branch = next(n for n in ast.walk(command)
                  if isinstance(n, ast.If) and ast.unparse(n.test) == "子 == '刷新'")
    assert len(branch.orelse) == 1
    loop = branch.orelse[0]
    assert isinstance(loop, ast.AsyncFor)
    assert ast.unparse(loop.iter) == 'self._刷新流程(event, 运行配置, 回溯已结束=True)'
