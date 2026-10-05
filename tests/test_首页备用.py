"""备用取法：数据子页解析 + 本地图标 URL 构造。

样本取自 2026-09-28 线上实测（「首页/亮点干员/新增皮肤(模组)/数据」的真实内容，
图标 URL 与首页 HTML 里 id=charicon 的实际引用逐字对过账）。
"""

from __future__ import annotations

from urllib.parse import unquote

from src.解析_首页 import 构造图标URL, 解析数据子页


def test_构造图标URL_与首页实际引用一致():
    # 三个样本 = 首页 HTML 实际引用的 src 去掉 ?v= 缓存参数
    assert 构造图标URL("头像_录武官_skin1.png") == \
        "https://media.prts.wiki/4/4f/%E5%A4%B4%E5%83%8F_%E5%BD%95%E6%AD%A6%E5%AE%98_skin1.png"
    assert 构造图标URL("头像_结城理_2.png") == \
        "https://media.prts.wiki/b/bf/%E5%A4%B4%E5%83%8F_%E7%BB%93%E5%9F%8E%E7%90%86_2.png"
    assert 构造图标URL("头像_涤火杰西卡.png") == \
        "https://media.prts.wiki/1/14/%E5%A4%B4%E5%83%8F_%E6%B6%A4%E7%81%AB%E6%9D%B0%E8%A5%BF%E5%8D%A1.png"


def test_构造图标URL_回读一致():
    for 名 in ("头像_空构_skin1.png", "头像_仇白_2.png", "头像_梅尔.png"):
        assert unquote(构造图标URL(名)).endswith(名)


def test_解析数据子页():
    结果 = 解析数据子页(
        "1=空构:skin=1,1=承曦格雷伊:skin=3",
        "1=结城理:2=PUM-Y:3=彼此的声音,1=埃癸斯:2=BRK-X:3=约定的证明",
    )
    assert [条目["干员"] for 条目 in 结果["时装"]] == ["空构", "承曦格雷伊"]
    assert 结果["时装"][0]["图标文件名"] == "时装_空构.png"
    assert 结果["时装"][0]["名称"] == ""
    assert [条目["干员"] for 条目 in 结果["模组"]] == ["结城理", "埃癸斯"]
    assert 结果["模组"][1]["名称"] == "约定的证明"
    assert 结果["模组"][1]["图标文件名"] == "模组_埃癸斯_约定的证明.png"
    # 模组图标与 wiki 模板同款：头像_{干员}_2.png（模板硬编码）
    assert unquote(结果["模组"][0]["图标"]).endswith("头像_结城理_2.png")
    assert 结果["凭证"] == []


def test_解析数据子页_空页仍保三键():
    结果 = 解析数据子页("", "")
    assert 结果 == {"时装": [], "模组": [], "凭证": []}
