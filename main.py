from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from random import choice

import matplotlib.pyplot as plt

from src.config import settings, setup_logging
from src.网络_prts import 获取事件列表, 获取公告页
from src.解析_公告 import 解析分区
from src.解析_事件 import (
    解析API时间戳,
    分类事件,
    合并商店,
    合并长期活动,
    去重排序,
    合并保存CSV,
)
from src.筛选_活动 import preprocess_data
from src.绘图_图表 import plot_events, set_x_ticks, 创建画布
from src.绘图_颜色 import extract_main_colors
from src.解析_卡池 import 抓取限时寻访, 抓取常驻寻访, 合并卡池CSV

logger = logging.getLogger("ganttknights")

现在时间 = datetime.now()
现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")
长期活动路径 = Path(__file__).resolve().parent / "数据" / "长期活动.csv"


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


def 更新数据() -> None:
    """第 1 步：爬取 + 解析 + 合并 + 保存"""
    api原始 = 获取事件列表(settings.api_limit)
    if not api原始:
        logger.warning("API 未返回数据")
        return

    活动列表 = []
    for idx, (事件名, 条目) in enumerate(api原始):
        属性 = 条目.get("printouts", {})
        开始 = 解析API时间戳(属性.get("活动开始时间", [None])[0]) if 属性.get("活动开始时间") else None
        结束 = 解析API时间戳(属性.get("活动结束时间", [None])[0]) if 属性.get("活动结束时间") else None
        if not (开始 and 结束 and 结束 > 现在字符串):
            continue

        网页 = 获取公告页(事件名)
        if 网页 is None:
            if 分类事件(事件名=事件名) == 99:
                活动列表.append({"名称": 事件名, "开始时间": 开始, "结束时间": 结束, "类型": 99, "_parent": 事件名})
                logger.info("  [%d] %s → 长期活动", idx + 1, 事件名)
            else:
                logger.info("  [%d] %s 无公告页，跳过", idx + 1, 事件名)
            continue

        子活动 = 解析分区(网页, 事件名)
        if 子活动:
            活动列表.extend(子活动)
            logger.info("  [%d] %s → %d 条子活动", idx + 1, 事件名, len(子活动))
        else:
            logger.info("  [%d] %s 有公告页但无有效子活动", idx + 1, 事件名)

    活动列表 = 合并长期活动(活动列表, 长期活动路径, 现在字符串)
    活动列表 = 合并商店(活动列表)

    # 卡池数据
    卡池路径 = Path(__file__).resolve().parent / "数据" / "卡池.csv"
    try:
        活动列表.extend(抓取限时寻访())
        活动列表.extend(抓取常驻寻访())
        活动列表 = 合并卡池CSV(活动列表, 卡池路径, 现在字符串)
    except Exception:
        logger.exception("获取卡池数据失败")

    活动列表 = 去重排序(活动列表)

    if 活动列表:
        合并保存CSV(活动列表, settings.all_data_path)
        logger.info("数据更新完成，共 %d 条活动", len(活动列表))
    else:
        logger.warning("未获取到有效活动")


def main():
    # 第 1 步：获取最新活动数据
    更新数据()

    # 第 2 步：按时间窗口过滤
    今天 = 现在时间.replace(hour=0, minute=0, second=0, microsecond=0)
    左边界 = 今天 - timedelta(days=settings.left_offset_days)
    右边界 = 今天 + timedelta(days=settings.right_offset_days - 今天.weekday())

    df = preprocess_data(
        all_data_path=settings.all_data_path,
        data_path=settings.data_path,
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


if __name__ == "__main__":
    setup_logging()
    main()
