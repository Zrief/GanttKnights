"""解析层 — 把 SMW ask 的查询结果转成活动条目

只负责"看懂 API 返回"：类型归类、时间戳转换、逐个活动调公告页
拆子活动。合并与存储见 汇总_活动.py。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .获取_prts import 公告页标题, 取页面修订时间, 获取公告wikitext
from .解析_公告 import 解析分区

logger = logging.getLogger("src.解析")

# PRTS 的"活动开始/结束时间"存的是 UTC，比国服早 8 小时；
# cn 后缀属性是国服时间，但只有开始时间有，结束时间一律自己 +8h 换算
UTC国服差 = timedelta(hours=8)

公告复查窗口天 = 90
"""多久之内结束过的活动，仍然算"可能被追加公告"的候选。

公告页会被**追加**（新的剿灭轮换就写在当期活动的公告里），所以"解析过"不能当"内容没变"。
候选范围 = 进行中的事件 ∪ 结束时间在窗口内的已结束事件。窗口取 90 天：
剿灭轮换一期约 90 天，而追加它的公告通常随当期活动发出、活动结束后不久轮换仍在跑。
窗口外的老页面不再进候选（否则每天要把全年几十个公告页都问一遍）。
**真正决定要不要抓**的是下一次的修订时间对比，见 `_需重取公告()`。
"""

修订记录名 = "公告修订.json"
"""记录"每个公告页上次被抓取时的修订时间"，用来判断它有没有被追加过内容。

