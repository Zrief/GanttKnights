from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

from dateutil.parser import parse

logger = logging.getLogger(__name__)

ACTIVITY_RULES: list[tuple[int, list[str]]] = [
    (0, ["寻访", "中坚", "招募", "甄选"]),
    (1, ["战斗", "SideStory", "#", "故事集", "资源收集", "集成"]),
    (2, ["签到", "赠送", "领取", "墙", "资深干员特别调用"]),
    (-1, ["家具", "新装", "时装", "主题", "上架", "风尚回顾"]),
    (99, ["剿灭", "保全"]),
]


def classify_activity(title: str) -> int:
    for type_id, keywords in ACTIVITY_RULES:
        if any(kw in title for kw in keywords):
            return type_id
    return -1


def transform_date(input_str: str):
    try:
        cleaned = input_str.replace("日", " ").replace("月", "-").replace("年", "-")
        return parse(cleaned)
    except Exception:
        return None


def json_to_csv(json_data: list[dict], output_file: str) -> None:
    output_path = Path(output_file)
    try:
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["名称", "开始时间", "结束时间", "类型"])

            for item in json_data:
                if not item.get("subsections"):
                    st = transform_date(item.get("start_time", "")) if item.get("start_time") else ""
                    et = transform_date(item.get("end_time", "")) if item.get("end_time") else ""
                    at = classify_activity(item.get("title", ""))
                    writer.writerow([item.get("title", ""), st, et, at])

                for subsection in item.get("subsections", []):
                    st = transform_date(subsection.get("start_time", "")) if subsection.get("start_time") else ""
                    et = transform_date(subsection.get("end_time", "")) if subsection.get("end_time") else ""
                    at = classify_activity(subsection.get("subtitle", ""))
                    writer.writerow([subsection.get("subtitle", ""), st, et, at])

        logger.info("JSON 转 CSV 完成: %s", output_file)
    except Exception:
        logger.exception("JSON 转 CSV 失败: %s", output_file)


if __name__ == "__main__":
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    json_path = Path("anniversary_activity_extracted.json")
    if not json_path.exists():
        logger.error("JSON 文件不存在: %s", json_path)
        sys.exit(1)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.exception("读取 JSON 文件失败: %s", json_path)
        sys.exit(1)

    json_to_csv(data, "output.csv")
    logger.info("处理完成，请手动运行 main.py 以生成图表")
