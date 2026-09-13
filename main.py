from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from random import choice

from src.config import settings, setup_logging
from src.获取_prts import 获取事件列表, 获取首页, 下载图片
from src.解析_API活动 import API转活动列表
from src.解析_首页 import 解析新增内容, 预告键
from src.汇总_活动 import (
    合并商店,
    去重排序,
    合并保存CSV,
)
from src.筛选_活动 import preprocess_data
from src.绘图_排版 import 建分区, 绘制甘特图
from src.绘图_主题 import 建主题
from src.解析_卡池 import 抓取卡池一览

logger = logging.getLogger("ganttknights")

现在时间 = datetime.now()
现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")


def 随机背景() -> str:
    bg列表 = list(Path(settings.bg_dir).glob("*"))
    if not bg列表:
        logger.error("背景图目录为空: %s", settings.bg_dir)
        raise SystemExit(1)
    return str(choice(bg列表))


def _写新增预告(新增: dict) -> None:
    Path(settings.new_items_path).write_text(
        json.dumps(新增, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _清理图标缓存(缓存目录: Path, 引用名们: set[str]) -> None:
    """删除不再被当前预告引用的孤儿图标"""
    删了 = 0
    for f in 缓存目录.iterdir():
        if f.is_file() and f.name not in 引用名们:
            f.unlink()
            删了 += 1
    if 删了:
        logger.info("  清理孤儿图标 %d 个", 删了)


def _今天写过(路径: Path) -> bool:
    """文件存在且是今天写的 —— 用于"每天只做一次"的新鲜度检查"""
    return 路径.exists() and datetime.fromtimestamp(路径.stat().st_mtime).date() == 现在时间.date()


def 更新增预告() -> dict:
    """抓首页新增时装/模组/凭证，图标缓存到 数据/图片缓存/，写 新增预告.json"""
    首页 = 获取首页()
    if 首页 is None:
        logger.warning("首页获取失败，沿用上次预告数据")
        return {}
    新增 = 解析新增内容(首页)
    if not any(新增.values()):
        # 覆盖为带时间戳的空预告，避免警告里长期播报早已结束的上新
        logger.warning("首页未解析到新增内容，预告清空")
        新增 = {键: [] for 键 in 预告键}
        新增["更新时间"] = 现在字符串
        _写新增预告(新增)
        return 新增

    缓存目录 = Path(settings.icon_cache_dir)
    缓存目录.mkdir(parents=True, exist_ok=True)
    for 条目们 in 新增.values():
        for 条目 in 条目们:
            目标 = 缓存目录 / 条目["图标文件名"]
            if 下载图片(条目["图标"], 目标):
                条目["图标文件"] = 条目["图标文件名"]

    新增["更新时间"] = 现在字符串
    _写新增预告(新增)
    引用名们 = {t["图标文件名"] for ts in 新增.values() if isinstance(ts, list) for t in ts}
    _清理图标缓存(缓存目录, 引用名们)
    logger.info(
        "新增预告: " + " / ".join(f"{键} {len(新增[键])}" for 键 in 预告键) + "，图标缓存于 %s",
        缓存目录,
    )
    return 新增


def 读新增预告() -> dict:
    """读 数据/新增预告.json；缺失或损坏时按空预告处理（底栏上新区留空）"""
    路径 = Path(settings.new_items_path)
    if not 路径.exists():
        logger.warning("新增预告不存在，底栏上新区留空: %s", 路径)
        return {}
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("新增预告解析失败，底栏上新区留空")
        return {}


def 补下载图标(分区: list[tuple[str, list[dict]]]) -> None:
    """底栏条目的头像补齐到 数据/图片缓存/（已存在的跳过），失败只记数不中断"""
    缓存目录 = Path(settings.icon_cache_dir)
    缓存目录.mkdir(parents=True, exist_ok=True)
    失败 = 0
    for _, 条目们 in 分区:
        for 条目 in 条目们:
            url, 文件名 = 条目.get("图标"), 条目.get("图标文件名")
            if not url or not 文件名:
                continue
            if not 下载图片(url, 缓存目录 / 文件名):
                失败 += 1
    if 失败:
        logger.warning("%d 个头像下载失败，渲染时会跳过", 失败)


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


def 更新数据(回溯已结束: bool = False) -> None:
    """第 1 步：爬取 + 解析 + 合并 + 保存活动数据

    首页新增预告（凭证/时装/模组）不在活动数据里，由 main 单独按天刷新。
    """
    try:
        api原始 = 获取事件列表(settings.api_limit)
    except Exception:
        logger.exception("获取事件列表失败（网络可能断开了）")
        return
    if not api原始:
        logger.warning("API 未返回数据")
        return

    活动列表 = API转活动列表(api原始, 现在字符串, 读取已解析来源(), 回溯已结束=回溯已结束)

    活动列表 = 合并商店(活动列表)

    # 卡池数据
    try:
        活动列表.extend(抓取卡池一览())
    except Exception:
        logger.exception("获取卡池数据失败")

    活动列表 = 去重排序(活动列表)

    if 活动列表:
        合并保存CSV(活动列表, settings.all_data_path, 现在字符串)
        logger.info("数据更新完成，共 %d 条活动", len(活动列表))
    else:
        logger.warning("未获取到有效活动")


def main(force: bool = False, bootstrap: bool = False):
    # 第 1 步：获取最新活动数据（每天只爬一次，--force 可强制重新爬取）
    if not force and _今天写过(Path(settings.all_data_path)):
        logger.info("今天已爬取过，跳过更新（--force 可强制更新）")
    else:
        更新数据(回溯已结束=bootstrap)

    # 第 2 步：新增预告（凭证/时装/模组）与活动数据各管各的新鲜度
    # —— 活动数据当天已爬过时，预告仍要确认是今天的，否则底栏会整区缺失
    if not force and _今天写过(Path(settings.new_items_path)):
        logger.info("今天已更新过新增预告，跳过")
    else:
        try:
            更新增预告()
        except Exception:
            logger.exception("新增预告获取失败")

    # 第 3 步：按时间窗口过滤
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

    # 第 4 步：随机背景图 → 整套配色由这一张图推导
    背景路径 = 随机背景()
    主题 = 建主题(背景路径)

    # 第 5 步：底栏上新区（凭证/时装/模组）+ 排版绘图
    新增内容 = 读新增预告()
    分区 = 建分区(新增内容)
    try:
        补下载图标(分区)
    except Exception:
        logger.exception("头像补下载失败，缺图标的条目按无图渲染")

    try:
        概况 = 绘制甘特图(
            settings.output_path, 分区, df, 主题, 左边界, 右边界, 背景路径, 现在时间,
        )
        logger.info("图表已保存至 %s（%s）", settings.output_path, 概况)
    except Exception:
        logger.exception("绘制图表失败")

    # 第 6 步：生成过期警告输出
    from src.生成_警告 import 生成警告
    try:
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
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="回溯已结束活动的公告，补录剿灭/保全等长期任务（数据初次建立时跑一次即可，需配合 --force）",
    )
    args = parser.parse_args()
    setup_logging()
    main(force=args.force, bootstrap=args.bootstrap)
