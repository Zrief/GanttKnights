"""解析层 — 把公告页 wikitext 拆成多条活动"""

from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger("src.解析")

# ---------- 正则 ----------

# 年份是**可选**的：公告多数只写"X月X日"，偶尔在跨年处才写"2026年01月02日"。
# 组号因此是 1..5（起：年/月/日/时/分）与 6..10（止：年/月/日/时/分）。
时间正则 = re.compile(
    r"(?:活动时间|售卖时间|开放时间|开启时间|关卡开放时间|家具商店售卖时间)"
    r"[：:]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
    r"\s*[～~\-]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
)

关卡时间正则 = re.compile(
    r"◆.+?[：:]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
    r"\s*[～~\-]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
)
独立活动正则 = re.compile(r"[「](.+?锦标.*?|.+?活动.*?)[」]")

标题正则 = re.compile(r"^(={2,4})(.+?)\1\s*$", re.M)

# ---------- 类型映射 ----------

章节类型规则 = [
    (["活动关卡", "关卡开启", "SideStory", "锦标", "阵地足球"], 1),
    (["签到"], 2),
    (["组合包", "采购中心"], -1),
    (["剿灭", "保全", "生息", "集成战略"], 99),
]

# 寻访条目由 卡池一览 wikitext 专门提供，公告页里的寻访分区直接跳过
跳过关键词 = ["新装", "时装", "家具", "干员登场", "凭证", "寻访"]


def _匹配关键词(标题: str, 规则表: list) -> int | None:
    for 关键词列表, 类型 in 规则表:
        for kw in 关键词列表:
            if kw in 标题:
                return 类型
    return None


def 分类章节(标题: str) -> int:
    t = _匹配关键词(标题, 章节类型规则)
    return t if t is not None else 1


# ---------- 时间 ----------

def _择年(月: int, 日: int, 基准: datetime) -> int:
    """只有"X月X日"没有年份时，选**离基准时间最近**的那一年。

    基准必须是**这条子活动所属活动的时间窗**（`API转活动列表` 手里的 ask 时间），
    不能是"今天"——公告页保留多年，用今天当基准会把 2025 年的老公告算成今年，
    生成一批"未来活动"（2026-09-14 实测：`揭幕者们2025` 被算成 2026-11-25，长期留在库里）。
    """
    候选 = [基准.year - 1, 基准.year, 基准.year + 1]

    def 距离(年: int) -> float:
        try:
            return abs((datetime(年, 月, 日) - 基准).total_seconds())
        except ValueError:          # 2月29日之类
            return float("inf")

    return min(候选, key=距离)


def 解析时间(文本: str, 参考: datetime | None = None) -> tuple[str, str] | None:
    """`X月X日 H:MM - X月X日 H:MM`（年份可写可不写）→ (开始, 结束)

    年份规则：
    - 文本里写了年份（跨年公告常见，如 `2026年01月02日`）→ 用它；
    - 没写 → 取离 `参考` 最近的那一年，`参考` 传**父活动的时间窗**；
    - 结束早于开始时（12 月 → 次年 1 月）→ 结束年 +1。
    """
    m = 关卡时间正则.search(文本) or 时间正则.search(文本)
    if not m:
        return None
    起年文本, 起月, 起日, 起时, 起分 = m.group(1, 2, 3, 4, 5)
    止年文本, 止月, 止日, 止时, 止分 = m.group(6, 7, 8, 9, 10)
    基准 = 参考 or datetime.now()
    开始年 = int(起年文本) if 起年文本 else _择年(int(起月), int(起日), 基准)
    开始 = datetime(开始年, int(起月), int(起日), int(起时), int(起分))
    结束年 = int(止年文本) if 止年文本 else _择年(int(止月), int(止日), 开始)
    结束 = datetime(结束年, int(止月), int(止日), int(止时), int(止分))
    if 结束 < 开始 and not 止年文本:
        结束 = 结束.replace(year=结束.year + 1)
    return (
        开始.strftime("%Y-%m-%d %H:%M:%S"),
        结束.strftime("%Y-%m-%d %H:%M:%S"),
    )


# ---------- 名称处理 ----------


def _是独立活动(标题: str, 父名: str) -> bool:
    if 父名 in 标题:
        return False
    子关键词 = ["活动关卡", "SideStory", "组合包", "寻访", "签到", "采购"]
    return not any(kw in 标题 for kw in 子关键词)


def _独立活动名(标题: str) -> str:
    m = 独立活动正则.search(标题)
    if m:
        return m.group(1)
    m = re.search(r"[「](.+?)[」]", 标题)
    if m:
        return m.group(1)
    return 标题[:12]


