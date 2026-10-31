from datetime import datetime
from pathlib import Path


def test_背景按日期顺序轮换(tmp_path, 插件模块):
    """背景目录配置后，连续日期应按排序后的图片逐张轮换。"""
    模块 = 插件模块("渲染")
    for name in ("a.png", "b.png", "c.png"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "说明.txt").write_text("不是图片", encoding="utf-8")

    设置 = type("设置", (), {"bg_dir": str(tmp_path)})()
    配置 = type("配置", (), {"指定背景": ""})()
    选 = 模块.渲染服务._背景路径
    结果 = [Path(选(配置, 设置, datetime(1970, 1, day))).name for day in (1, 2, 3, 4)]
    assert 结果 == ["a.png", "b.png", "c.png", "a.png"]


def test_背景同日稳定(tmp_path, 插件模块):
    模块 = 插件模块("渲染")
    (tmp_path / "a.png").write_bytes(b"x")
    设置 = type("设置", (), {"bg_dir": str(tmp_path)})()
    配置 = type("配置", (), {"指定背景": ""})()
    选 = 模块.渲染服务._背景路径
    assert 选(配置, 设置, datetime(2024, 1, 2)) == 选(配置, 设置, datetime(2024, 1, 2))
