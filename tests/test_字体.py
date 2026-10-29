"""字体注册：三层候选全落空时显式抛 `字体缺失`，不再静默画豆腐图。

2026-10 Docker issue：早期官方镜像（2026-08-26 之前）没有中文字体，出图
中文全是方块且只有一行日志——现在改为抛异常，入口层把修法告诉用户。
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def 字体(内核模块):
    return 内核模块("字体")


def test_有字体时正常注册(字体):
    """本机（开发环境）至少有一支候选可命中，注册不抛、方案完整。"""
    方案 = 字体.注册字体(强制=True)
    assert 方案.无衬线族
    assert 方案.正文文件


def test_候选全落空时抛字体缺失(字体, monkeypatch):
    """三层候选全部解析不到（模拟无字体的精简容器）：抛 `字体缺失`
    而不是回退 sans-serif 画豆腐。"""
    monkeypatch.setattr(字体, "_挑族", lambda 候选, 字重="normal": None)
    with pytest.raises(字体.字体缺失, match="中文字体"):
        字体.注册字体(强制=True)


def test_插件侧字体缺失链路():
    """插件侧的转译类型与用户文案（2026-10-29 教训：插件文案的语法错误
    内核测试抓不到——tests 不 import 插件包，这里把链路 import 一遍钉住）。"""
    import gk.插件.文案 as 文案
    import gk.插件.渲染 as 渲染

    assert 渲染.字体缺失
    文 = 文案.说明字体缺失()
    assert "docker pull" in 文 and "font.ttf" in 文
