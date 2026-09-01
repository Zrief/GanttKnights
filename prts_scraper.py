"""CLI 入口 — 独立运行时用，main.py 直接调用各模块"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from src.网络_prts import 获取事件列表, 获取公告页
from src.解析_公告 import 解析分区
from src.解析_事件 import (
    分类事件,
    解析API时间戳,
    合并商店,
    合并长期活动,
    去重排序,
    保存CSV,
)

logger = logging.getLogger("prts_scraper")

输出文件 = Path(__file__).resolve().parent / "数据" / "prts_events.csv"
长期活动文件 = Path(__file__).resolve().parent / "数据" / "长期活动.csv"

现在时间 = datetime.now()
现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")


def 爬取(限制: int = 10) -> list[dict]:
    """串联 获取→解析→合并→排序 的完整流程"""
    api原始 = 获取事件列表(限制)
    if not api原始:
        logger.warning("API 未返回数据")
        return []

    活动列表: list[dict] = []

    for idx, (事件名, 条目) in enumerate(api原始):
        属性 = 条目.get("printouts", {})
        开始 = 解析API时间戳(属性.get("活动开始时间", [None])[0]) if 属性.get("活动开始时间") else None
        结束 = 解析API时间戳(属性.get("活动结束时间", [None])[0]) if 属性.get("活动结束时间") else None

        if not (开始 and 结束 and 结束 > 现在字符串):
            continue

        网页 = 获取公告页(事件名)
        if 网页 is None:
            if 分类事件(事件名=事件名) == 99:
                活动列表.append({
                    "名称": 事件名, "开始时间": 开始, "结束时间": 结束,
                    "类型": 99, "_parent": 事件名,
                })
                logger.info("  [%d] %s → 长期活动 (API)", idx + 1, 事件名)
            else:
                logger.info("  [%d] %s 无公告页，跳过", idx + 1, 事件名)
            continue

        子活动 = 解析分区(网页, 事件名)
        if 子活动:
            活动列表.extend(子活动)
            logger.info("  [%d] %s → %d 条子活动", idx + 1, 事件名, len(子活动))
        else:
            logger.info("  [%d] %s 有公告页但无有效子活动", idx + 1, 事件名)

    活动列表 = 合并长期活动(活动列表, 长期活动文件, 现在字符串)
    活动列表 = 合并商店(活动列表)
    活动列表 = 去重排序(活动列表)
    return 活动列表


def run(输出路径: str | Path | None = None, 限制: int = 10) -> int:
    """供 main.py 调用的入口，返回保存条数"""
    try:
        activities = 爬取(限制)
    except Exception:
        logger.exception("爬取失败")
        return 0
    if not activities:
        logger.info("未获取到有效活动")
        return 0
    保存CSV(activities, 输出路径 or 输出文件)
    logger.info("已保存 %d 条活动", len(activities))
    return len(activities)


def main():
    限制 = 10
    if len(sys.argv) > 1:
        try:
            限制 = max(1, int(sys.argv[1]))
        except ValueError:
            pass

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
    )
    logger.info("正在获取活动数据 (limit=%d)...", 限制)

    activities = 爬取(限制)
    if not activities:
        logger.warning("未获取到活动数据")
        sys.exit(1)

    保存CSV(activities, 输出文件)
    print()
    类型名 = {0: "卡池", 1: "活动", 2: "福利", -1: "商店", 99: "长期"}
    for e in activities:
        状态 = (
            "进行中"
            if e["开始时间"] <= 现在字符串 <= e["结束时间"]
            else ("即将开始" if e["开始时间"] > 现在字符串 else "已结束")
        )
        tn = 类型名.get(e["类型"], "?")
        print(f"  [{状态}] [{tn}] {e['名称']}")
        print(f"           {e['开始时间']} ~ {e['结束时间']}")


if __name__ == "__main__":
    main()
