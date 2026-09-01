"""解析层 — 把公告页 HTML 拆成多条活动"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

logger = logging.getLogger("src.解析")

NOW = datetime.now()
本年 = NOW.year

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

六星正则 = re.compile(r"★★★★★★[：:]\s*([^（(]+)")

独立活动正则 = re.compile(r"[「](.+?锦标.*?|.+?活动.*?)[」]")

# ---------- 类型映射 ----------

章节类型规则 = [
    (["寻访", "卡池"], 0),
    (["活动关卡", "关卡开启", "SideStory", "锦标", "阵地足球"], 1),
    (["签到"], 2),
    (["组合包", "采购中心"], -1),
    (["剿灭", "保全", "生息", "集成战略"], 99),
]

跳过关键词 = ["新装", "时装", "家具", "干员登场", "凭证"]


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
    开始年 = 结束年 = 本年
    if 止月 < 起月:
        结束年 += 1
    elif 止月 == 起月 and 止日 < 起日:
        结束年 += 1
    return (
        f"{开始年}-{起月:02d}-{起日:02d} {起时:02d}:{起分:02d}:00",
        f"{结束年}-{止月:02d}-{止日:02d} {止时:02d}:{止分:02d}:00",
    )


# ---------- 六星 ----------

def 提取六星(段落列表: list[str]) -> str:
    for t in 段落列表:
        m = 六星正则.search(t)
        if m:
            return m.group(1).replace(" ", "").strip()
    return ""


# ---------- 名称处理 ----------

def _卡池短名(标题: str) -> str:
    m = re.search(r"【(.+?)】", 标题)
    return f"【{m.group(1)}】寻访" if m else "寻访"


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

def 解析分区(网页: BeautifulSoup, 父名: str) -> list[dict]:
    """把活动公告页的每个 <h2> 分区解析为一条活动"""
    容器 = 网页.find("div", class_="mw-parser-output")
    if not 容器:
        return []

    结果 = []
    for h in 容器.find_all(["h2", "h3", "h4"], recursive=True):
        标题 = h.get_text(strip=True)
        if not 标题 or 标题 == "目录":
            continue

        if any(kw in 标题 for kw in 跳过关键词):
            continue

        # 收集 <h2> 后面的 <p> 文本
        段落 = []
        for sib in h.find_next_siblings():
            if sib.name in ("h2", "h3", "h4"):
                break
            if sib.name == "p":
                t = sib.get_text(strip=True)
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
            elif 分段类型 == 0:
                名称 = _卡池短名(标题)
                six = 提取六星(段落)
                名称 = f"{父名} {名称} · {six}" if six else f"{父名} {名称}"
            elif 分段类型 == 2:
                名称 = f"{父名} 签到"
            elif 分段类型 == -1:
                名称 = f"{父名} 组合包"
            else:
                名称 = f"{父名} {标题[:12]}"

            结果.append({
                "名称": 名称,
                "开始时间": 活动时间[0],
                "结束时间": 活动时间[1],
                "类型": 分段类型 if 分段类型 != 1 else 1,
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
