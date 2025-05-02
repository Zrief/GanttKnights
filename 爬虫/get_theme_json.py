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

def get_target_url_from_page(url, xpath_selector):
    """获取最新的YJ活动预告新闻

    Args:
        url (str): 特定的网页
        xpath_selector (str): 用于定位目标元素的XPath选择器

    Returns:
        str: 解析后的网页链接
    """
    edge_options = configure_edge_options()
    service = Service(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=edge_options)
    try:
        driver.set_page_load_timeout(15)
        print("正在快速加载页面...")
        driver.get(url)

        # 使用传入的XPath选择器定位元素
        element = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable(
                (By.XPATH, xpath_selector)
            )
        )

        # 获取目标链接直接访问（避免点击不稳定）
        target_url = element.get_attribute("href")
        print("解析到目标地址:", target_url)
        return target_url

    except Exception as e:
        print(f"加载异常: {str(e)}")
        return None
    finally:
        driver.quit()
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
        "profile.managed_default_content_settings.popups": 2,  # 禁止弹窗
    }
    edge_options.add_experimental_option("prefs", prefs)
    # 反自动化检测配置
    edge_options.add_argument("--disable-blink-features=AutomationControlled")
    edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    # 网络协议优化
    edge_options.add_argument("--enable-tcp-fast-open --dns-prefetch-disable")
    edge_options.add_argument("--log-level=3")  # 设置日志级别为FATAL，消除不必要的警告
    return edge_options

def get_dynamic_content(url, core_container_selector, target_element_selector):
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
        core_container_selector (str): 核心容器的CSS选择器
        target_element_selector (str): 目标元素的CSS选择器

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
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        print(1)
        # 确保核心容器加载
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, core_container_selector)
            )
        )
        # 模拟滚动触发动态加载
        scroll_count = 8
        print("加载完毕，正在爬取")
        for _ in range(scroll_count):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            print(f"{_}/{scroll_count}")
            time.sleep(0.5)  # 减少滚动间隔时间
        # 确保目标元素渲染完成
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, target_element_selector))
        )
        return BeautifulSoup(driver.page_source, "html.parser")

    except Exception as e:
        print(f"加载异常: {str(e)}")
        return None
    finally:
        driver.quit()

def css_selector_version(html):
    soup = BeautifulSoup(html, 'html.parser')
    return soup.select('div[style*="overflow-y:scroll"][style*="margin-right:-16px"]')

if __name__ == "__main__":
# 读取鹰角官方，爬取活动卡池信息，活动信息
    # yj_url = "https://ak.hypergryph.com/news"
    # xpath_selector = '//a[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "活动预告")]'
    # news_url = get_target_url_from_page(yj_url, xpath_selector)# 活动详情网页
    # core_container_selector = '[style*="overflow-y: scroll; margin-right: -16px;"]'
    # target_element_selector = '[style*="overflow-y: scroll; margin-right: -16px;"]'
    # # yj_url = ""
    # yj_html = get_dynamic_content(news_url, core_container_selector, target_element_selector)
    with open("debug_page.html", "r", encoding="utf-8") as f:
        soup = f.read()
        theme_res = css_selector_version(soup)
        with open("theme.html","w",encoding="utf-8") as f:
            f.write(theme_res.prettify())
    

        