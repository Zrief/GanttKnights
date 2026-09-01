import time
from turtle import st
from bs4 import BeautifulSoup
import json
import re


def extract_structured_data(html_content, stopwords=None):
    soup = BeautifulSoup(html_content, 'html.parser')
    container = soup.find('div', class_='_0868052a')
    if not container:
        print("未找到指定的HTML容器")
        return []

    result = []
    current_section = None
    current_subsection = None

    for element in container.children:

        if not element.name:
            continue
        # 处理非段落元素时重置 current_subsection
        if element.name != 'p':
            current_subsection = None  # 关键修复点：遇到图片等非段落元素时结束当前子标题
            continue

        text = element.get_text(strip=True)
        if not text:
            continue

        # 检查是否是主标题（一、二、三... 或 1. 2. 3.）
        title_match = re.match(r'^([一二三四五六七八九十]+、|\d+\.)\s*(.+)', text)
        if title_match:
            the_titile = title_match.group(2).strip()
            the_titile = the_titile.partition('，')[0] if not the_titile.partition('，')[2] else the_titile.partition('，')[2]  # 去掉逗号前面的内容
            current_section = {
                'title': the_titile,
                'subsections': [],
                'start_time': None,
                'end_time': None,
            }
            current_subsection = None
            result.append(current_section)
            continue

        # 检查是否是子标题（◆<...> 或 【...】）
        # subtitle_match = re.search(r'<(第.+)>|【(第.+)】', text)
        subtitle_match = re.search(r'(?:◆|<|【)(第.+?)(?:>|】|$)', text)
        if subtitle_match and current_section:
            current_subsection = {
                'subtitle': subtitle_match.group(1).strip(),
                'start_time': None,
                'end_time': None,
            }
            result[-1]['subsections'].append(current_subsection)
            continue

        # 提取时间信息（格式如：04月21日 16:00 - 05月05日 03:59）
        date_pattern = r"(\d{1,2}月\d{1,2}日\s*\d{2}:\d{2})\s*[～~-]\s*(\d{1,2}月\d{1,2}日\s*\d{2}:\d{2})"

        time_match = re.search(date_pattern, text)
        if time_match:
            time_start = time_match.group(1)
            time_end = time_match.group(2)
            if current_subsection:
                current_subsection['start_time'] = time_start
                current_subsection['end_time'] = time_end
            elif current_section:
                current_section['start_time'] = time_start
                current_section['end_time'] = time_end
            continue

        # 处理开放关卡信息
        if '开放关卡：' in text and current_subsection:
            stage_match = re.search(r'开放关卡：\s*(\S+)', text)
            if stage_match:
                stage_name = stage_match.group(1).strip()
                current_subsection['subtitle'] += f" - {stage_name}"

    result = [item for item in result if not (len(item['subsections']) == 0 and item['start_time'] is None and item['end_time'] is None)]

    return result


# 示例使用
def process_html_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    structured_data = extract_structured_data(html_content)

    output_file = file_path.replace('.html', '_extracted.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(structured_data, f, ensure_ascii=False, indent=2)

    print(f"处理完成，结果已保存到 {output_file}")


# 处理HTML文件
process_html_file('anniversary_activity.html')  # 第一个页面
process_html_file('babel_activity.html')  # 第二个页面
