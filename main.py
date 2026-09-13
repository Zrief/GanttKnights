"""CLI 入口 — 生成明日方舟近期活动甘特图（数据每天只爬一次）。

用法:
    python main.py                       # 生成 Gantt.jpg（数据每天只爬一次）
    python main.py --force               # 强制重新爬取
    python main.py --bootstrap --force   # 数据初次建立：回溯已结束活动的公告

编排逻辑（"今天要不要爬"这类策略）在本文件；实际渲染在 src/流水线.py，
与 AstrBot 插件入口（astrbot_plugin.py）共用同一条流水线。
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from src.config import settings, setup_logging
from src.流水线 import (
    今天写过,
    更新增预告,
    更新数据,
    render_once,
)

logger = logging.getLogger("ganttknights")


def main(force: bool = False, bootstrap: bool = False, 现在时间: datetime | None = None) -> None:
    """CLI 编排：先按"每天只做一次"决定是否更新数据与新增预告，再渲染。

    时间在每次调用时求值：CLI 下与模块导入时刻等价，
    但在长驻进程（AstrBot 插件）里必须是"本次调用"的时间。
    """
    现在时间 = 现在时间 or datetime.now()
    现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")

    # 第 1 步：获取最新活动数据（每天只爬一次，--force 可强制重新爬取）
    if not force and 今天写过(Path(settings.all_data_path), 现在时间):
        logger.info("今天已爬取过，跳过更新（--force 可强制更新）")
    else:
        更新数据(现在字符串, 回溯已结束=bootstrap)

    # 第 2 步：新增预告（凭证/时装/模组）与活动数据各管各的新鲜度
    # —— 活动数据当天已爬过时，预告仍要确认是今天的，否则底栏会整区缺失
    if not force and 今天写过(Path(settings.new_items_path), 现在时间):
        logger.info("今天已更新过新增预告，跳过")
    else:
        try:
            更新增预告(现在时间, 现在字符串)
        except Exception:
            logger.exception("新增预告获取失败")

    # 第 3~6 步交给流水线：过滤 → 主题 → 渲染 → 警告
    结果 = render_once(
        现在时间=现在时间,
        强制刷新=False,          # 数据新鲜度已在上两步判定
        控制台打印警告=True,     # CLI 把警告打到 stdout
    )
    return 结果


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="明日方舟近期活动甘特图生成工具")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新爬取数据（忽略'今天已爬取过'检查）",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="回溯已结束活动的公告，补录剿灭/保全等长期任务（数据初次建立时跑一次即可，需配合 --force）",
    )
    args = parser.parse_args()
    setup_logging()
    main(force=args.force, bootstrap=args.bootstrap)
