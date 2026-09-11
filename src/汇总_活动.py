"""汇总层 — 合并商店、去重排序、活动数据 CSV 增量存储"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("src.汇总")

# store 里过期超过这个天数的条目自动清理
过期保留天数 = 7


# ---------- 商店合并 ----------

def 合并商店(活动列表: list[dict]) -> list[dict]:
    """合并同一父活动下的多条礼包为一条"""
    groups: dict[str, list[dict]] = {}
    for it in 活动列表:
        key = it.get("_parent", "")
        groups.setdefault(key, []).append(it)

    结果 = []
    for 父名, 组 in groups.items():
        礼包 = [i for i in 组 if i["类型"] == -1]
        其他 = [i for i in 组 if i["类型"] != -1]

        if len(礼包) >= 2:
            最早 = min(礼包, key=lambda x: x["开始时间"])
            最晚 = max(礼包, key=lambda x: x["结束时间"])
            结果.append({
                "名称": f"{父名} 礼包" if 父名 else "礼包",
                "开始时间": 最早["开始时间"],
                "结束时间": 最晚["结束时间"],
                "类型": -1,
                "_parent": 父名,
            })
        else:
            结果.extend(礼包)
        结果.extend(其他)
    return 结果


# ---------- 去重排序 ----------

def _提取干员(名称: str) -> str:
    """从卡池名称中提取 · 后面的干员名，用于卡池去重"""
    if " · " in 名称:
        return 名称.split(" · ", 1)[1]
    return ""


def 去重排序(活动列表: list[dict]) -> list[dict]:
    """按干员名+时间去重（卡池），按开始时间排序"""
    seen = set()
    去重后 = []
    for a in 活动列表:
        if a["类型"] == 0:
            干员 = _提取干员(a["名称"])
            key = (干员, a["开始时间"], a["结束时间"], a["类型"]) if 干员 else (a["名称"], a["开始时间"], a["结束时间"], a["类型"])
        else:
            key = (a["名称"], a["开始时间"], a["结束时间"], a["类型"])
        if key not in seen:
            seen.add(key)
            去重后.append(a)
    去重后.sort(key=lambda e: e["开始时间"])
    return 去重后


# ---------- 增量存储 ----------

def _卡池合并key(条目: dict) -> str:
    """卡池统一键名：优先用干员名，否则用名称"""
    if 条目["类型"] == 0:
        干员 = _提取干员(条目["名称"])
        if 干员:
            return 干员
    return 条目["名称"]


def 合并保存CSV(新活动列表: list[dict], 输出路径: str | Path, 现在时间: str) -> str:
    """增量保存：读已有数据 + 新数据覆盖 + 清理过期条目 + 写回

    store 带"来源"列（条目出自哪个活动公告；卡池和 API 兜底条目为空）。
    来源非空说明该公告解析成功过，主流程据此跳过重复解析——公告里的
    剿灭/保全等长期任务因此只解析一次就能一直保留到过期。
    """
    路径 = Path(输出路径)
    字段 = ["名称", "开始时间", "结束时间", "类型", "来源"]

    已有: dict[str, dict] = {}
    if 路径.exists():
        with open(路径, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if not row.get("名称", "").strip():
                    continue
                类型 = int(row["类型"])
                键名 = 干员名 if (干员名 := _提取干员(row["名称"])) and 类型 == 0 else row["名称"]
                已有[键名] = {
                    "名称": row["名称"],
                    "开始时间": row["开始时间"],
                    "结束时间": row["结束时间"],
                    "类型": 类型,
                    "来源": row.get("来源", ""),
                }

    for a in 新活动列表:
        已有[_卡池合并key(a)] = {
            "名称": a["名称"],
            "开始时间": a["开始时间"],
            "结束时间": a["结束时间"],
            "类型": a["类型"],
            "来源": a.get("_parent", ""),
        }

    清理线 = (
        datetime.strptime(现在时间, "%Y-%m-%d %H:%M:%S") - timedelta(days=过期保留天数)
    ).strftime("%Y-%m-%d %H:%M:%S")
    所有 = [r for r in 已有.values() if r["结束时间"] >= 清理线]
    删了 = len(已有) - len(所有)
    if 删了:
        logger.info("  清理过期条目 %d 条（结束时间早于 %s）", 删了, 清理线)

    所有.sort(key=lambda e: e["开始时间"])
    with open(路径, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=字段)
        writer.writeheader()
        writer.writerows(所有)
    return str(路径)
