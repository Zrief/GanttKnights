"""显式阶段元数据、节点合并与凌晨截止；不联网、不解析名字猜阶段。"""
from __future__ import annotations

import csv
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def 工具(内核模块):
    类 = 内核模块("活动").活动

    def 造(序=1, *, 关联="来源块:A", 本名="SideStory「测试」", 角色="关卡开放",
           开始="2026-11-01 16:00", 结束="2026-11-22 03:59", 名称=None):
        return 类(名称 or f"{本名}·{序}阶段", datetime.fromisoformat(开始),
                  datetime.fromisoformat(结束), 1, 活动关联=关联, 活动本名=本名,
                  时间角色=角色, 阶段序号=序)

    return SimpleNamespace(类=类, 造=造, 提醒=内核模块("生成_提醒").生成提醒,
                           读CSV=内核模块("筛选_活动")._读CSV,
                           说明=内核模块("提醒文案").结束说明)


def test_模型旧构造默认值且保持冻结slots(工具):
    e = 工具.类("旧活动", datetime(2026, 11, 1), datetime(2026, 11, 22), 1)
    assert (e.活动关联, e.活动本名, e.时间角色, e.阶段序号) == ("", "", "", 0)
    assert not hasattr(e, "__dict__")
    with pytest.raises(FrozenInstanceError):
        e.阶段序号 = 1


@pytest.mark.parametrize("列数", [6, 8, 12])
def test_CSV六八十二列兼容及坏序号(工具, tmp_path, 列数):
    头 = ["名称", "开始时间", "结束时间", "类型", "子类型", "来源",
          "身份键", "身份强度", "活动关联", "活动本名", "时间角色", "阶段序号"][:列数]
    路径 = tmp_path / "阶段.csv"
    基本 = dict(名称="活动", 开始时间="2026-11-01 16:00", 结束时间="2026-11-22 03:59",
                类型="1", 子类型="", 来源="公告", 身份键="key", 身份强度="强",
                活动关联="来源块:A", 活动本名="SideStory「测试」", 时间角色="关卡开放", 阶段序号="2")
    with 路径.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=头, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(基本)
        if 列数 == 12:
            writer.writerow(基本 | {"名称": "默认序号", "阶段序号": ""})
            for 坏序号 in ("第二", "1.5", "-1"):
                writer.writerow(基本 | {"阶段序号": 坏序号})
    记录, 坏行 = 工具.读CSV(路径)
    if 列数 < 12:
        assert len(记录) == 1 and 坏行 == 0
        assert (记录[0].活动关联, 记录[0].活动本名, 记录[0].时间角色, 记录[0].阶段序号) == ("", "", "", 0)
    else:
        assert len(记录) == 2 and 坏行 == 3
        assert (记录[0].活动关联, 记录[0].活动本名, 记录[0].时间角色, 记录[0].阶段序号) == (
            "来源块:A", "SideStory「测试」", "关卡开放", 2)
        assert 记录[1].阶段序号 == 0


def test_一二三阶段共同结束并在三天节点标明精确时刻(工具):
    记录 = [工具.造(i, 开始=f"2026-11-{i:02} 16:00") for i in (3, 1, 2)]
    assert 工具.提醒(记录, datetime(2026, 11, 19)) == (
        "3 天后结束\n📅 SideStory「测试」·活动关卡共同结束 (11-22 03:59结束)")
    assert [e.阶段序号 for e in 记录] == [3, 1, 2], "不修改原记录"


def test_开始分别提醒并按显式序号不按中文标签(工具):
    记录 = [工具.造(3, 名称="A三"), 工具.造(2, 名称="B二"), 工具.造(1, 名称="Z一")]
    assert 工具.提醒(记录, datetime(2026, 11, 1)) == "🔥 今天开启\n📅 Z一\n📅 B二\n📅 A三"


def test_跨关联即使本名相同也不合并(工具):
    记录 = [工具.造(1, 关联="块:A"), 工具.造(2, 关联="块:B")]
    文案 = 工具.提醒(记录, datetime(2026, 11, 19))
    assert len(文案.splitlines()) == 3 and "共同结束" not in 文案


def test_同日但精确结束时刻不同不合并(工具):
    记录 = [工具.造(1), 工具.造(2, 结束="2026-11-22 04:00")]
    文案 = 工具.提醒(记录, datetime(2026, 11, 19))
    assert len(文案.splitlines()) == 3 and "共同结束" not in 文案


