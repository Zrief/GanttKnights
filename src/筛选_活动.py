from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

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

    col_start = df.columns[1]
    col_end = df.columns[2]
    col_type = df.columns[3]

    # 无法解析的行丢弃而不是让整个流程崩溃
    df[col_start] = pd.to_datetime(df[col_start], errors="coerce")
    df[col_end] = pd.to_datetime(df[col_end], errors="coerce")
    坏行 = df[col_start].isna() | df[col_end].isna()
    if 坏行.any():
        logger.warning("丢弃 %d 条日期无法解析的活动:\n%s", 坏行.sum(), df[坏行].to_string())
        df = df[~坏行]

    df = df.loc[df[col_end] > now + timedelta(hours=settings.future_buffer_hours)]
    df = df.loc[df[col_start] < right_border]
    df = df.sort_values(
        by=[col_type, col_end, col_start], ascending=False
    )
    df = df[df[col_type] != -1]

    try:
        df.to_csv(data_path, index=False)
    except Exception:
        logger.exception("保存过滤后数据失败: %s", data_path)

    if df.empty:
        logger.warning(
            "过滤后无近期活动数据 (窗口 %s ~ %s)", left_border.date(), right_border.date()
        )

    return df
