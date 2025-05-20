import json
import csv
from datetime import datetime
from dateutil.parser import parse
from dataclasses import dataclass
from typing import List, Dict


@dataclass
class ActivityTypeRule:
    id: int
    name: str
    keywords: List[str]


ACTIVITY_RULES = [
    ActivityTypeRule(0, "卡池", ["寻访", "中坚", "招募"]),
    ActivityTypeRule(1, "活动", ["-", "SideStory", "#", "故事集", "资源收集", "集成"]),
    ActivityTypeRule(2, "福利", ["签到", "赠送", "领取", "墙", "资深干员特别调用"]),
    ActivityTypeRule(-1, "商店", ["家具", "新装", "时装", "主题", "上架", "风尚回顾"]),
    ActivityTypeRule(99, "长期", ["剿灭", "保全"]),
]


def determine_activity_type(title: str) -> int:
    """
    根据标题判断活动类型
    :param title: 活动标题
    :return: 类型ID (未匹配时返回-1)
    """
    for rule in ACTIVITY_RULES:
        if any(keyword in title for keyword in rule.keywords):
            return rule.id
    return -1


def transform_data(input_str: str):
    """
    将日期字符串转换为标准日期格式
    """
    try:
        input_str = input_str.replace("日", " ").replace("月", "-")
        input_str = input_str.replace("年", "-")
        return parse(input_str)
    except ValueError:
        return None


def json_to_csv(json_data, output_file):
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['名称', '开始时间', '结束时间', '类型'])

        for item in json_data:
            # 处理主条目（如果没有subsections）
            if not item['subsections']:
                start_time = transform_data(item['start_time']) if item['start_time'] else ""
                end_time = transform_data(item['end_time']) if item['end_time'] else ""
                activity_type = determine_activity_type(item['title'])
                writer.writerow([item['title'], start_time, end_time, activity_type])

            # 处理subsections
            for subsection in item['subsections']:
                start_time = transform_data(subsection['start_time']) if subsection['start_time'] else ""
                end_time = transform_data(subsection['end_time']) if subsection['end_time'] else ""
                activity_type = determine_activity_type(subsection['subtitle'])

                writer.writerow([subsection['subtitle'], start_time, end_time, activity_type])


# 读取JSON数据
with open('anniversary_activity_extracted.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 转换为CSV
json_to_csv(data, 'output.csv')
import os

os.system('python ./main.py')
