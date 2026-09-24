"""解析层 — 公告页 / 活动页的 wikitext 解析

- `抽板块` / `板块条目` / `关卡条目`：公告 → 板块表与条目。纯解析，认领策略见 解析_API活动。
- `解析活动信息` / `公告定位` / `页父名`：活动页 `{{活动信息}}` 的 `公告=` 指认——
  wiki 在这里维护着"这条活动的内容在哪个公告页的哪个板块"，可带 #板块锚点
  （如 此夜同行 → 月行水上/活动公告#【…】签到活动开启）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from . import 长期活动

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
    (list(长期活动.关键词们), 长期活动.类型值),   # 长期玩法：定义只有一份（src/长期活动.py）
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


def _长期任务名(标题: str) -> str:
    """长期板块取名：**官方名**当前缀 + 标题【】里的对象名。

    如"剿灭作战关卡【默祷圣祠】追加" → "【剿灭作战】默祷圣祠"。
    前缀与识别都来自 `长期活动`（唯一定义）；标题里没有【】或认不出玩法时原样返回标题。
    """
    前缀 = 长期活动.前缀名(标题)
    m = re.search(r"【([^】]+)】", 标题)
    return f"{前缀}{m.group(1)}" if 前缀 and m else 标题


# 保全轮换不在任何公开来源（活动公告/SMW/保全派驻页均无日期），列为待办项：
# 解析链路保持就位，将来官方一旦公告，这里会以 warning 提醒
def 提醒保全(条目们: list[dict]) -> None:
    for e in 条目们:
        if e["名称"].startswith("【保全】"):
            logger.warning(
                "🔔 检测到保全派驻轮换公告：%s（%s ~ %s）——保全此前无公开来源，首次解析到",
                e["名称"], e["开始时间"], e["结束时间"],
            )


# ---------- 活动页本体：{{活动信息}} 模板 ----------

def 解析活动信息(wikitext: str) -> dict[str, str]:
    """活动页 wikitext → `{{活动信息}}` 模板的字段表（要的是 `公告=` 指认）。无模板 → {}"""
    m = re.search(r"\{\{活动信息(.*?)\}\}", wikitext, re.S)
    if not m:
        return {}
    return {
        km.group(1).strip(): km.group(2).strip()
        for 行 in m.group(1).splitlines()
        if (km := re.match(r"\|\s*([^=|]+?)\s*=\s*(.*)", 行))
    }


def 公告定位(公告值: str) -> tuple[str, str]:
    """`公告=` 的值 → (公告页名, 板块锚点)。带锚点时 wiki 已指认到具体板块，
    这是"板块名与活动名无关"时（此夜同行）唯一的可靠映射。"""
    页名, _, 锚点 = 公告值.partition("#")
    return 页名.strip(), 锚点.strip()


def 页父名(页名: str) -> str:
    """公告页名 → 所属活动名（`X/活动公告` → `X`；其他写法原样返回）"""
    return 页名[: -len("/活动公告")] if 页名.endswith("/活动公告") else 页名


# ---------- 公告解析：板块表 ----------

@dataclass
class 板块:
    """公告里的一个分区。命名与认领策略不在这一层（见 解析_API活动）。"""

    标题: str
    窗口: tuple[str, str] | None          # `活动时间：` 的起止；只有 ◆ 关卡段的板块没有它
    关卡各段: list[tuple[str, str]]
    类型: int
    是主体: bool                          # 主活动板块（SideStory/活动关卡）：◆ 段要另出一条 关卡


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


def 抽板块(wikitext: str, 参考: datetime | None = None) -> list[板块]:
    """公告 wikitext → 板块列表。

    跳过 寻访/时装 等板块（条目另有来源，见 跳过关键词）。
    `参考` = 父活动时间窗，用于给"只写 X月X日"的日期定年份（见 `解析时间`）。
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
        活动时间 = None
        关卡各段: list[tuple[str, str]] = []

        for 行 in wikitext[m.end():正文终点].splitlines():
            t = _清理行(行)
            if not t:
                continue
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

        结果.append(板块(
            标题=标题,
            窗口=活动时间,
            关卡各段=关卡各段,
            类型=分类章节(标题),
            是主体=("活动关卡" in 标题 or "SideStory" in 标题),
        ))
    return 结果


def 关卡条目(b: 板块, 父名: str) -> dict | None:
    """主体板块的 ◆ 关卡段 → 一条 `父名 关卡` 条目（跨段取最早开始/最晚结束）"""
    if not (b.关卡各段 and b.是主体):
        return None
    return {
        "名称": f"{父名} 关卡",
        "开始时间": min(段[0] for 段 in b.关卡各段),
        "结束时间": max(段[1] for 段 in b.关卡各段),
        "类型": 1,
        "_parent": 父名,
    }


def 板块条目(b: 板块, 父名: str) -> list[dict]:
    """无人认领的板块自生成的条目（沿用既有命名规则）。"""
    结果 = []

    if _是独立活动(b.标题, 父名):
        if b.窗口:
            名称 = _长期任务名(b.标题) if b.类型 == 99 else _独立活动名(b.标题)
            结果.append({
                "名称": 名称,
                "开始时间": b.窗口[0],
                "结束时间": b.窗口[1],
                "类型": b.类型,
                "_parent": 父名,
            })
        return 结果

    if b.窗口:
        if b.是主体:
            名称 = 父名
        elif b.类型 == 2:
            名称 = f"{父名} 签到"
        elif b.类型 == -1:
            名称 = f"{父名} 组合包"
        else:
            名称 = f"{父名} {b.标题}"
            for suffix in ("限时开放", "限时售卖", "限时上架", "限时开启"):
                if 名称.endswith(suffix):
                    名称 = 名称[:-len(suffix)]
                    break

        结果.append({
            "名称": 名称,
            "开始时间": b.窗口[0],
            "结束时间": b.窗口[1],
            "类型": b.类型,
            "_parent": 父名,
        })

    if 关卡 := 关卡条目(b, 父名):
        结果.append(关卡)
    return 结果
