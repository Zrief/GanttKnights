"""配置契约：`_conf_schema.json` ↔ 代码默认值/夹取范围。

这是 「测试与验证」 列的"测试 2 + 测试 5"：**配置即契约**。两边必须同一口径——
- schema 的默认值 == `运行配置` 的默认值；
- schema 的 minimum/maximum == `插件/配置.py` 的夹取范围。

（曾是三边契约，含"README 配置项表记录每个字段"一腿；2026-09-24 删掉——
设置页每项自带 description（`test_schema_形状` 保证），README 重复一份只是维护负担。）
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


def test_越界与坏值都被夹住(插件模块):
    读 = 插件模块("配置")
    配置 = 读.读取配置({
        "render": {"title": "  ", "left_offset_days": -5, "right_offset_days": 999,
                   "background_dir": 123},
        "data": {"auto_refresh_daily": "false"},
        "notify": {"end_offsets": ["−3", " -1 ", "abc", 0, 5, -1], "start_offsets": "-1，0"},
        "push": {"enabled": "yes", "time": "25:99", "targets": "a\nb"},
    })
    assert 配置.左边界天数 == 0 and 配置.右边界天数 == 30
    assert 配置.标题 == "近期活动一览" and 配置.背景目录 == ""
    assert 配置.每日自动更新 is False
    # 整数列表：全角负号/空格能读、坏值丢弃、正数丢弃、去重、由大到小
    assert 配置.结束偏移们 == (0, -1, -3)
    assert 配置.开始偏移们 == (0, -1)
    assert 配置.推送开关 is True and 配置.推送时刻 == "08:00"     # 坏时刻退回默认
    assert 配置.推送目标 == ("a", "b")


def test_通知三层开关(插件模块):
    """总开关 > 单类开关 > 空数组：任一条成立就返回空元组（= 这类不提醒）。"""
    运行配置 = 插件模块("配置").运行配置
    默认 = 运行配置()
    assert 默认.有效结束偏移们() == (-3, -1) and 默认.有效开始偏移们() == (0,)
    assert 运行配置(通知开关=False).有效结束偏移们() == ()
    assert 运行配置(通知开关=False).有效开始偏移们() == ()
    assert 运行配置(结束提醒开关=False).有效结束偏移们() == ()
    assert 运行配置(结束提醒开关=False).有效开始偏移们() == (0,)   # 只关一类，不影响另一类
    assert 运行配置(结束偏移们=()).有效结束偏移们() == ()


def test_整数列表的容错(插件模块):
    读 = 插件模块("配置").读取整数列表
    assert 读(["-3", "-1"]) == (-1, -3)
    assert 读([-3, -1]) == (-1, -3)                 # 手写成数字也能读
    assert 读("-3\n-1") == (-1, -3) and 读("-3，-1") == (-1, -3)
    assert 读(["−3"]) == (-3,)                      # 全角负号
    assert 读(["abc", "", None, True, "-31", "5"]) == ()   # 坏值/越界/正数都丢
    assert 读(5) == () and 读(None) == ()


def test_时刻规范化(插件模块):
    规范化 = 插件模块("配置").规范化时刻
    assert 规范化("8:5") == "08:05"
    assert 规范化(" 23:59 ") == "23:59"
    assert 规范化("24:00") == "08:00"
    assert 规范化("abc") == "08:00"
    assert 规范化(None) == "08:00"
