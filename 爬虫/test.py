import time
from turtle import st
from bs4 import BeautifulSoup
import json
import re

from sympy import N

def extract_structured_data(html_content,stopwords=None):
    soup = BeautifulSoup(html_content, 'html.parser')
    container = soup.find('div', class_='_0868052a')
    
    result = []
    current_section = None
    
    i=1
    for element in container.children:
        i+=1
        current_subsection = None
        if not element.name:
            continue
            
        if element.name == 'p':
            text = element.get_text(strip=True)
            # if not text:
            #     continue
            if i<30:print(text)

            if not stopwords:
                stopwords = ['条件', '说明','注意','组合包','礼包','家具','主要奖励','累计寻访' ]

            # 检查是否是主标题（一、二、三... 或 1. 2. 3.）
            title_match = re.match(r'^([一二三四五六七八九十]+、|\d+\.)\s*(.+)', text)
            if title_match:
                if current_section:
                    result.append(current_section)
                current_section = {
                    'title': title_match.group(2).strip(),
                    'subsections': [],
                    'start_time': None,
                    'end_time': None,
                }
                continue

            # 检查是否是子标题（◆<...> 或 【...】）
            subtitle_match = re.search(r'<(第.+)>|【(第.+)】', text)
            if subtitle_match:
                print(subtitle_match)
                if current_section:
                    # 提取子标题名称（使用第一个非空匹配组）
                    subtitle = subtitle_match.group(1) or subtitle_match.group(2)
                    current_subsection = {
                        'subtitle': subtitle.strip(),
                        'start_time': None,
                        'end_time': None,
                    }
                    current_section['subsections'].append(current_subsection)
                continue
                
            # 提取时间信息（格式如：04月21日 16:00 - 05月05日 03:59）
            date_pattern = r"(\d{1,2}月\d{1,2}日\s*\d{2}:\d{2})\s*[～~-]\s*(\d{1,2}月\d{1,2}日\s*\d{2}:\d{2})"
    
            time_match = re.search(date_pattern, text)
            if time_match:
                time_start = time_match.group(1)
                time_end = time_match.group(2)
                if current_subsection:
                    current_section['subsections']['start_time'] = time_start
                    current_section['subsections']['end_time'] = time_end
                elif current_section:
                    current_section['start_time'] = time_start
                    current_section['end_time'] = time_end
                continue
                
            # # 添加到当前内容
            # if current_section:
            #     if current_section['subsections']:
            #         current_section['subsections'][-1]['content'].append(text)
            #     else:
            #         current_section['content'].append(text)
    
    # 添加最后一个section
    if current_section:
        result.append(current_section)
    
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
# process_html_file('babel_activity.html')       # 第二个页面