"""配置契约：`_conf_schema.json` ↔ 代码默认值/夹取范围 ↔ README 字段说明。

这是 §6 列的"测试 2 + 测试 5"：**配置即契约**。三份东西必须同一口径——
- schema 的默认值 == `运行配置` 的默认值；
- schema 的 minimum/maximum == `插件/配置.py` 的夹取范围；
- README 的「配置项」一节里能查到**每一个**字段（照 palette 的
  `test_settings_static.py` 思路：不 import astrbot，纯 stdlib 读文件比对）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

仓库根 = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads((仓库根 / "_conf_schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def 默认(插件模块):
    return 插件模块("配置").运行配置()


@pytest.fixture(scope="module")
def 范围(插件模块):
    return 插件模块("配置").范围


@pytest.fixture(scope="module")
def 字段映射(插件模块) -> dict[tuple[str, str], tuple[str, str]]:
    """`(节, schema 键) → (运行配置 字段名, 取值方式)`：配置契约的单一来源。"""
    return 插件模块("配置").字段映射


def _字段们(schema: dict) -> dict[tuple[str, str], dict]:
    return {(节, 键): 项 for 节, 节项 in schema.items() for 键, 项 in 节项["items"].items()}


def test_schema_形状(schema):
    """每个节都是 object + items，字段都有 description 与非空 type。"""
    必备类型 = {"int", "float", "bool", "string", "text", "list", "file", "object",
              "template_list", "dict"}
    for 节, 节项 in schema.items():
        assert 节项["type"] == "object", 节
        assert isinstance(节项.get("items"), dict) and 节项["items"], 节
        for 键, 项 in 节项["items"].items():
            assert 项.get("type") in 必备类型, f"{节}.{键}"
            assert 项.get("description"), f"{节}.{键} 缺 description"
            assert "default" in 项, f"{节}.{键} 缺 default"


def test_字段映射覆盖全部_schema_字段(schema, 字段映射):
    assert set(字段映射) == set(_字段们(schema)), "schema 与 插件/配置.py 的字段映射对不上"
    assert len(字段映射) == sum(len(v["items"]) for v in schema.values())


def test_schema_默认值等于代码默认值(schema, 默认, 字段映射):
    不符 = []
    for (节, 键), (字段, _类型) in 字段映射.items():
        代码值 = getattr(默认, 字段)
        if isinstance(代码值, tuple):      # schema 里 list 是 JSON 数组，代码里是 tuple
            代码值 = list(代码值)
        if schema[节]["items"][键]["default"] != 代码值:
            不符.append(f"{节}.{键}: schema={schema[节]['items'][键]['default']!r} 代码={代码值!r}")
    assert not 不符, 不符


def test_schema_数值范围等于代码夹取范围(schema, 范围, 字段映射):
    for (节, 键), (_字段, _类型) in 字段映射.items():
        项 = schema[节]["items"][键]
        if 键 in 范围:
            assert (项.get("minimum"), 项.get("maximum")) == 范围[键], f"{节}.{键}"
        else:
            assert "minimum" not in 项 and "maximum" not in 项, f"{节}.{键} 有范围但代码没夹取"


def test_README_记录了每个配置字段(schema, 字段映射):
    """README 的「配置项」一节必须能查到每个字段（文档即契约）。"""
    readme = (仓库根 / "README.md").read_text(encoding="utf-8")
    assert "## 配置项" in readme, "README 里没有「配置项」一节"
    缺 = [f"{节}.{键}" for 节, 键 in 字段映射 if f"`{节}.{键}`" not in readme]
    assert not 缺, f"README 未记录：{缺}"


def test_越界与坏值都被夹住(插件模块):
    读 = 插件模块("配置")
    配置 = 读.读取配置({
        "render": {"title": "  ", "left_offset_days": -5, "right_offset_days": 999,
                   "remind_days": True, "background_dir": 123},
        "data": {"auto_refresh_daily": "false"},
        "push": {"enabled": "yes", "time": "25:99", "targets": "a\nb"},
    })
    assert 配置.左边界天数 == 0 and 配置.右边界天数 == 30 and 配置.提醒天数 == 3
    assert 配置.标题 == "近期活动一览" and 配置.背景目录 == ""
    assert 配置.每日自动更新 is False
    assert 配置.推送开关 is True and 配置.推送时刻 == "08:00"     # 坏时刻退回默认
    assert 配置.推送目标 == ("a", "b")


def test_时刻规范化(插件模块):
    规范化 = 插件模块("配置").规范化时刻
    assert 规范化("8:5") == "08:05"
    assert 规范化(" 23:59 ") == "23:59"
    assert 规范化("24:00") == "08:00"
    assert 规范化("abc") == "08:00"
    assert 规范化(None) == "08:00"
