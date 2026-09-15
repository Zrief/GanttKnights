"""每日推送：推送目标（配置项 `push.targets`）+ 幂等记账 + 调度判据。

推送目标是**配置项**而不是状态文件——这样用户能在 AstrBot 设置页里直接删掉某个群的推送。
"""

from __future__ import annotations

import asyncio
import json
import types
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("apscheduler", reason="调度器断言需要 apscheduler（requirements.txt 里有）")

今天 = datetime.now().date().isoformat()


@pytest.fixture
def 推送(插件模块):
    return 插件模块("推送")


@pytest.fixture
def 配置模块(插件模块):
    return 插件模块("配置")


# ---------- 推送目标：来自配置 ----------

def test_读取文本列表的三种形态(配置模块):
    读 = 配置模块.读取文本列表
    assert 读(["a", "b"]) == ("a", "b")
    assert 读(["b", "", "a", "b"]) == ("b", "a")          # 去空、去重、保序
    assert 读("a\nb,c，d") == ("a", "b", "c", "d")        # 手改成一个字符串也能读
    assert 读(5) == () and 读(None) == () and 读(["", 7]) == ()


def test_读取配置三件套(配置模块):
    配置 = 配置模块.读取配置({"push": {"enabled": True, "time": "8:5", "targets": ["甲"]}})
    assert 配置.推送开关 is True and 配置.推送时刻 == "08:05" and 配置.推送目标 == ("甲",)


# ---------- 幂等记账 ----------

def test_记账与_上次结果(tmp_path, 推送):
    状态 = 推送.推送状态(tmp_path / "s.json")
    assert 状态.该推吗("甲", 今天) is True
    状态.记成功("甲", 今天, ("甲", "乙"))
    assert 状态.该推吗("甲", 今天) is False
    assert 状态.该推吗("甲", "2099-01-01") is True
    assert 状态.今天推过吗(今天, ("甲",)) is True
    assert 状态.今天推过吗(今天, ("甲", "乙")) is False
    状态.记成功("甲", 今天, ("甲", "乙"))
    状态.记成功("乙", 今天, ("甲", "乙"))
    状态.记成功("丙", 今天, ("甲", "乙"))        # 丙 已从目标里删掉
    assert set(状态.读()["已推"]) == {"甲", "乙"}
    状态.记失败("出图失败")
    assert 状态.上次()["失败"] == 1 and 状态.上次()["说明"] == "出图失败"
    状态.记结果(2, 0)
    assert 状态.上次()["成功"] == 2 and 状态.上次()["失败"] == 0


def test_状态文件容错(tmp_path, 推送):
    路径 = tmp_path / "s.json"
    路径.write_text("{ 坏 json", encoding="utf-8")
    状态 = 推送.推送状态(路径)
    assert 状态.读() == {} and 状态.该推吗("a", 今天) is True
    路径.write_text("[]", encoding="utf-8")
    assert 状态.读() == {}
    路径.write_text(json.dumps({"已推": 5, "上次": "坏"}), encoding="utf-8")
    assert 状态.该推吗("a", 今天) is True and 状态.上次() == {}
    状态.记成功("a", 今天, ("a",))
    assert 状态.该推吗("a", 今天) is False
    assert not list(tmp_path.glob(".push-*.tmp"))


# ---------- 调度与投递 ----------

class 假渲染:
    def __init__(self, 产物: Path) -> None:
        self.调用 = 0
        self.产物 = 产物
        产物.write_bytes(b"\xff\xd8\xff" + b"J" * 100)

    async def 出图(self, **kwargs):
        self.调用 += 1
        return types.SimpleNamespace(图片路径=self.产物, 提醒="⚠️ 明天结束\n📅 甲",
                                     变化="较 09-14：🆕 乙", 有提醒=True)

    @staticmethod
    def 产物可用(路径) -> bool:
        return Path(路径).exists()


def test_目标为空不武装_有目标才武装(tmp_path, 推送, 配置模块):
    渲染 = 假渲染(tmp_path / "图.jpg")
    发送: list[str] = []
    文本们: list[str] = []

    async def 假发送(umo, 文本, 图片路径):
        发送.append(umo)
        文本们.append(文本)
        return umo != "坏的"          # 让一个目标投递失败，验证"只记成功 → 下次重试"

    服务 = 推送.推送服务(渲染=渲染, 状态=推送.推送状态(tmp_path / "s.json"),
                        发送=假发送, 配置读取=lambda: 配置模块.运行配置())

    async def 跑():
        空 = 配置模块.运行配置(推送开关=True, 推送目标=())
        assert "推送目标列表" in 服务.确保任务(空) and 服务._调度器 is None

        有 = 配置模块.运行配置(推送开关=True, 推送时刻="08:00", 推送目标=("甲", "乙"))
        提示 = 服务.确保任务(有)
        assert 服务._调度器 is not None and "08:00" in 提示
        job = 服务._调度器.get_job(推送.任务ID)
        assert job.coalesce is True and job.max_instances == 1
        assert job.misfire_grace_time == 推送.宽限秒       # 库默认只有 1 秒，必须显式写
        assert len(服务._调度器.get_jobs()) == 1
        assert 服务.确保任务(有) and len(服务._调度器.get_jobs()) == 1

        assert "未开启" in 服务.确保任务(配置模块.运行配置(推送开关=False))
        assert 服务._调度器 is None

        # 投递：渲染一次、每个目标一条、幂等、失败只影响那一个
        有坏 = 配置模块.运行配置(推送开关=True, 推送时刻="08:00",
                                推送目标=("甲", "乙", "坏的"))
        服务.确保任务(有坏)
        结果 = await 服务.推一次(运行配置=有坏)
        assert 渲染.调用 == 1 and 发送 == ["甲", "乙", "坏的"]
        assert 文本们 == ["⚠️ 明天结束\n📅 甲"] * 3     # 文字只来自渲染结果的"提醒"
        assert 服务.状态.该推吗("甲", 今天) is False
        assert 服务.状态.该推吗("坏的", 今天) is True      # 只记成功 → 下次会重试
        await 服务.推一次(运行配置=有坏)
        assert 发送 == ["甲", "乙", "坏的", "坏的"]        # 成功的绝不重发
        await 服务.停()
        assert 服务._调度器 is None

    asyncio.run(跑())
