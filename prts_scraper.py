"""对账工具 — 单独跑一次爬取，把活动列表打到控制台（只读，不落盘）。

与 `cli.py` 的分工：`cli.py` 是**出图**入口（会更新数据、渲染产物）；这里只回答
"PRTS 现在返回了哪些活动、时间是什么"，用来人工核对解析结果，不写任何文件。

时间在函数内求值，不在模块级冻结：本模块的 `爬取()` 可能被当包导入复用，
那样"导入即取时间"会在这类长驻场景里变成陈旧值（同 `src/流水线.py::今天写过` 的约定）。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from src.获取_prts import 获取事件列表
from src.解析_API活动 import API转活动列表
from src.汇总_活动 import (
    合并商店,
    去重排序,
)

logger = logging.getLogger("prts_scraper")


def 爬取(限制: int = 10, 回溯已结束: bool = False,
         现在时间: datetime | None = None) -> list[dict]:
    """串联 获取→解析→合并→排序 的完整流程（只读，不落盘）"""
    现在时间 = 现在时间 or datetime.now()
    现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")
    api原始 = 获取事件列表(限制)
    if not api原始:
        logger.warning("API 未返回数据")
        return []

    活动列表 = API转活动列表(api原始, 现在字符串, 回溯已结束=回溯已结束)
    活动列表 = 合并商店(活动列表)
    活动列表 = 去重排序(活动列表)
    return 活动列表


def main():
    回溯已结束 = "--bootstrap" in sys.argv
    限制 = 10
    for arg in sys.argv[1:]:
        if arg.isdigit():
            限制 = max(1, int(arg))

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
    )
    logger.info("正在获取活动数据 (limit=%d)...", 限制)

    现在时间 = datetime.now()
    现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")
    activities = 爬取(限制, 回溯已结束=回溯已结束, 现在时间=现在时间)
    if not activities:
        logger.warning("未获取到活动数据")
        sys.exit(1)

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
