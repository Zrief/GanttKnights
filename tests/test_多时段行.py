"""多时段行（同一活动的一/二/三阶段＋商店、预选/招募）的排版契约。

2026-10-31 落地：一个活动只占一行——外框 + 名字槽（占槽不画条）+ 子阶段条；
子阶段一律竖切（斜切只留给长期合并行）；行高不再等长。
"""
from __future__ import annotations

from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pytest

from src.活动 import 活动
from src.甘特行 import 分行, 多时段组, 是多时段行
from src.绘图_排版 import (甘特行高px, 多时段行高px, 普通条高px, 填甘特区, 总高计算,
                          定图宽, 建分区画布, 行们行高, _确保字体就绪)

左 = datetime(2026, 10, 24)
右 = datetime(2026, 12, 3)
现在 = datetime(2026, 10, 30, 20, 0)
关联 = '["公告活动关联-v1","页","块"]'


def 阶段(名, 起, 止, 序号, 角色='关卡开放', 本名='SS「甲」', 关联值=关联):
    return 活动(名, datetime.fromisoformat(起), datetime.fromisoformat(止), 1,
              活动关联=关联值, 活动本名=本名, 时间角色=角色, 阶段序号=序号)


def 一组():
    return [
        阶段('SS「甲」·一阶段', '2026-11-01 12:00:00', '2026-11-22 03:59:00', 1),
        阶段('SS「甲」·二阶段', '2026-11-08 16:00:00', '2026-11-22 03:59:00', 2),
        阶段('SS「甲」·三阶段', '2026-11-15 16:00:00', '2026-11-22 03:59:00', 3),
        阶段('SS「甲」·商店', '2026-11-01 12:00:00', '2026-11-29 03:59:00', 0, '兑换开放'),
    ]


def test_同一活动关联并成一行():
    行们 = 分行(一组(), 左, 右)
    assert [len(行) for 行 in 行们] == [4]
    assert [t.时间角色 for t in 行们[0]] == ['关卡开放', '关卡开放', '关卡开放', '兑换开放']


def test_没有关联不多段并不猜分组():
    记录 = [阶段('甲一', '2026-11-01 12:00:00', '2026-11-22 03:59:00', 1, 关联值=''),
            阶段('甲二', '2026-11-08 16:00:00', '2026-11-22 03:59:00', 2, 关联值='')]
    行们 = 分行(记录, 左, 右)
    assert [len(行) for 行 in 行们] == [1, 1]
    assert 多时段组(记录) == {} and not 是多时段行(行们[0])


def test_关联相同但本名不同不并():
    记录 = [阶段('甲一', '2026-11-01 12:00:00', '2026-11-22 03:59:00', 1, 本名='甲'),
            阶段('乙一', '2026-11-08 16:00:00', '2026-11-22 03:59:00', 1, 本名='乙')]
    assert 多时段组(记录) == {}
    assert [len(行) for 行 in 分行(记录, 左, 右)] == [1, 1]


def test_多时段行更高且总高按累计():
    行们 = 分行(一组(), 左, 右)
    高度们 = 行们行高(行们)
    assert 高度们 == (多时段行高px,)
    assert 多时段行高px > 甘特行高px
    普通行 = 分行([活动('普通活动', datetime(2026, 11, 1), datetime(2026, 11, 9), 1)], 左, 右)
    assert 行们行高(普通行) == (甘特行高px,)
    _, 高 = 总高计算(2, 0, (多时段行高px, 甘特行高px))
    _, 等高 = 总高计算(2, 0)
    assert 高 - 等高 == 多时段行高px - 甘特行高px


def test_左列色轨覆盖整组所有行():
    """组色轨必须从首行行顶铺到末行行底；漏首行高度会让每组少一格（2026-10-31 修）。"""
    from src.绘图_主题 import 建主题
    from src.绘图_排版 import 甘特左列px, 组标签
    _确保字体就绪()
    记录 = [
        阶段('SS「甲」·一阶段', '2026-11-01 12:00:00', '2026-11-22 03:59:00', 1),
        阶段('SS「甲」·二阶段', '2026-11-08 16:00:00', '2026-11-22 03:59:00', 2),
        活动('普通活动', datetime(2026, 11, 2), datetime(2026, 11, 10), 1),
    ]
    行们 = 分行(list(reversed(记录)), 左, 右)
    高度们 = 行们行高(行们)
    assert len(行们) == 2 and len({组标签(行[0]) for 行 in 行们}) == 1, '两行应同属一个分组'
    主题 = 建主题(None)
    fig, gs, _, ax = 建分区画布(len(行们), 0, 主题, None, 1200, 高度们)
    try:
        填甘特区(ax, fig, 记录, 主题, 左, 右, 现在, 高度们, 行们)
        fig.canvas.draw()
        渲染器 = fig.canvas.get_renderer()
        组轨们 = [p.get_window_extent(渲染器) for p in ax.patches
                  if abs(p.get_window_extent(渲染器).width - 甘特左列px) < 0.5]
        assert len(组轨们) == 1, '一个分组只画一条组色轨'
        assert abs(组轨们[0].height - sum(高度们)) < 1.5, '色轨高度 = 组内各行高之和'
    finally:
        plt.close(fig)


