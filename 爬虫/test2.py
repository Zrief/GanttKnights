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


class BrowserManager:
    """浏览器操作管理类，负责浏览器实例的创建、操作和关闭"""

    def __init__(self, headless: bool = True, page_load_timeout: int = 15):
        """
        初始化浏览器管理器
        
        Args:
            headless: 是否无头模式
            page_load_timeout: 页面加载超时时间（秒）
        """
        self.headless = headless
        self.page_load_timeout = page_load_timeout
        self.driver = None  # 浏览器驱动实例
        self.is_running = False  # 浏览器运行状态

    def start_browser(self) -> None:
        """启动浏览器实例"""
        if self.is_running:
            print("浏览器已在运行中")
            return

        edge_options = self._configure_edge_options()
        service = Service(EdgeChromiumDriverManager().install())
        self.driver = webdriver.Edge(service=service, options=edge_options)
        self.driver.set_page_load_timeout(self.page_load_timeout)
        self.is_running = True
        print("浏览器已启动")

    def _configure_edge_options(self) -> Options:
        """
        配置Edge浏览器选项，包含无头模式、性能优化、反检测等设置
        """
        edge_options = Options()
        # 核心运行模式配置
        edge_options.add_argument("--headless=new" if self.headless else "")
        edge_options.add_argument("--disable-gpu")
        edge_options.add_argument("--no-sandbox")
        # 页面加载优化配置
        edge_options.page_load_strategy = "eager"
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "permissions.default.stylesheet": 2,
            "profile.default_content_setting_values.javascript": 1,
            "profile.managed_default_content_settings.media_stream":
            2,  # 禁止媒体流
            "profile.managed_default_content_settings.popups": 2,  # 禁止弹窗
        }
        edge_options.add_experimental_option("prefs", prefs)
        # 反自动化检测配置
        edge_options.add_argument(
            "--disable-blink-features=AutomationControlled")
        edge_options.add_experimental_option("excludeSwitches",
                                             ["enable-automation"])
        # 网络协议优化
        edge_options.add_argument(
            "--enable-tcp-fast-open --dns-prefetch-disable")
        edge_options.add_argument("--log-level=3")  # 设置日志级别为FATAL，消除不必要的警告
        return edge_options

    def fetch_dynamic_page_content(self,
                                   url: str,
                                   core_container_selector: str,
                                   target_element_selector: str,
                                   scroll_count=4) -> BeautifulSoup | None:
        """
        获取动态渲染的网页内容
        
        Args:
            url: 目标URL
            core_container_selector: 核心容器的CSS选择器
            target_element_selector: 目标元素的CSS选择器
            
        Returns:
            BeautifulSoup对象或None
        """
        if not self.is_running:
            self.start_browser()

        try:
            print(f"正在加载页面: {url}")
            self.driver.get(url)

            # 等待页面完全加载
            WebDriverWait(self.driver, 10).until(lambda d: d.execute_script(
                "return document.readyState") == "complete")

            # 确保核心容器加载
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, core_container_selector)))

            # 模拟滚动触发动态加载
            print("加载完毕，正在爬取")
            for i in range(scroll_count):
                self.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);")
                print(f"{i+1}/{scroll_count}")
                time.sleep(0.5)  # 减少滚动间隔时间

            # 确保目标元素渲染完成
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, target_element_selector)))

            return BeautifulSoup(self.driver.page_source, "html.parser")

        except Exception as e:
            print(f"加载异常: {str(e)}")
            return None

    def extract_target_url_from_page(self, url: str,
                                     xpath_selector: str) -> str | None:
        """
        从页面中提取目标URL
        
        Args:
            url: 目标URL
            xpath_selector: 目标元素的XPath选择器
            
        Returns:
            目标URL或None
        """
        if not self.is_running:
            self.start_browser()

        try:
            print(f"正在加载页面: {url}")
            self.driver.get(url)

            # 使用传入的XPath选择器定位元素
            element = WebDriverWait(self.driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, xpath_selector)))

            # 获取目标链接直接访问（避免点击不稳定）
            target_url = element.get_attribute("href")
            print("解析到目标地址:", target_url)
            return target_url

        except Exception as e:
            print(f"加载异常: {str(e)}")
            return None

    def close_browser(self) -> None:
        """关闭浏览器实例"""
        if self.is_running and self.driver:
            self.driver.quit()
            self.is_running = False
            print("浏览器已关闭")


def parse_event_container(title_text, content_text):
    """
    解析单条活动的数据
    """
    date_pattern = r"(\d{1,2}月\d{1,2}日\s*\d{2}:\d{2})\s*[～~-]\s*(\d{1,2}月\d{1,2}日\s*\d{2}:\d{2})"
    six_star_pattern = r"★★★★★★[:：]?(.+?)[\(（]"
    try:

        time_match = re.search(date_pattern, content_text)
        if time_match:
            start, end = time_match.groups()
        else:
            return

        six_star_data = re.search(six_star_pattern, content_text)
        if six_star_data:
            six_star = six_star_data.group(1)
        else:
            six_star = "N/A"

        return {
            "event_type": title_text,
            "start_time": start,
            "end_time": end,
            "six_star": six_star.replace(" ", ""),
        }
    except Exception as e:
        print(f"解析异常：{str(e)}")
        return None


