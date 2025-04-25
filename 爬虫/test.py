import time
import re
import csv
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.microsoft import EdgeChromiumDriverManager


def get_dynamic_content(url):
    """
    使用无头模式Edge浏览器获取动态渲染的网页内容，并进行性能优化和反检测处理

    本函数实现以下核心功能：
    1. 配置高性能无界面浏览器环境
    2. 自动管理Edge驱动版本
    3. 网页资源加载优化
    4. 自动化特征隐藏
    5. 智能等待与动态内容加载
    6. 异常处理和资源回收

    Args:
        url (str): 需要抓取的目标网页URL，必须包含协议头（http/https）

    Returns:
        BeautifulSoup: 解析后的HTML文档对象，可直接用于数据提取
        None: 当页面加载失败时返回

    Raises:
        WebDriverException: 当浏览器驱动初始化失败时抛出
        TimeoutException: 当核心元素加载超时抛出（被内部捕获）

    Notes:
        - 执行效率：平均加载时间2-4秒（取决于网络状况）
        - 内存消耗：约300MB
        - 支持页面类型：SPA（单页应用）、CSR（客户端渲染）网页
        - 网络要求：需要允许WebSocket协议
    """
    # 配置无界面浏览器
    edge_options = Options()

    # 核心运行模式配置
    edge_options.add_argument("--headless=new")  # 无头模式
    edge_options.add_argument("--disable-gpu")  # GPU加速
    edge_options.add_argument("--no-sandbox")   # 沙盒策略

    # 页面加载优化配置
    edge_options.page_load_strategy = "eager"  # 加载策略
    prefs = {
        "profile.managed_default_content_settings.images": 2,    # 图片
        "permissions.default.stylesheet": 2,                     # CSS
        "profile.default_content_setting_values.javascript": 1    # JS
    }
    edge_options.add_experimental_option("prefs", prefs)

    # 反自动化检测配置
    edge_options.add_argument("--disable-blink-features=AutomationControlled")
    edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    # 网络协议优化
    edge_options.add_argument("--disable-quic --enable-tcp-fast-open --dns-prefetch-disable")  # 合并参数

    # 自动管理浏览器驱动（版本兼容处理）
    service = Service(EdgeChromiumDriverManager().install())

    # 初始化浏览器实例
    driver = webdriver.Edge(service=service, options=edge_options)
    # 增加JavaScript执行等待
    WebDriverWait(driver, 15).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )
    try:
        # 设置全局超时（页面加载/元素查找）
        driver.set_page_load_timeout(20)  # 超过20秒触发TimeoutException

        # 访问目标页面（显示加载进度）
        print("正在快速加载页面...")
        driver.get(url)

        # 第一阶段等待：确保核心容器加载
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[class*="ProfilePostList__Wrapper"]')
            )
        )

        # 模拟滚动触发动态加载（适用于无限滚动页面）
        for _ in range(2):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight*0.8);")
            time.sleep(0.5)  # 滚动间隔需匹配AJAX响应时间

        # 最终等待：确保目标元素渲染完成
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="PostItem__"]'))
        )

        # 返回标准化解析器对象
        return BeautifulSoup(driver.page_source, "html.parser")
    except Exception as e:
        print(f"加载异常: {str(e)}")
        return None
    finally:
        # 确保浏览器实例回收（避免内存泄漏）
        driver.quit()

def parse_content(soup):
    SELECTORS = {
        'post_container': 'div[class^="PostItem__Body"]',  # 帖子容器
        'title': 'div.title-name',  # 标题
        'content_container': 'div[class^="PostItem__Brief-"]', # 简要内容
        'time_span': 'span:contains("起止时间")', # 卡池的起止时间
        'six_star_span': 'span:contains("★★★★★★")', # 六星
    }

    events = []
    # 遍历所有包含标题的容器
    for title_container in soup.select(SELECTORS['post_container']):
        try:
            # 标题提取
            title_block = title_container.select_one(SELECTORS['title'])
            if not title_block:
                print("警告：标题容器结构异常")
                continue
            title_text = title_block.get_text(strip=True)
            
            # 查找内容容器
            content_block = title_container.select_one(SELECTORS['content_container'])

            if not content_block:
                print(f"警告：未找到关联内容区块->标题 {title_text}")
                continue

            # 时间提取（带防御性查找）
            time_data = content_block.select_one(SELECTORS['time_span'])
            if time_data:
                time_match = re.search(
                    r'(\d{1,2}月\d{1,2}日\d{2}:\d{2})\s*[～~]\s*(\d{1,2}月\d{1,2}日\d{2}:\d{2})', 
                    time_data.text
                )
                start, end = time_match.groups() if time_match else ("N/A", "N/A")
            else:
                start = end = "N/A"

            # 干员提取（改进分割逻辑）
            six_star_data = content_block.select_one(SELECTORS['six_star_span'])
            if six_star_data:
                # 使用partition方法替代正则分割
                _, _, temp = six_star_data.text.partition('：')
                six_star = temp.split('（')[0].strip() if temp else "N/A"
            else:
                six_star = "N/A"

            events.append({
                'event_type': title_text,
                'start_time': start,
                'end_time': end,
                'six_star': six_star.replace(" ","")
            })

        except Exception as e:
            print(f"解析异常：{str(e)}")
            continue


    # 写入CSV（空数据保护）
    if events:
        with open('arknights_events.csv', 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=['活动类型', '开始时间', '结束时间', '六星干员'])
            writer.writeheader()
            writer.writerows([
                {
                    '活动类型': e['event_type'],
                    '开始时间': e['start_time'],
                    '结束时间': e['end_time'],
                    '六星干员': e['six_star']
                } for e in events
            ])
        print(f"成功写入 {len(events)} 条活动记录")
    else:
        print("警告：未提取到任何有效数据")
    
    return events

# 执行示例
if __name__ == "__main__":
    target_url = "https://www.skland.com/profile?id=7779816949641"
    soup = get_dynamic_content(target_url)
    
    # 保存完整页面供分析
    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(soup.prettify())
    data = parse_content(soup)
    with open("res.dat", "w", encoding="utf-8") as f:
        f.write(str(data))
    print(f"获取到 {len(data)} 条内容")