def test_多时段行高落在自己那一行():
    """正序/倒序分行结果不同；若绘制时另分一次行，外框会落到别的行高里。

    不重算轴高：直接拿「左列色轨」当行高的基准（它就是按本行 y底/y顶 画的），
    核对多时段行的外框恰好落在**高 134px 那条色轨**里、上下各留 6px。
    """
    from src.绘图_主题 import 建主题
    from src.绘图_排版 import 多时段框高px
    _确保字体就绪()
    记录 = [
        阶段('SS「甲」·一阶段', '2026-11-01 12:00:00', '2026-11-22 03:59:00', 1),
        阶段('SS「甲」·二阶段', '2026-11-08 16:00:00', '2026-11-22 03:59:00', 2),
        活动('普通活动', datetime(2026, 11, 2), datetime(2026, 11, 10), 1),
    ]
    正序 = 分行(记录, 左, 右)
    倒序 = 分行(list(reversed(记录)), 左, 右)
    assert [len(行) for 行 in 正序] != [len(行) for 行 in 倒序], '顺序不同才会暴露错配'
    行们 = 倒序
    高度们 = 行们行高(行们)
    主题 = 建主题(None)
    fig, gs, _, ax = 建分区画布(len(行们), 0, 主题, None, 1200, 高度们)
    try:
        填甘特区(ax, fig, 记录, 主题, 左, 右, 现在, 高度们, 行们)
        fig.canvas.draw()
        渲染器 = fig.canvas.get_renderer()
        框们 = []
        轨们 = []
        for p in ax.patches:
            b = p.get_window_extent(渲染器)
            # 外框：主题更深色 75% 的圆角底（见 画多时段框）
            if abs((p.get_alpha() or 1) - 0.75) < 1e-6:
                框们.append(b)
            elif abs(b.width - 7) < 0.5:
                轨们.append(b)
        assert len(框们) == 1 and len(轨们) == len(行们)
        assert round(框们[0].height) == 多时段框高px
        高轨 = [b for b in 轨们 if round(b.height) == 高度们[1]]
        assert len(高轨) == 1, '多时段行应有一条 134px 的行轨'
        框, 轨 = 框们[0], 高轨[0]
        assert abs(框.y0 - (轨.y0 + 6)) < 1.5 and abs(框.y1 - (轨.y1 - 6)) < 1.5
    finally:
        plt.close(fig)


def test_绘图按竖切分段且名字只写一次():
    from src.绘图_主题 import 建主题
    _确保字体就绪()
    主题 = 建主题(None)
    行们 = 分行(一组(), 左, 右)
    高度们 = 行们行高(行们)
    图宽px, 底栏行们, _ = 定图宽(len(行们), [], 高度们)
    fig, gs, _, ax = 建分区画布(len(行们), len(底栏行们), 主题, None, 图宽px, 高度们)
    ax.set_position([0.05, 0.4, 0.9, 0.5])
    try:
        填甘特区(ax, fig, 一组(), 主题, 左, 右, 现在, 高度们)
        文 = [t.get_text() for t in ax.texts]
        assert 文.count('SS「甲」') == 1                      # 本名只出现一次
        assert {'一阶段', '二阶段', '三阶段', '商店'} <= set(文)
        切 = [l for l in ax.lines if l.get_linewidth() >= 2.5 and l.get_solid_capstyle() == 'butt']
        assert len(切) == 3, '三处阶段/商店边界各一条竖切'
        for 线 in 切:
            x, y = 线.get_data()
            assert x[0] == x[1], '多时段行只竖切，不再有斜杠'
        柱 = [p for p in ax.patches if getattr(p, 'get_facecolor', None)]
        assert len({tuple(round(c, 3) for c in p.get_facecolor()) for p in 柱}) >= 1
    finally:
        plt.close(fig)


def test_分组色弧不会把未知分组落到限时同色():
    """新分类（如某天出现没有子类型的「寻访」）不能回落到 t=0 与「限时」同色。"""
    from src.绘图_排版 import 组弧度表
    表 = 组弧度表(['限时', '福利', '寻访'])
    assert 表['寻访'] != 表['限时']
    assert len(set(表.values())) == len(表)          # 每组一个位置
    assert 组弧度表(['限时']) == 组弧度表()           # 无额外标签时与旧表一致


def test_被窗口截断的一侧不画端点竖边():
    """外框只给真实端点画竖边（A 轻主题框：次级文字色细实线）。"""
    from src.绘图_主题 import 建主题
    _确保字体就绪()
    主题 = 建主题(None)
    记录 = 一组()
    行们 = 分行(记录, 左, 右)
    高度们 = 行们行高(行们)
    图宽px, 底栏行们, _ = 定图宽(len(行们), [], 高度们)
    for 右边界, 期望边数 in ((datetime(2026, 12, 3), 4), (datetime(2026, 11, 16), 3)):
        fig, gs, _, ax = 建分区画布(len(行们), len(底栏行们), 主题, None, 图宽px, 高度们)
        ax.set_position([0.05, 0.4, 0.9, 0.5])
        try:
            填甘特区(ax, fig, 记录, 主题, 左, 右边界, 现在, 高度们)
            边们 = [l for l in ax.lines if l.get_color() == 主题.次文]
            assert len(边们) == 期望边数
            竖们 = [l for l in 边们 if l.get_data()[0][0] == l.get_data()[0][-1]]
            assert len(竖们) == (2 if 期望边数 == 4 else 1)
        finally:
            plt.close(fig)