长期前缀词 = ("剿灭", "保全", "生息", "集成战略")


def _长期任务名(标题: str) -> str:
    """剿灭/保全等长期板块取名：【前缀】+标题【】里的对象名，
    如"剿灭作战关卡【默祷圣祠】追加" → "【剿灭】默祷圣祠\""""
    关键词 = next(k for k in 长期前缀词 if k in 标题)
    m = re.search(r"【([^】]+)】", 标题)
    return f"【{关键词}】{m.group(1)}" if m else 标题


# 保全轮换不在任何公开来源（活动公告/SMW/保全派驻页均无日期），列为待办项：
# 解析链路保持就位，将来官方一旦公告，这里会以 warning 提醒
def _提醒保全(条目们: list[dict]) -> None:
    for e in 条目们:
        if e["名称"].startswith("【保全】"):
            logger.warning(
                "🔔 检测到保全派驻轮换公告：%s（%s ~ %s）——保全此前无公开来源，首次解析到",
                e["名称"], e["开始时间"], e["结束时间"],
            )


# ---------- 页面解析 ----------

def _清理行(行: str) -> str:
    """剥掉加粗/斜体和 HTML 标签；模板含日期时剥语法留内容，否则整块删除"""
    行 = re.sub(r"'+", "", 行)
    行 = re.sub(r"<[^>]+>", "", 行)

    def _处理模板(m: re.Match) -> str:
        模板 = m.group(0)
        if "月" not in 模板:
            return ""
        return re.sub(r"\{\{[^|{}]*\|?", "", 模板).replace("}}", "")

    return re.sub(r"\{\{[^{}]*\}\}", _处理模板, 行).strip()


def 解析分区(wikitext: str, 父名: str, 参考: datetime | None = None) -> list[dict]:
    """把活动公告页 wikitext 按 ==分区== 解析为一条条活动

    `参考` = 父活动的时间窗（ask 给的），用于给"只有 X月X日"的公告**定年份**（见 `解析时间`）。
    """
    匹配们 = list(标题正则.finditer(wikitext))
    if not 匹配们:
        return []

    结果 = []
    for i, m in enumerate(匹配们):
        标题 = m.group(2).strip()
        if not 标题 or 标题 == "目录":
            continue

        if any(kw in 标题 for kw in 跳过关键词):
            continue

        # 收集分区正文里的非空文本行
        正文终点 = 匹配们[i + 1].start() if i + 1 < len(匹配们) else len(wikitext)
        段落 = []
        for 行 in wikitext[m.end():正文终点].splitlines():
            t = _清理行(行)
            if t:
                段落.append(t)

        # 分离活动时间和关卡子时间
        活动时间 = None
        关卡各段 = []

        for t in 段落:
            pt = 解析时间(t, 参考)
            if not pt:
                continue
            if "活动时间" in t:
                活动时间 = pt
            elif "◆" in t:
                关卡各段.append(pt)
            elif not 活动时间:
                活动时间 = pt

        if not 活动时间 and not 关卡各段:
            continue

        是主体 = "活动关卡" in 标题 or "SideStory" in 标题
        是独立的 = _是独立活动(标题, 父名)
        分段类型 = 分类章节(标题)

        # --- 独立活动 ---
        if 是独立的:
            if 活动时间:
                名称 = _长期任务名(标题) if 分段类型 == 99 else _独立活动名(标题)
                结果.append({
                    "名称": 名称,
                    "开始时间": 活动时间[0],
                    "结束时间": 活动时间[1],
                    "类型": 分段类型,
                    "_parent": 父名,
                })
            continue

        # --- 主体活动时间 ---
        if 活动时间:
            if 是主体:
                名称 = 父名
            elif 分段类型 == 2:
                名称 = f"{父名} 签到"
            elif 分段类型 == -1:
                名称 = f"{父名} 组合包"
            else:
                名称 = f"{父名} {标题}"
                for suffix in ("限时开放", "限时售卖", "限时上架", "限时开启"):
                    if 名称.endswith(suffix):
                        名称 = 名称[:-len(suffix)]
                        break

            结果.append({
                "名称": 名称,
                "开始时间": 活动时间[0],
                "结束时间": 活动时间[1],
                "类型": 分段类型,
                "_parent": 父名,
            })

        # --- 关卡时间 ---
        if 关卡各段 and 是主体:
            最早开始 = min(关卡各段, key=lambda x: x[0])
            最晚结束 = max(关卡各段, key=lambda x: x[1])
            结果.append({
                "名称": f"{父名} 关卡",
                "开始时间": 最早开始[0],
                "结束时间": 最晚结束[1],
                "类型": 1,
                "_parent": 父名,
            })
    _提醒保全(结果)
    return 结果
