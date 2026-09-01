"""数据层 — API 响应解析、合并长期活动、去重排序、存 CSV"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger("src.解析")

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
    (["战斗", "SideStory", "故事集", "资源收集", "复刻"], 1),
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
    """把 PRTS API 的 timestamp 转成 'YYYY-MM-DD HH:MM:00'"""
    if isinstance(ts_info, dict):
        parts = ts_info.get("raw", "").split("/")
        if len(parts) >= 6:
            _, y, m, d, h, mi = parts[:6]
            return f"{y}-{m.zfill(2)}-{d.zfill(2)} {h.zfill(2)}:{mi.zfill(2)}:00"
    return None


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

def 去重排序(活动列表: list[dict]) -> list[dict]:
    """按名称+时间去重，按开始时间排序"""
    seen = set()
    去重后 = []
    for a in 活动列表:
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


def 合并保存CSV(新活动列表: list[dict], 输出路径: str | Path) -> str:
    """合并式保存：读已有数据 + 新数据按名称覆盖 + 写回"""
    路径 = Path(输出路径)
    # 读已有数据
    已有: dict[str, dict] = {}
    if 路径.exists():
        with open(路径, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("名称", "").strip():
                    已有[row["名称"]] = {
                        "名称": row["名称"],
                        "开始时间": row["开始时间"],
                        "结束时间": row["结束时间"],
                        "类型": int(row["类型"]),
                    }
    # 新数据按名称覆盖
    for a in 新活动列表:
        已有[a["名称"]] = {
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
