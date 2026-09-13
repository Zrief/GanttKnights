"""解析层 — 把 SMW ask 的查询结果转成活动条目

只负责"看懂 API 返回"：类型归类、时间戳转换、逐个活动调公告页拆子活动。
合并与存储见 汇总_活动.py。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .获取_prts import 获取公告wikitext
from .解析_公告 import 解析分区

logger = logging.getLogger("src.解析")

# PRTS 的"活动开始/结束时间"存的是 UTC，比国服早 8 小时；
# cn 后缀属性是国服时间，但只有开始时间有，结束时间一律自己 +8h 换算
UTC国服差 = timedelta(hours=8)

近期窗口天 = 30
"""日常扫描的时间窗：**进行中的活动** + **结束时间在这个窗口内**的已结束活动。

流程（2026-09-14 与用户对齐）：**先初始化一份 CSV，之后只动态维护它**——
日常只扫"最近这部分"（新出现的加进来、过期的由合并删掉），
老活动的公告不会再变，没必要天天读。初始化（`回溯已结束=True`）才扫所有活动。

窗口取 30 天：剿灭轮换的公告随当期活动一起发（活动结束前就挂上了，属于"进行中"那类），
30 天足以覆盖"停几天机、活动刚结束"的情况；更老的靠初始化补齐。
"""

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


def API转活动列表(api原始: list[dict], 现在时间: str, 回溯已结束: bool = False) -> list[dict]:
    """SMW ask 结果 → 活动条目列表

    开始/结束时间的 SMW 属性存的是 UTC，一律 +8h 换算成国服时间
    （开始时间优先用 活动开始时间cn，内容一致）。

    - `回溯已结束=False`（日常）：只看**进行中 + 近期窗口内结束过**的活动；
    - `回溯已结束=True`（初始化：CLI `--bootstrap` / `/甘特图初始化`）：看**所有**活动。

    对看得到的事件，**每次都读一遍它的公告页**（不查"解析过没有"、不记台账）：
    公告页会被**追加**内容——新的剿灭轮换就写在当期活动的公告里，
    按"解析过就跳过"会让追加部分永远看不到（2026-09-14 实测：库里那条剿灭只有
    全量重建那次才捡到）。读不到公告就用 ask 时间兜底。

    同一官网公告的活动（官网链接相同）只读一份公告——公告页挂在主活动名下，
    登录活动等次要成员没有自己的公告页。

    新增与过期不在这里判断：交给下游 `合并保存CSV`（它拿这个列表和昨天的 CSV 合并，
    有新增就加、过期就删）。
    """
    现在dt = datetime.strptime(现在时间, "%Y-%m-%d %H:%M:%S")
    窗口线 = (现在dt - timedelta(days=近期窗口天)).strftime("%Y-%m-%d %H:%M:%S")

    # 整理有效条目：进行中的 + 窗口内结束过的（更老的活动不读公告，靠初始化补齐）
    待处理: list[dict] = []
    for 事件名, 条目 in api原始:
        属性 = 条目.get("printouts", {})
        开始 = 提取API时间(属性, "活动开始时间cn") or 转国服时间(提取API时间(属性, "活动开始时间"))
        结束 = 转国服时间(提取API时间(属性, "活动结束时间"))
        if not (开始 and 结束):
            continue
        已结束 = 结束 <= 现在时间
        if 已结束 and not (回溯已结束 or 结束 >= 窗口线):
            continue
        api类型 = (属性.get("活动类型") or [None])[0] or ""
        显示名 = 事件名
        if api类型 == "集成战略":
            显示名 = f"【肉鸽】{事件名}"
        elif api类型 == "合作活动":
            显示名 = f"【联动】{事件名}"
        开始dt = datetime.strptime(开始, "%Y-%m-%d %H:%M:%S")
        结束dt = datetime.strptime(结束, "%Y-%m-%d %H:%M:%S")
        待处理.append({
            "事件名": 事件名,
            "显示名": 显示名,
            "开始": 开始,
            "结束": 结束,
            "类型": 分类事件(API类型=api类型 or "", 事件名=事件名),
            "已结束": 已结束,
            "组": 提取官网链接(属性) or 显示名,
            # 公告里多数只写"X月X日"：定年份要拿**父活动的时间窗中点**当基准
            # （用"今天"当基准会把老公告算成今年，见 解析_公告.解析时间）
            "参考": 开始dt + (结束dt - 开始dt) / 2,
        })

    # 按官网公告分组；组内登录活动等次要成员排后面（公告页挂在主活动名下）
    分组: dict[str, list[dict]] = {}
    for t in 待处理:
        分组.setdefault(t["组"], []).append(t)

    活动列表: list[dict] = []

    def 收录(m: dict) -> bool:
        """用 m 的公告页收录子活动；成功（读到页面且解析出内容）返回 True。

        已结束成员的公告只收**仍在进行**的内容（剿灭/保全轮换等）；
        公告里的签到板块往往不带本名（如月行水上公告的签到其实是此夜同行），
        窗口与同组成员一致的交给该成员的 ask 条目，丢弃无名副本。
        """
        公告 = 获取公告wikitext(m["事件名"])
        if 公告 is None:
            return False
        子活动 = 解析分区(公告, m["显示名"], m["参考"])
        if m["已结束"]:
            子活动 = [e for e in 子活动 if e["结束时间"] > 现在时间]
        同组窗口 = {(x["开始"], x["结束"]) for x in m["_同组"] if x["显示名"] != m["显示名"]}
        子活动 = [e for e in 子活动
                 if e["类型"] != 2 or (e["开始时间"], e["结束时间"]) not in 同组窗口]
        if 子活动:
            活动列表.extend(子活动)
            logger.info("  %s → %d 条子活动", m["显示名"], len(子活动))
            return True
        if not m["已结束"]:
            # 公告明明存在却解析不出内容，多半是解析规则跟不上页面改版——需要人工介入
            logger.warning(
                "  %s 公告存在但未解析出子活动，已回退 API 时间；若多日持续请检查 src/解析_公告.py 的规则",
                m["显示名"],
            )
        return False

    def 兜底(m: dict) -> None:
        """没收录到子活动时：进行中的成员退回 ask 时间，已结束的什么都不加
        （它的公告里没有仍在进行的内容）。"""
        if m["已结束"]:
            logger.info("  %s（已结束）公告无可收录内容", m["显示名"])
            return
        活动列表.append({"名称": m["显示名"], "开始时间": m["开始"],
                        "结束时间": m["结束"], "类型": m["类型"], "_parent": ""})
        logger.info("  %s → API 时间（%s）", m["显示名"], m["类型"])

    for 成员们 in 分组.values():
        成员们.sort(key=lambda m: (m["类型"] == 2, m["已结束"]))
        for m in 成员们:
            m["_同组"] = 成员们
        已读到 = False
        for m in 成员们:
            if not 已读到 and 收录(m):
                已读到 = True       # 本组这次已读到内容，其余成员走兜底
                continue
            兜底(m)

    return 活动列表
