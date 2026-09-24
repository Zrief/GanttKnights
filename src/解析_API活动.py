"""解析层 — 把 SMW ask 的查询结果转成活动条目

**公告是唯一时间源，ask 只当电话簿**（2026-09-17 定；页面名/类型/粗窗口/分组）：
wiki 手填的 SMW 属性会抄错（实测 `稳态测定` 的窗口被抄成月行水上那批的），
而公告原文是运营公告的逐字转载。ask 时间只剩三个用途：30 天扫描过滤、
公告年份锚、无公告页条目（99 型常驻）的兜底。

认领顺序即降级顺序（`认领与生成`）：`公告=` 的 #板块锚点（wiki 的显式指认）→
板块标题含活动名 → ask 粗窗口。无人认领的板块（关卡◆/组合包/剿灭追加）照常自生成。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import 长期活动
from .获取_prts import 公告页标题, 获取页面wikitext
from .解析_公告 import 板块, 板块条目, 公告定位, 关卡条目, 页父名, 解析活动信息, 提醒保全, 抽板块

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
    # 长期玩法：字面量来自 src/长期活动.py（SMW「活动类型」的精确取值）
    **{字面量: 长期活动.类型值 for 字面量 in 长期活动.字面量们},
}

名称类型规则 = [
    (["寻访", "中坚", "甄选", "招募", "限定", "标准池", "中坚池", "跨年"], 0),
    (["战斗", "SideStory", "故事集", "资源收集", "复刻", "联动"], 1),
    (["签到", "赠送", "领取", "月卡", "专享", "补给"], 2),
    (["家具", "时装", "新装", "主题", "上架", "风尚"], -1),
    (list(长期活动.关键词们), 长期活动.类型值),
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


def 认领与生成(成员们: list[dict], 页们: dict[str, list[板块]]) -> list[dict]:
    """组内的三层认领与条目生成（**纯函数**：网络与页面定位由调用方负责，测试直接喂字典）。

    成员字段：事件名 / 显示名 / 开始 / 结束 / 类型 / 已结束 / 公告页 / 锚点。
    每个成员至多认领一个板块，每个板块至多被一个成员认领。
    """
    全板块 = [(页名, b) for 页名, 表 in 页们.items() for b in 表]
    认领: dict[int, dict] = {}       # 板块序号 → 成员
    已领: set[int] = set()           # 已认领成员的 id()

    def 试认领(m: dict, i: int, b: 板块, 方式: str) -> bool:
        if i not in 认领 and b.窗口:
            认领[i] = m
            已领.add(id(m))
            logger.info("  %s ← 板块「%s」（%s认领）", m["显示名"], b.标题, 方式)
            return True
        return False

    for m in 成员们:                                 # ① 锚点：wiki 的显式指认（只在该成员指的页里找）
        if m["锚点"]:
            for i, (页名, b) in enumerate(全板块):
                if 页名 == m["公告页"] and b.标题 == m["锚点"] and 试认领(m, i, b, "锚点"):
                    break
    for m in 成员们:                                 # ② 板块标题含事件名
        if id(m) not in 已领:
            for i, (_, b) in enumerate(全板块):
                if m["事件名"] in b.标题 and 试认领(m, i, b, "标题"):
                    break

    结果 = []
    for i, (页名, b) in enumerate(全板块):
        父名 = 页父名(页名)
        m = 认领.get(i)
        if m is None:
            结果.extend(板块条目(b, 父名))            # 无人认领：按既有命名规则自生成
            continue
        结果.append({"名称": m["显示名"], "开始时间": b.窗口[0], "结束时间": b.窗口[1],
                    "类型": m["类型"], "_parent": 父名})
        if 关卡 := 关卡条目(b, 父名):                 # 被认领的主体板块，其 ◆ 段照常出一条 关卡
            结果.append(关卡)

    for m in 成员们:                                 # ③ 未认领 → ask 粗窗口
        if id(m) in 已领:
            continue
        if m["已结束"]:
            logger.info("  %s → 未认领（已结束，不添加）", m["显示名"])
        else:
            结果.append({"名称": m["显示名"], "开始时间": m["开始"], "结束时间": m["结束"],
                        "类型": m["类型"], "_parent": ""})
            logger.info("  %s → ask 时间（类型 %s，公告未认领）", m["显示名"], m["类型"])
    return 结果


def API转活动列表(api原始: list[dict], 现在时间: str, 回溯已结束: bool = False) -> list[dict]:
    """SMW ask 结果 → 活动条目列表（机制见模块 docstring）

    - `回溯已结束=False`（日常）：只看**进行中 + 近期窗口内结束过**的活动；
    - `回溯已结束=True`（初始化：CLI `--bootstrap` / `/甘特图初始化`）：看**所有**活动。

    公告页会被**追加**内容（新的剿灭轮换写在当期活动的公告里），所以看得到的组
    每次都重读公告——公告也是我们唯一的显示时间来源。

    新增与过期不在这里判断：交给下游 `合并保存CSV`（它拿这个列表和昨天的 CSV 合并，
    有新增就加、过期就删）。
    """
    现在dt = datetime.strptime(现在时间, "%Y-%m-%d %H:%M:%S")
    窗口线 = (现在dt - timedelta(days=近期窗口天)).strftime("%Y-%m-%d %H:%M:%S")

    # 整理成员：ask 只提供身份（名称/类型/分组）与粗窗口（过滤 + 年份锚）
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
        # 长期玩法用官方名当前缀（左列只写「长期」，玩法信息得靠名字带）；
        # 前缀与识别来自 src/长期活动.py —— 剿灭/保全 也一起走，不再只挑肉鸽/联动
        if (长期前缀 := 长期活动.前缀名(api类型)):
            显示名 = f"{长期前缀}{事件名}"
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

    # 逐成员读活动页本体的 {{活动信息}}，拿 公告= 指认（99 型常驻没有公告页，跳过）
    for m in 待处理:
        m["公告页"] = m["锚点"] = None
        if m["类型"] != 99:
            信息 = 解析活动信息(获取页面wikitext(m["事件名"]) or "")
            if 信息.get("公告"):
                m["公告页"], m["锚点"] = 公告定位(信息["公告"])

    分组: dict[str, list[dict]] = {}
    for t in 待处理:
        分组.setdefault(t["组"], []).append(t)

    公告缓存: dict[tuple[str, datetime], list[板块]] = {}

    def 取公告(页名: str, 参考: datetime) -> list[板块]:
        """读一份公告页 → 板块表；读不到 → 空表。缓存键带**参考窗**：
        同一份公告可能被复刻页指回，年份锚不同则解析结果不同，不能共用。"""
        键 = (页名, 参考)
        if 键 not in 公告缓存:
            wikitext = 获取页面wikitext(页名)
            公告缓存[键] = 抽板块(wikitext, 参考) if wikitext else []
        return 公告缓存[键]

    活动列表: list[dict] = []
    for 成员们 in 分组.values():
        成员们.sort(key=lambda m: (m["类型"] == 2, m["已结束"]))   # 主活动先认领
        # 组的公告页：成员 公告= 指的页；没人写过才退回主成员的默认公告页
        候选们 = [m["公告页"] for m in 成员们 if m["公告页"]]
        if not 候选们 and 成员们[0]["类型"] != 99:
            候选们 = [公告页标题(成员们[0]["事件名"])]
        页们 = {页: 表 for 页 in dict.fromkeys(候选们)
               if (表 := 取公告(页, 成员们[0]["参考"]))}
        活动列表.extend(认领与生成(成员们, 页们))

    提醒保全(活动列表)
    return 活动列表
