from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
from dateutil.parser import parse

logger = logging.getLogger(__name__)


def transform_data(input_str: str):
    try:
        input_str = input_str.replace("日", " ").replace("月", "-")
        input_str = input_str.replace("年", "-")
        return parse(input_str)
    except Exception:
        return pd.NaT


def read_data(file_path: str) -> pd.DataFrame | None:
    try:
        return pd.read_csv(file_path)
    except FileNotFoundError:
        logger.error("文件不存在: %s", file_path)
        return None
    except Exception:
        logger.exception("读取文件失败: %s", file_path)
        return None


def filter_non_null_stars(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["六星干员"].isnull()]


def process_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.iloc[:, 1] = [transform_data(ii) for ii in df.iloc[:, 1]]
    df.iloc[:, 2] = [transform_data(ii) for ii in df.iloc[:, 2]]
    return df


def process_name_column(df: pd.DataFrame) -> pd.DataFrame:
    df.iloc[:, 0] = (
        df.iloc[:, 0]
        .str.replace("常驻标准寻访", "【标准池】")
        .str.replace("中坚寻访", "【中坚池】")
    )
    mask = df.iloc[:, 0].str.contains("限定寻访·庆典")
    df.loc[mask, df.columns[0]] = "【限定池】"

    df.iloc[:, 0] = df.iloc[:, 0] + df.iloc[:, 3].str.replace("[限定]", "")

    df.rename(columns={"活动类型": "名称"}, inplace=True)
    df["类型"] = 0
    df = df.drop("六星干员", axis=1)
    return df


def merge_dataframes(df1: pd.DataFrame, df2: pd.DataFrame) -> pd.DataFrame:
    df = pd.concat([df1, df2], axis=0, ignore_index=True)
    df = df.convert_dtypes()
    df = df.drop_duplicates(df.columns[0])
    df["开始时间"] = pd.to_datetime(df["开始时间"], errors="coerce")
    df = df.sort_values(by="开始时间", ascending=True)
    return df


def save_data(df: pd.DataFrame, file_path: str) -> bool:
    try:
        df.to_csv(file_path, index=False)
        return True
    except Exception:
        logger.exception("保存文件失败: %s", file_path)
        return False


def process_data(
    skdpath: str = "arknights_events.csv",
    oppath: str = "爬虫/卡池.csv",
) -> pd.DataFrame | None:
    script_dir = Path(__file__).resolve().parent.parent
    skd_full = script_dir / skdpath
    op_full = script_dir / oppath

    df = read_data(str(skd_full))
    if df is None:
        logger.warning("森空岛数据不存在，跳过卡池合并")
        return None

    df = filter_non_null_stars(df)
    df = process_date_columns(df)
    df = process_name_column(df)

    df2 = read_data(str(op_full))
    if df2 is None:
        logger.warning("本地卡池数据不存在，仅使用爬虫数据")
        merged = df
    else:
        merged = merge_dataframes(df2, df)

    if not save_data(merged, str(op_full)):
        return merged

    final_path = script_dir / "所有活动数据.csv"
    existing = read_data(str(final_path))
    if existing is not None:
        merged = merge_dataframes(existing, merged)

    if not save_data(merged, str(final_path)):
        logger.error("最终数据保存失败: %s", final_path)

    logger.info("数据合并完成，共 %d 条记录", len(merged))
    return merged


if __name__ == "__main__":
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    result = process_data()
    if result is None:
        logger.warning("未获取到新数据，原有数据不受影响")
    sys.exit(0)
