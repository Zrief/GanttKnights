"""解析层 — 把 SMW ask 的查询结果转成活动条目

只负责"看懂 API 返回"：类型归类、时间戳转换、逐个活动调公告页
拆子活动。合并与存储见 汇总_活动.py。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.获取_prts import 获取公告wikitext
from src.解析_公告 import 解析分区

logger = logging.getLogger("src.解析")

# PRTS 的"活动开始/结束时间"存的是 UTC，比国服早 8 小时；
# cn 后缀属性是国服时间，但只有开始时间有，结束时间一律自己 +8h 换算
UTC国服差 = timedelta(hours=8)

# ---------- API 活动类型 → 数值 ----------

API类型映射 = {
    "支线故事": 1, "主线": 1, "故事集": 1, "合作活动": 1,
    "其他活动": 1, "纪念活动": 1, "危机合约": 1,
    "矢量突破": 1, "卫戍协议": 1, "争锋频道": 1, "纷争演绎": 1,
    "登录活动": 2, "签到": 2,
    "生息演算": 99, "集成战略": 99, "剿灭": 99, "保全": 99,
}

名称类型规则 = [
    (["寻访", "中坚", "甄选", "招募", "限定", "标准池", "中坚池", "跨年"], 0),
    (["战斗", "SideStory", "故事集", "资源收集", "复刻", "联动"], 1),
    (["签到", "赠送", "领取", "月卡", "专享", "补给"], 2),
    (["家具", "时装", "新装", "主题", "上架", "风尚"], -1),
    (["剿灭", "保全", "生息", "集成战略"], 99),
]


def 分类事件(API类型: str = "", 事件名: str = "") -> int:
    if API类型 and API类型 in API类型映射:
        return API类型映射[API类型]
    for 关键词列表, 类型 in 名称类型规则:
        for kw in 关键词列表:
            if kw in 事件名:
                return 类型
    return 1


def 解析API时间戳(ts_info) -> str | None:
    """把 SMW 的 raw 时间转成 'YYYY-MM-DD HH:MM:00'

    raw 形如 1/2026/9/4/12/0/0，首段是日历标识（格里高利历=1）；
    兼容缺少首段的 6 段写法。
    """
    if isinstance(ts_info, dict):
        parts = ts_info.get("raw", "").split("/")
        if len(parts) >= 7:
            _, y, m, d, h, mi = parts[:6]
        elif len(parts) >= 6:
            y, m, d, h, mi = parts[:5]
        else:
            return None
        return f"{y}-{m.zfill(2)}-{d.zfill(2)} {h.zfill(2)}:{mi.zfill(2)}:00"
    return None


def 提取API时间(属性: dict, 键: str) -> str | None:
    值 = 属性.get(键)
    return 解析API时间戳(值[0]) if 值 else None


def 转国服时间(时间串: str | None) -> str | None:
    if not 时间串:
        return None
    t = datetime.strptime(时间串, "%Y-%m-%d %H:%M:%S") + UTC国服差
    return t.strftime("%Y-%m-%d %H:%M:%S")


def 提取官网链接(属性: dict) -> str:
    """官网公告标识：同一官方公告的活动（如月行水上和它的登录活动此夜同行）
    共享一个链接 id。无则返回空串。"""
    值 = 属性.get("官网链接")
    if not 值:
        return ""
    v = 值[0]
    return str(v.get("raw", "")).strip() if isinstance(v, dict) else str(v).strip()


def API转活动列表(api原始: list[dict], 现在时间: str, 已解析来源: set[str] | None = None, 回溯已结束: bool = False) -> list[dict]:
    """SMW ask 结果 → 活动条目列表

    开始/结束时间的 SMW 属性存的是 UTC，一律 +8h 换算成国服时间
    （开始时间优先用 活动开始时间cn，内容一致）。

    同一官网公告的活动（官网链接相同）只解析一份公告——公告页挂在
    主活动名下，登录活动等次要成员没有自己的公告页。解析成功过的活动
    （来源在 已解析来源 里）整组跳过；公告缺失或没解析出内容的成员回退
    ask 时间，不记来源，下次运行重试。

    回溯已结束=True（--bootstrap，数据初次建立时跑一次）时，额外扫描
    已结束活动的公告，补录仍在进行的剿灭/保全等长期任务轮换。
    """
    已解析来源 = 已解析来源 or set()

    # 整理有效条目
    待处理: list[dict] = []
    for 事件名, 条目 in api原始:
        属性 = 条目.get("printouts", {})
        开始 = 提取API时间(属性, "活动开始时间cn") or 转国服时间(提取API时间(属性, "活动开始时间"))
        结束 = 转国服时间(提取API时间(属性, "活动结束时间"))
        if not (开始 and 结束):
            continue
        已结束 = 结束 <= 现在时间
        if 已结束 and not 回溯已结束:
            continue
        api类型 = (属性.get("活动类型") or [None])[0] or ""
        显示名 = 事件名
        if api类型 == "集成战略":
            显示名 = f"【肉鸽】{事件名}"
        elif api类型 == "合作活动":
            显示名 = f"【联动】{事件名}"
        待处理.append({
            "事件名": 事件名,
            "显示名": 显示名,
            "开始": 开始,
            "结束": 结束,
            "类型": 分类事件(API类型=api类型 or "", 事件名=事件名),
            "已结束": 已结束,
            "组": 提取官网链接(属性) or 显示名,
        })

    # 按官网公告分组；组内登录活动等次要成员排后面（公告页挂在主活动名下）
    分组: dict[str, list[dict]] = {}
    for t in 待处理:
        分组.setdefault(t["组"], []).append(t)

    活动列表: list[dict] = []
    for 成员们 in 分组.values():
        成员们.sort(key=lambda m: (m["类型"] == 2, m["已结束"]))
        本组已入库 = any(m["显示名"] in 已解析来源 for m in 成员们)
        本组已解析 = 本组已入库
        for m in 成员们:
            if m["显示名"] in 已解析来源:
                logger.info("  %s 公告已解析过，跳过", m["显示名"])
                continue
            if not 本组已解析:
                公告 = 获取公告wikitext(m["事件名"])
                if 公告 is not None:
                    子活动 = 解析分区(公告, m["显示名"])
                    if m["已结束"]:
                        # 已结束成员的公告只收仍在进行的内容（剿灭/保全轮换等）
                        子活动 = [e for e in 子活动 if e["结束时间"] > 现在时间]
                    # 公告里的签到板块往往不带本名（如月行水上公告的签到
                    # 其实是此夜同行）：窗口与同组成员一致的，交给该成员的
                    # ask 条目，丢弃无名副本
                    同组窗口 = {
                        (x["开始"], x["结束"]) for x in 成员们 if x["显示名"] != m["显示名"]
                    }
                    子活动 = [
                        e for e in 子活动
                        if e["类型"] != 2 or (e["开始时间"], e["结束时间"]) not in 同组窗口
                    ]
                    if 子活动:
                        活动列表.extend(子活动)
                        本组已解析 = True
                        logger.info("  %s → %d 条子活动", m["显示名"], len(子活动))
                        continue
                    if not m["已结束"]:
                        # 公告明明存在却解析不出内容，多半是解析规则跟不上
                        # 页面改版——这是需要人工介入的信号
                        logger.warning(
                            "  %s 公告存在但未解析出子活动，已回退 API 时间；若多日持续请检查 src/解析_公告.py 的规则",
                            m["显示名"],
                        )
                if not m["已结束"]:
                    # 无公告页或没解析出内容：回退 ask 时间，不记来源，下次重试
                    活动列表.append({"名称": m["显示名"], "开始时间": m["开始"], "结束时间": m["结束"], "类型": m["类型"], "_parent": ""})
                    logger.info("  %s → API 时间（%s）", m["显示名"], m["类型"])
                else:
                    logger.info("  %s（已结束）公告无可收录内容", m["显示名"])
                continue
            # 本组公告已解析过：其余成员直接用 ask 时间兜底，不再探测公告
            if not m["已结束"]:
                活动列表.append({"名称": m["显示名"], "开始时间": m["开始"], "结束时间": m["结束"], "类型": m["类型"], "_parent": ""})
                logger.info("  %s → API 时间（同组公告已解析）", m["显示名"])

    return 活动列表
