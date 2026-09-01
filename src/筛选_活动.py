from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
from dateutil.parser import parse

from src.config import settings

logger = logging.getLogger(__name__)


def preprocess_data(
    data_path: str | None = None,
    all_data_path: str | None = None,
    *,
    now: datetime | None = None,
    left_border: datetime | None = None,
    right_border: datetime | None = None,
) -> pd.DataFrame:
    all_data_path = all_data_path or settings.all_data_path
    data_path = data_path or settings.data_path
    now = now or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    left_border = left_border or now - timedelta(days=settings.left_offset_days)
    right_border = right_border or now + timedelta(
        days=settings.right_offset_days - now.weekday()
    )

    try:
        df = pd.read_csv(all_data_path)
    except FileNotFoundError:
        logger.error("数据文件不存在: %s", all_data_path)
        return pd.DataFrame(columns=["名称", "开始时间", "结束时间", "类型"])
    except Exception:
        logger.exception("读取数据文件失败: %s", all_data_path)
        return pd.DataFrame(columns=["名称", "开始时间", "结束时间", "类型"])

    if df.empty:
        logger.warning("数据文件为空: %s", all_data_path)
        return df

    col_name = df.columns[0]
    col_start = df.columns[1]
    col_end = df.columns[2]
    col_type = df.columns[3]

    try:
        df[col_start] = [parse(str(ii)) for ii in df[col_start]]
        df[col_end] = [parse(str(ii)) for ii in df[col_end]]
    except Exception:
        logger.exception("日期解析失败")

    df = df.loc[df[col_end] > now + timedelta(hours=settings.future_buffer_hours)]
    df = df.loc[df[col_start] < right_border]
    df = df.sort_values(
        by=[col_type, col_end, col_start], ascending=False
    )
    df = df[df[col_type] != -1]

    unclassified = df[df[col_type] == -1]
    if not unclassified.empty:
        logger.info("未归类的活动:\n%s", unclassified.to_string())

    try:
        df.to_csv(data_path, index=False)
    except Exception:
        logger.exception("保存过滤后数据失败: %s", data_path)

    if df.empty:
        logger.warning(
            "过滤后无近期活动数据 (窗口 %s ~ %s)", left_border.date(), right_border.date()
        )

    return df
