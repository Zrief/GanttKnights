"""汇总层 — 合并商店与长期活动、去重排序、活动数据 CSV 读写"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger("src.汇总")


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


# ---------- 合并长期活动 ----------

def 合并长期活动(活动列表: list[dict], 文件路径: str | Path, 现在时间: str) -> list[dict]:
    """从 长期活动.csv 合并尚未结束的长期活动"""
    路径 = Path(文件路径)
    if not 路径.exists():
        return 活动列表

    try:
        with open(路径, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            已有名称 = {a["名称"] for a in 活动列表}
            for row in reader:
                名称 = row.get("名称", "").strip()
                if not 名称 or 名称 in 已有名称:
                    continue
                if row.get("结束时间", "") >= 现在时间:
                    活动列表.append({
                        "名称": 名称,
                        "开始时间": row["开始时间"],
                        "结束时间": row["结束时间"],
                        "类型": int(row["类型"]),
                        "_parent": "",
                    })
                    已有名称.add(名称)
            logger.info("  合并长期活动: %s", 路径.name)
    except Exception:
        logger.exception("读取长期活动文件失败: %s", 路径)
    return 活动列表


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
    for a in 去重后:
        a.pop("_parent", None)
    return 去重后


# ---------- 保存 CSV ----------

def 保存CSV(活动列表: list[dict], 输出路径: str | Path) -> str:
    路径 = Path(输出路径)
    with open(路径, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["名称", "开始时间", "结束时间", "类型"])
        writer.writeheader()
        writer.writerows(活动列表)
    return str(路径)


def _卡池合并key(条目: dict) -> str:
    """卡池统一键名：优先用干员名，否则用名称"""
    if 条目["类型"] == 0:
        干员 = _提取干员(条目["名称"])
        if 干员:
            return 干员
    return 条目["名称"]


def 合并保存CSV(新活动列表: list[dict], 输出路径: str | Path) -> str:
    """合并式保存：读已有数据 + 新数据覆盖 + 写回（卡池按干员名去重）"""
    路径 = Path(输出路径)
    # 读已有数据
    已有: dict[str, dict] = {}
    if 路径.exists():
        with open(路径, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("名称", "").strip():
                    类型 = int(row["类型"])
                    键名 = 干员名 if (干员名 := _提取干员(row["名称"])) and 类型 == 0 else row["名称"]
                    已有[键名] = {
                        "名称": row["名称"],
                        "开始时间": row["开始时间"],
                        "结束时间": row["结束时间"],
                        "类型": 类型,
                    }
    # 新数据覆盖
    for a in 新活动列表:
        键名 = _卡池合并key(a)
        已有[键名] = {
            "名称": a["名称"],
            "开始时间": a["开始时间"],
            "结束时间": a["结束时间"],
            "类型": a["类型"],
        }
    # 排序后写回
    所有 = list(已有.values())
    所有.sort(key=lambda e: e["开始时间"])
    with open(路径, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["名称", "开始时间", "结束时间", "类型"])
        writer.writeheader()
        writer.writerows(所有)
    return str(路径)
