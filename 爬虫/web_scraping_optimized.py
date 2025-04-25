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


def configure_edge_options():
    """
    配置Edge浏览器选项，包含无头模式、性能优化、反检测等设置
    """
    edge_options = Options()
    # 核心运行模式配置
    edge_options.add_argument("--headless=new")
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--no-sandbox")
    # 页面加载优化配置
    edge_options.page_load_strategy = "eager"
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "permissions.default.stylesheet": 2,
        "profile.default_content_setting_values.javascript": 1,        
        "profile.managed_default_content_settings.media_stream": 2,  # 禁止媒体流
        "profile.managed_default_content_settings.popups": 2  # 禁止弹窗
    }
    edge_options.add_experimental_option("prefs", prefs)
    # 反自动化检测配置
    edge_options.add_argument("--disable-blink-features=AutomationControlled")
    edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    # 网络协议优化
    edge_options.add_argument("--enable-tcp-fast-open --dns-prefetch-disable")
    edge_options.add_argument("--log-level=3")# 设置日志级别为FATAL，消除不必要的警告
    # edge_options.add_argument('--ignore-certificate-errors')# 忽略SSL证书验证（可选，有安全风险）
    return edge_options


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
        - 执行效率：平均加载时间2 - 4秒（取决于网络状况）
        - 内存消耗：约300MB
        - 支持页面类型：SPA（单页应用）、CSR（客户端渲染）网页
        - 网络要求：需要允许WebSocket协议
    """
    edge_options = configure_edge_options()
    service = Service(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=edge_options)
    try:
        driver.set_page_load_timeout(15)
        print("正在快速加载页面...")
        driver.get(url)
        # 等待页面完全加载
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        # 确保核心容器加载
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[class*="ProfilePostList__Wrapper"]')
            )
        )
        # 模拟滚动触发动态加载
        scroll_count = 2
        for _ in range(scroll_count):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.3)  # 减少滚动间隔时间
        # 确保目标元素渲染完成
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="PostItem__"]'))
        )
        return BeautifulSoup(driver.page_source, "html.parser")
    except Exception as e:
        print(f"加载异常: {str(e)}")
        return None
    finally:
        driver.quit()


def parse_event(event_container, selectors):
    """
    解析单个事件的数据
    """
    try:
        title_block = event_container.select_one(selectors['title'])
        if not title_block:
            print("警告：标题容器结构异常")
            return None
        title_text = title_block.get_text(strip=True)
        content_block = event_container.select_one(selectors['content_container'])
        if not content_block:
            print(f"警告：未找到关联内容区块->标题 {title_text}")
            return None
        time_data = content_block.select_one(selectors['time_span'])
        if time_data:
            time_match = re.search(
                r'(\d{1,2}月\d{1,2}日\d{2}:\d{2})\s*[～~]\s*(\d{1,2}月\d{1,2}日\d{2}:\d{2})',
                time_data.text
            )
            start, end = time_match.groups() if time_match else ("N/A", "N/A")
        else:
            start = end = "N/A"
        six_star_data = content_block.select_one(selectors['six_star_span'])
        if six_star_data:
            _, _, temp = six_star_data.text.partition('：')
            six_star = temp.split('（')[0].strip() if temp else "N/A"
        else:
            six_star = "N/A"
            return
        return {
            'event_type': title_text,
            'start_time': start,
            'end_time': end,
            'six_star': six_star.replace(" ", "")
        }
    except Exception as e:
        print(f"解析异常：{str(e)}")
        return None


def parse_content(soup):
    """
    解析网页内容，提取事件信息并保存到CSV文件
    """
    selectors = {
        'post_container': 'div[class^="PostItem__Body"]',
        'title': 'div.title-name',
        'content_container': 'div[class^="PostItem__Brief-"]',
        'time_span': 'span:-soup-contains("起止时间")',
        'six_star_span': 'span:-soup-contains("★★★★★★")'
    }
    events = [event for event_container in soup.select(selectors['post_container'])
            if (event := parse_event(event_container, selectors))]

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


if __name__ == "__main__":
    target_url = "https://www.skland.com/profile?id=7779816949641"
    soup = get_dynamic_content(target_url)
    if soup:
        # 保存完整页面供分析
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(soup.prettify())
        data = parse_content(soup)
        with open("res.dat", "w", encoding="utf-8") as f:
            f.write(str(data))
        print(f"获取到 {len(data)} 条内容")
    else:
        print("未获取到网页内容，无法进行解析。")
    