放在数据目录（`settings.数据目录`）里，与 CSV 同级；坏了/没了只会导致多抓一次。
"""


def _修订记录路径() -> Path:
    from .config import settings

    return Path(settings.数据目录) / 修订记录名


def _读修订记录() -> dict[str, str]:
    try:
        数据 = json.loads(_修订记录路径().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("公告修订记录读不出来（按空处理）")
        return {}
    return {str(k): str(v) for k, v in 数据.items()} if isinstance(数据, dict) else {}


def _写修订记录(记录: dict[str, str]) -> None:
    try:
        路径 = _修订记录路径()
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(json.dumps(记录, ensure_ascii=False, indent=1, sort_keys=True),
                        encoding="utf-8")
    except OSError:
        logger.exception("公告修订记录写不进去（下次会重复抓，不影响正确性）")


def _需重取公告(事件名: str, 修订: dict[str, str], 已记: dict[str, str],
                未解析过: bool, 已结束: bool, 记录存在: bool) -> bool:
    """这组的公告页这次要不要重新抓？—— 判断集中在这里，好读也好测。

    | 情形 | 取不取 | 为什么 |
    |---|---|---|
    | 页面修订时间变了 | **取** | 有人往公告里追加了内容——新的剿灭轮换就是这样进来的 |
    | 没成功解析过 且 活动还在进行 | **取** | 老逻辑：公告缺失/解析规则没跟上，每天重试 |
    | 没成功解析过 且 活动已结束 | 不取 | 已结束的活动没解析出内容，重试也没意义（要补历史用 `--bootstrap`） |
    | 修订记录还不存在（首次/升级后第一次） | **取** | 一次性自愈：把窗口内候选组的公告重读一遍，
    补回以前"因为解析过而整组跳过"时漏掉的追加内容（实例里那条剿灭就是这么丢的） |
    """
    页 = 公告页标题(事件名)
    时间 = 修订.get(页)
    if 记录存在 and 时间 and 时间 != 已记.get(页):
        return True
    if not 未解析过:
        return False
    return (not 已结束) or not 记录存在

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
    主活动名下，登录活动等次要成员没有自己的公告页。公告缺失或没解析出内容的
    成员回退 ask 时间，不记来源，下次运行重试。

    ⚠️ **"公告解析过"不等于"不用再看"**（2026-09-14 修）：
    公告页会被**追加**内容——新的剿灭轮换就写在当期活动的公告页里
    （如"剿灭作战关卡【默祷圣祠】追加"挂在 `红丝绒2026` 的公告里）。
    旧实现遇到"来源已在 CSV 里"就整组跳过，于是追加的部分永远看不到，
    只有 `--bootstrap` 全量重建那次才捡得回来（实测：库里那条剿灭就是重建来的）。
    现在改成：**窗口内（或仍在进行）的组每次都重新取一遍公告**，
    窗口外的老组才沿用"解析过就不再取"。窗口见 `公告复查窗口天`。
    回溯已结束=True（--bootstrap）仍然扫描更老的已结束事件，用于初次建立数据。
    """
    已解析来源 = 已解析来源 or set()
    现在dt = datetime.strptime(现在时间, "%Y-%m-%d %H:%M:%S")
    复查线 = (现在dt - timedelta(days=公告复查窗口天)).strftime("%Y-%m-%d %H:%M:%S")

    # 整理有效条目
    待处理: list[dict] = []
    for 事件名, 条目 in api原始:
        属性 = 条目.get("printouts", {})
        开始 = 提取API时间(属性, "活动开始时间cn") or 转国服时间(提取API时间(属性, "活动开始时间"))
        结束 = 转国服时间(提取API时间(属性, "活动结束时间"))
        if not (开始 and 结束):
            continue
        已结束 = 结束 <= 现在时间
        if 已结束 and not (回溯已结束 or 结束 >= 复查线):
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

    # 一次性问清所有候选公告页有没有被改过（一次请求），以及我们上次看到的是哪个版本
    标题们 = sorted({公告页标题(m["事件名"]) for m in 待处理})
    修订 = 取页面修订时间(标题们)
    已记 = _读修订记录()
    记录存在 = bool(已记)
    if 标题们:
        logger.info("  公告页候选 %d 个，修订时间拿到 %d 个（记录%s）",
                    len(标题们), len(修订), "已有" if 记录存在 else "为空→本次全量复查")

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
        页 = 公告页标题(m["事件名"])
        if 修订.get(页):
            已记[页] = 修订[页]        # 记下这一版，下次页面没变就不再来抓
        子活动 = 解析分区(公告, m["显示名"])
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

    def 兜底(m: dict, 说明: str) -> None:
        """没收录到子活动时：进行中的成员退回 ask 时间（不记来源，下次还能再来），
        已结束的成员什么都不加（它的公告里没有仍在进行的内容）。"""
        if m["已结束"]:
            logger.info("  %s（已结束）公告无可收录内容", m["显示名"])
            return
        活动列表.append({"名称": m["显示名"], "开始时间": m["开始"],
                        "结束时间": m["结束"], "类型": m["类型"], "_parent": ""})
        logger.info("  %s → API 时间（%s）", m["显示名"], 说明)

    for 成员们 in 分组.values():
        成员们.sort(key=lambda m: (m["类型"] == 2, m["已结束"]))
        for m in 成员们:
            m["_同组"] = 成员们
        本组已解析 = any(m["显示名"] in 已解析来源 for m in 成员们)
        # 本组这次要不要读公告：任一成员"被改过 / 该重试"就重读一次
        # （公告页挂在主成员名下，组内读到第一份成功的就够）
        需重读 = any(
            _需重取公告(m["事件名"], 修订, 已记, not 本组已解析, m["已结束"], 记录存在)
            for m in 成员们
        )
        if not 需重读:
            # 公告页没变化（且都解析过）→ **整组不动**：CSV 里已有的公告内容比 API 时间准，
            # 用兜底行去覆盖它只会让同一条记录每天在两个值之间来回跳（实测踩过）。
            continue
        for m in 成员们:
            if 需重读 and 收录(m):
                需重读 = False      # 本组这次已读到内容，其余成员走兜底
                continue
            兜底(m, m["类型"] if not 本组已解析 else "公告无变化")

    if 已记:
        _写修订记录(已记)
    return 活动列表