def test_总窗不同窗口独立保留不改名(工具):
    记录 = [工具.造(1), 工具.造(2),
            工具.造(0, 角色="活动总窗", 结束="2026-11-22 23:59", 名称="SideStory「测试」")]
    assert 工具.提醒(记录, datetime(2026, 11, 19)).splitlines() == [
        "3 天后结束", "📅 SideStory「测试」·活动关卡共同结束 (11-22 03:59结束)", "📅 SideStory「测试」"]
    # 总窗即使碰巧和关卡同一结束也不是关卡组成员。
    记录[-1] = replace(记录[-1], 结束=记录[0].结束)
    文案 = 工具.提醒(记录, datetime(2026, 11, 19))
    assert len(文案.splitlines()) == 3 and 文案.count("共同结束") == 1


def test_流程预选招募不合并(工具):
    记录 = [工具.造(2, 角色="流程阶段", 名称="活动·招募"),
            工具.造(1, 角色="流程阶段", 名称="活动·预选")]
    文案 = 工具.提醒(记录, datetime(2026, 11, 19))
    assert "共同结束" not in 文案 and len(文案.splitlines()) == 3
    assert 工具.提醒(记录, datetime(2026, 11, 1)) == "🔥 今天开启\n📅 活动·预选\n📅 活动·招募"


def test_缺元数据绝不凭名字猜且单阶段不称共同(工具):
    记录 = [工具.造(1, 关联="", 本名="", 角色=""), 工具.造(2, 关联="", 本名="", 角色="")]
    文案 = 工具.提醒(记录, datetime(2026, 11, 19))
    assert "共同结束" not in 文案 and len(文案.splitlines()) == 3
    assert "共同结束" not in 工具.提醒([工具.造()], datetime(2026, 11, 19))
    for 字段 in ("活动关联", "活动本名", "时间角色"):
        记录 = [replace(工具.造(i), **{字段: ""}) for i in (1, 2)]
        assert "共同结束" not in 工具.提醒(记录, datetime(2026, 11, 19))


def test_无显式关联开始保持旧名字排序(工具):
    记录 = [工具.造(1, 关联="", 名称="Z一"), 工具.造(2, 关联="", 名称="A二")]
    assert 工具.提醒(记录, datetime(2026, 11, 1)) == "🔥 今天开启\n📅 A二\n📅 Z一"


def test_凌晨最后完整日保留明天组头及原日偏移(工具):
    记录 = [工具.造(1), 工具.造(2)]
    assert 工具.提醒(记录, datetime(2026, 11, 21, 23, 50)) == (
        "⚠️ 明天结束\n📅 SideStory「测试」·活动关卡共同结束 (明天03:59结束；今天是最后完整游玩日)")
    assert 工具.提醒(记录, datetime(2026, 11, 20)) == ""
    assert 工具.提醒(记录, datetime(2026, 11, 22, 1)) == ""
    assert "最后完整游玩日" not in 工具.提醒(记录, datetime(2026, 11, 22, 1), 结束偏移们=(0,))


def test_凌晨阈值严格小于四点且非凌晨旧文案不变(工具):
    for 时刻 in ("00:00", "03:59"):
        e = 工具.造(结束=f"2026-11-22 {时刻}")
        assert f"明天{时刻}结束；今天是最后完整游玩日" in 工具.提醒([e], datetime(2026, 11, 21))
    for 时刻 in ("04:00", "16:00", "23:59"):
        e = 工具.造(结束=f"2026-11-22 {时刻}", 名称="普通活动", 关联="", 本名="", 角色="")
        assert 工具.提醒([e], datetime(2026, 11, 21)) == "⚠️ 明天结束\n📅 普通活动"


def test_不补兑换或无节点日常消息(工具):
    记录 = [工具.造(1), 工具.造(2)]
    assert 工具.提醒(记录, datetime(2026, 11, 10)) == ""
    文案 = 工具.提醒(记录, datetime(2026, 11, 19))
    assert "兑换" not in 文案 and "商店" not in 文案


def test_限行计算合并后节点数且结束按精确时刻排序(工具):
    记录 = [工具.造(i) for i in (1, 2, 3)]
    记录 += [工具.造(i, 关联="", 本名="", 角色="", 名称=f"普通{i:02}",
                      结束="2026-11-22 16:00") for i in range(11)]
    行 = 工具.提醒(记录, datetime(2026, 11, 19)).splitlines()
    assert len(行) == 12 and 行[-1] == "…另有 2 项"
    assert "共同结束" in 行[1] and 行[2] == "📅 普通00"
