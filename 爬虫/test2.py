import re
from bs4 import BeautifulSoup

def classify_events(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    print(soup)
    container = soup.find('div', class_='_0868052a')
    
    results = {
        "sidestory": [],
        "卡池类": [],
        "其他活动": []
    }

    current_category = None
    current_event = {}
    
    for element in container.find_all(['p', 'img']):
        if element.name == 'img':
            # 图片作为新章节开始的标志
            current_event = {}
            current_category = None
            continue
            
        text = element.get_text(strip=True)
        strong = element.find('strong')
        
        # 类型判断逻辑
        if strong:
            title = strong.get_text(strip=True)
            current_event["活动名称"] = title
            
            # Sidestory 识别 (包含分阶段活动)
            if "SideStory" in title or "限时开启" in title:
                current_category = "sidestory"
                current_event["阶段"] = []
                
            # 卡池类识别
            elif any(kw in title for kw in ["寻访", "卡池", "甄选"]):
                current_category = "卡池类"
                
            else:
                current_category = "其他活动"

        # 时间提取强化逻辑
        time_match = re.search(
            r'(?:开放时间|活动时间|售卖时间)[：:]?\s*(\d{1,2}月\d{1,2}日[ \d:-]+\d{2}:\d{2})[ ～~至-]+(\d{1,2}月\d{1,2}日[ \d:-]+\d{2}:\d{2})', 
            text
        )
        
        if time_match and current_event:
            time_data = {
                "开始时间": time_match.group(1),
                "结束时间": time_match.group(2)
            }
            
            # Sidestory 阶段处理
            if current_category == "sidestory" and "◆" in text:
                stage_match = re.search(r'◆&lt;(.*?)&gt;', text)
                if stage_match:
                    current_event["阶段"].append({
                        "阶段名称": stage_match.group(1),
                        **time_data,
                        "开放关卡": re.search(r'【(.*?)】', text).group(1) if "开放关卡" in text else None
                    })
            else:
                current_event.update(time_data)
                
        # 卡池详细信息提取
        if current_category == "卡池类" and "出现率上升" in text:
            current_event["UP干员"] = {
                "六星": re.findall(r'★★★★★★：(.*?)(?=\s|$)', text),
                "五星": re.findall(r'★★★★★：(.*?)(?=\s|$)', text)
            }
            
        # 完成事件收集
        if element.name == 'p' and current_event.get("活动名称") and not element.find_next('strong'):
            if current_category == "sidestory" and "阶段" in current_event:
                results["sidestory"].append(current_event)
            elif current_category == "卡池类":
                results["卡池类"].append(current_event)
            else:
                results["其他活动"].append(current_event)
            current_event = {}

    return results

if __name__ == "__main__":

    with open("debug_page.html", "r", encoding="utf-8") as f:
        soup=f.read()
        
    res=classify_events(soup)
    print(res)