def parse_six_star_events(soup):
    """
    解析网页内容，提取六星活动信息并保存到CSV文件
    """
    selectors = {
        "title": "div.title-name",
        "content_container": 'div[class^="PostItem__Brief-"]',
    }

    # 匹配森空岛帖子简要
    content_containers = soup.select(selectors["content_container"])
    events = []

    for content_container in content_containers:
        # 尝试在内容容器的上级或同级中找到标题
        title_block = content_container.find_previous(
            'div', class_=lambda x: x and x.startswith('title-name'))

        if not title_block:
            title_block = content_container.find_parent().find(
                'div', class_=lambda x: x and x.startswith('title-name'))

        if not title_block:
            print(
                f"警告：未找到关联标题->内容 {content_container.get_text(strip=True)[:20]}..."
            )
            continue

        title_text = title_block.get_text(strip=True)
        content_text = content_container.get_text(strip=True)

        event = parse_event_container(title_text, content_text)
        if event:
            events.append(event)

    if events:
        with open("arknights_events.csv",
                  "w",
                  newline="",
                  encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=["活动类型", "开始时间", "结束时间", "六星干员"])
            writer.writeheader()
            writer.writerows([{
                "活动类型": e["event_type"],
                "开始时间": e["start_time"],
                "结束时间": e["end_time"],
                "六星干员": e["six_star"],
            } for e in events])
        print(f"成功写入 {len(events)} 条活动记录")
    else:
        print("警告：未提取到任何有效数据")
    return events


def extract_event_details(html_content):
    """
    从HTML内容中提取活动详情信息
    返回结构：[{活动名称, 开始时间, 结束时间}]
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    events = []

    # 遍历所有段落标签
    for p in soup.find_all('p'):
        text = p.get_text(strip=True)

        # 匹配活动名称模式：<strong>活动名称</strong>
        if strong_tag := p.find('strong'):
            event_name = strong_tag.get_text(strip=True)

            # 寻找时间信息（可能在当前段落或后续段落）
            time_match = re.search(
                r'(开放时间|活动时间)[：:]?\s*(\d{1,2}月\d{1,2}日 \d{2}:\d{2})\s*[～~至-]\s*(\d{1,2}月\d{1,2}日 \d{2}:\d{2})',
                text)

            # 如果当前段落没有时间信息，检查后续兄弟节点
            if not time_match:
                next_sib = p.find_next_sibling()
                if next_sib and next_sib.name == 'p':
                    time_match = re.search(
                        r'(\d{1,2}月\d{1,2}日 \d{2}:\d{2})\s*[～~至-]\s*(\d{1,2}月\d{1,2}日 \d{2}:\d{2})',
                        next_sib.get_text(strip=True))

            # 提取时间信息
            if time_match:
                start_time = time_match.group(2) if time_match.group(
                    2) else time_match.group(1)
                end_time = time_match.group(3) if time_match.group(
                    3) else time_match.group(2)
                events.append({
                    '活动名称': event_name,
                    '开始时间': start_time,
                    '结束时间': end_time
                })

    return events


if __name__ == "__main__":
    # 使用浏览器管理器实例爬取数据
    browser = BrowserManager(headless=True)

    try:
        # 读取森空岛的官方，爬取近期轮换卡池信息
        skd_url = "https://www.skland.com/profile?id=7779816949641"
        core_container_selector = '[class*="ProfilePostList__Wrapper"]'
        target_element_selector = '[class*="PostItem__"]'
        soup = browser.fetch_dynamic_page_content(skd_url,
                                                  core_container_selector,
                                                  target_element_selector,
                                                  scroll_count=8)

        # 读取鹰角官方，爬取活动卡池信息，活动信息
        # yj_url = "https://ak.hypergryph.com/news"
        # xpath_selector = '//a[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "活动预告")]'
        # news_url = browser.extract_target_url_from_page(yj_url, xpath_selector)  # 活动详情网页
        # core_container_selector = '[style*="overflow-y: scroll; margin-right: -16px;"]'
        # target_element_selector = '[style*="overflow-y: scroll; margin-right: -16px;"]'
        # soup = browser.fetch_dynamic_page_content(news_url, core_container_selector, target_element_selector)

        if soup:
            # 保存完整页面供分析
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            data = parse_six_star_events(soup)
        else:
            print("未获取到网页内容，无法进行解析。")

    finally:
        # 确保浏览器被关闭
        browser.close_browser()
