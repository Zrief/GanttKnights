from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from random import choice

import matplotlib.pyplot as plt

from src.config import settings, setup_logging
from src.获取_prts import 获取事件列表, 获取首页, 下载图片
from src.解析_API活动 import API转活动列表
from src.解析_首页 import 解析新增内容
from src.汇总_活动 import (
    合并商店,
    去重排序,
    合并保存CSV,
)
from src.筛选_活动 import preprocess_data
from src.绘图_图表 import plot_events, set_x_ticks, 创建画布
from src.绘图_颜色 import extract_main_colors
from src.解析_卡池 import 抓取卡池一览

logger = logging.getLogger("ganttknights")

现在时间 = datetime.now()
现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")


def 随机路径() -> tuple[str, str]:
    bg列表 = list(Path(settings.bg_dir).glob("*"))
    tx列表 = list(Path(settings.texture_dir).glob("*"))
    if not bg列表:
        logger.error("背景图目录为空: %s", settings.bg_dir)
        raise SystemExit(1)
    if not tx列表:
        logger.error("纹理目录为空: %s", settings.texture_dir)
        raise SystemExit(1)
    return str(choice(bg列表)), str(choice(tx列表))


def 更新增预告() -> dict:
    """抓首页新增时装/模组，图标缓存到 数据/图片缓存/，写 新增预告.json"""
    首页 = 获取首页()
    if 首页 is None:
        logger.warning("首页获取失败，跳过新增预告")
        return {}
    新增 = 解析新增内容(首页)
    if not any(新增.values()):
        logger.warning("首页未解析到新增时装/模组")
        return 新增

    缓存目录 = Path(settings.icon_cache_dir)
    缓存目录.mkdir(parents=True, exist_ok=True)
    for 条目们 in 新增.values():
        for 条目 in 条目们:
            目标 = 缓存目录 / 条目["图标文件名"]
            if 下载图片(条目["图标"], 目标):
                条目["图标文件"] = str(目标)

    Path(settings.new_items_path).write_text(
        json.dumps(新增, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "新增预告: 时装 %d / 模组 %d，图标缓存于 %s",
        len(新增["时装"]), len(新增["模组"]), 缓存目录,
    )
    return 新增


def 读取已解析来源() -> set[str]:
    """从 store 读出公告解析成功过的活动名，用于跳过重复解析"""
    来源: set[str] = set()
    路径 = Path(settings.all_data_path)
    if not 路径.exists():
        return 来源
    try:
        with open(路径, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                值 = (row.get("来源") or "").strip()
                if 值:
                    来源.add(值)
    except Exception:
        logger.exception("读取已解析来源失败")
    return 来源


def 更新数据() -> None:
    """第 1 步：爬取 + 解析 + 合并 + 保存"""
    try:
        api原始 = 获取事件列表(settings.api_limit)
    except Exception:
        logger.exception("获取事件列表失败（网络可能断开了）")
        return
    if not api原始:
        logger.warning("API 未返回数据")
        return

    活动列表 = API转活动列表(api原始, 现在字符串, 读取已解析来源())

    活动列表 = 合并商店(活动列表)

    # 卡池数据
    try:
        活动列表.extend(抓取卡池一览())
    except Exception:
        logger.exception("获取卡池数据失败")

    # 首页新增时装/模组（图标缓存到本地）
    try:
        更新增预告()
    except Exception:
        logger.exception("新增预告获取失败")

    活动列表 = 去重排序(活动列表)

    if 活动列表:
        合并保存CSV(活动列表, settings.all_data_path, 现在字符串)
        logger.info("数据更新完成，共 %d 条活动", len(活动列表))
    else:
        logger.warning("未获取到有效活动")


def main(force: bool = False):
    # 第 1 步：获取最新活动数据（每天只爬一次，--force 可强制重新爬取）
    数据路径 = Path(settings.all_data_path)
    if (
        not force
        and 数据路径.exists()
        and datetime.fromtimestamp(数据路径.stat().st_mtime).date() == 现在时间.date()
    ):
        logger.info("今天已爬取过，跳过更新（--force 可强制更新）")
    else:
        更新数据()

    # 第 2 步：按时间窗口过滤
    今天 = 现在时间.replace(hour=0, minute=0, second=0, microsecond=0)
    左边界 = 今天 - timedelta(days=settings.left_offset_days)
    右边界 = 今天 + timedelta(days=settings.right_offset_days - 今天.weekday())

    df = preprocess_data(
        all_data_path=settings.all_data_path,
        now=今天,
        left_border=左边界,
        right_border=右边界,
    )
    if df.empty:
        logger.warning("没有即将开始或进行中的活动，请更新数据源。")

    # 第 3 步：选择背景图片 + 提取颜色
    背景路径, 纹理路径 = 随机路径()
    颜色 = extract_main_colors(背景路径, settings.num_colors)

    # 第 4 步：绘图 + 保存
    总小时 = (右边界 - 左边界).total_seconds() / 3600
    fig, ax = 创建画布(背景路径, 纹理路径, len(df))
    plot_events(df, 左边界, 右边界, 颜色, ax=ax)
    ax.set_title("近期活动一览", color="white")
    set_x_ticks(ax, 左边界, 右边界)
    ax.set_yticks([])
    ax.set_xlim(0, 总小时)
    ax.set_ylim(-0.5, max(len(df) - 0.5, 0))
    ax.spines[["right", "left"]].set_visible(False)
    fig.tight_layout(pad=0.5)

    try:
        fig.savefig(settings.output_path)
        logger.info("图表已保存至 %s", settings.output_path)
    except Exception:
        logger.exception("保存图表失败")
    finally:
        plt.close(fig)

    # 第 5 步：生成过期警告输出
    from src.生成_警告 import 生成警告
    try:
        新增内容 = {}
        if Path(settings.new_items_path).exists():
            新增内容 = json.loads(Path(settings.new_items_path).read_text(encoding="utf-8"))
        警告 = 生成警告(df, 提醒天数=3, 新增内容=新增内容)
        if 警告:
            print("\n" + "=" * 54)
            print(警告)
            print("=" * 54)
        else:
            警告 = "博士，罗德岛当前所有行动均在正常排期内，无需提醒。"
        Path(settings.warning_path).write_text(警告, encoding="utf-8")
        logger.info("过期警告已保存至 %s", settings.warning_path)
    except Exception:
        logger.exception("生成警告失败")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="明日方舟近期活动甘特图生成工具")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新爬取数据（忽略'今天已爬取过'检查）",
    )
    args = parser.parse_args()
    setup_logging()
    main(force=args.force)
