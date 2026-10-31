"""已结束页面的解析诊断降为 debug：初始化回溯半年时终端不再被 WARN 刷屏。

消息端的“部分活动未更新”与这里同一口径（见 解析_API活动.隔离）：
活动还进行中才报 warning，已结束只记 debug。
裸机日志不走标准库 logging（见 src/日志.py），所以用替身记录器断言。
"""
from __future__ import annotations

from datetime import datetime


class 记录器:
    def __init__(self):
        self.项: list[tuple[str, str]] = []

    def _收(self, 级别):
        def _记(msg, *args, **kwargs):
            self.项.append((级别, str(msg) % args if args else str(msg)))
        return _记

    def __getattr__(self, 名):
        # debug/info/warning/error/exception 都收
        return self._收(名)

    def 级别们(self):
        return [级别 for 级别, _ in self.项]


def 板块(内核模块, 窗口=None):
    return 内核模块('解析_公告').板块(标题='2026「某活动」，「某板块」活动开启',
                               窗口=窗口, 关卡各段=[], 类型=1, 是主体=False)


def 成员(**覆盖):
    m = dict(事件名='某活动', 显示名='某活动', 公告页='某活动/活动公告',
             锚点='不存在的锚点', 类型=1,
             开始='2099-01-01 00:00:00', 结束='2099-12-31 23:59:00', 已结束=False)
    m.update(覆盖)
    return m


def test_已结束页面的认领诊断不刷WARN(monkeypatch, 内核模块):
    api = 内核模块('解析_API活动')
    记录 = 记录器()
    monkeypatch.setattr(api, 'logger', 记录)
    api.认领与生成([成员(已结束=True)], {'某活动/活动公告': [板块(内核模块)]})
    assert 'warning' not in 记录.级别们(), 记录.项


def test_进行中页面的认领诊断仍报WARN(monkeypatch, 内核模块):
    """标题候选不唯一（真歧义）仍要 warning；唯一标题兜底属良性回退不报。"""
    api = 内核模块('解析_API活动')
    记录 = 记录器()
    monkeypatch.setattr(api, 'logger', 记录)
    板块们 = [板块(内核模块), 板块(内核模块)]
    板块们[1].标题 = '2026「某活动」，「另一个板块」活动开启'
    api.认领与生成([成员(已结束=False)], {'某活动/活动公告': 板块们})
    assert any('公告认领' in msg for 级别, msg in 记录.项 if 级别 == 'warning'), 记录.项


def test_唯一标题兜底属良性回退不刷WARN(monkeypatch, 内核模块):
    """锚点零匹配但标题唯一、板块有窗口（能接管）→ 只有良性诊断，不刷 WARN。"""
    api = 内核模块('解析_API活动')
    记录 = 记录器()
    monkeypatch.setattr(api, 'logger', 记录)
    有效板块 = 板块(内核模块, 窗口=('2026-11-01 12:00:00', '2026-11-10 03:59:00'))
    api.认领与生成([成员(已结束=False)], {'某活动/活动公告': [有效板块]})
    assert 'warning' not in 记录.级别们(), 记录.项


def test_抽板块静默把问题写debug(monkeypatch, 内核模块):
    公告 = 内核模块('解析_公告')
    文本 = ('==2026「感谢庆典」，「某活动」活动开启==\n'
            "'''活动开启时间：'''11月08日 16:00（补注）\n")
    记录 = 记录器()
    monkeypatch.setattr(公告, 'logger', 记录)
    公告.抽板块(文本, datetime(2026, 10, 30), 静默=True)
    assert 'warning' not in 记录.级别们(), 记录.项
    记录.项.clear()
    公告.抽板块(文本, datetime(2026, 10, 30))
    assert any('时间未精确解析' in msg for 级别, msg in 记录.项 if 级别 == 'warning'), 记录.项
