"""解析层 — 把公告页 wikitext 拆成多条活动"""

from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger("src.解析")

# ---------- 正则 ----------

时间正则 = re.compile(
    r"(?:活动时间|售卖时间|开放时间|关卡开放时间|家具商店售卖时间)"
    r"[：:]\s*"
    r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
    r"\s*[～~\-]\s*"
    r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
)

关卡时间正则 = re.compile(
    r"◆.+?[：:]\s*"
    r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
    r"\s*[～~\-]\s*"
    r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
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

def 解析时间(文本: str) -> tuple[str, str] | None:
    m = 关卡时间正则.search(文本) or 时间正则.search(文本)
    if not m:
        return None
    起月, 起日, 起时, 起分 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    止月, 止日, 止时, 止分 = int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8))
    # 公告里只有"X月X日"没有年份：日期若在 300 天以前，
    # 视为跨年预告（如 12 月公告次年 1 月的活动）
    今天 = datetime.now()
    开始年 = 今天.year
    if (今天 - datetime(开始年, 起月, 起日)).days > 300:
        开始年 += 1
    结束年 = 开始年
    if (止月, 止日) < (起月, 起日):
        结束年 += 1
    return (
        f"{开始年}-{起月:02d}-{起日:02d} {起时:02d}:{起分:02d}:00",
        f"{结束年}-{止月:02d}-{止日:02d} {止时:02d}:{止分:02d}:00",
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


def 解析分区(wikitext: str, 父名: str) -> list[dict]:
    """把活动公告页 wikitext 按 ==分区== 解析为一条条活动"""
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
            pt = 解析时间(t)
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
                结果.append({
                    "名称": _独立活动名(标题),
                    "开始时间": 活动时间[0],
                    "结束时间": 活动时间[1],
                    "类型": 分段类型,
                    "_parent": "",
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

    return 结果
