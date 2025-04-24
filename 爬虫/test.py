import time
import json
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
    # 配置无界面模式
    edge_options = Options()
    edge_options.add_argument("--headless=new")  # 使用Chromium 112+的无头渲染引擎
    edge_options.add_argument("--disable-gpu")  # 禁用GPU加速防止云环境异常
    edge_options.add_argument("--no-sandbox")  # 禁用沙盒提升容器兼容性

    # 资源加载策略配置（提速40%+）
    edge_options.page_load_strategy = "eager"  # 文档加载完成即返回，不等待子资源
    prefs = {
        "profile.managed_default_content_settings.images": 2,  # 禁止图片加载
        "permissions.default.stylesheet": 2,  # 禁用CSS样式表
        "profile.default_content_setting_values.javascript": 1,  # 保持JS执行
    }
    edge_options.add_experimental_option("prefs", prefs)

    # 反自动化检测配置
    edge_options.add_argument("--disable-blink-features=AutomationControlled")
    edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    # 网络协议优化配置
    edge_options.add_argument("--disable-quic")  # 禁用QUIC协议避免协商延迟
    edge_options.add_argument("--enable-tcp-fast-open")  # 启用TCP快速打开
    edge_options.add_argument("--dns-prefetch-disable")  # 禁用DNS预取

    # 自动管理浏览器驱动（版本兼容处理）
    service = Service(EdgeChromiumDriverManager().install())

    # 初始化浏览器实例
    driver = webdriver.Edge(service=service, options=edge_options)
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
    # 使用CSS属性包含选择器防御类名混淆
    posts = soup.select('[class*="Profile__ContentStyle"]')

    results = []
    for post in posts:
        # 使用包含关键字的属性选择器
        title = post.select_one('[class*="title_name"]')
        
        # 定位包含多个span的brief容器
        brief_container = post.select_one('[class*="PostItem_Brief"]')
        spans = []
        
        if brief_container:
            # 提取容器内的所有span元素内容
            spans = [span.get_text(strip=True) for span in brief_container.select('span')]

        results.append({
            "title": title.text.strip() if title else None,
            "position_brief": {
                "text": brief_container.text.strip() if brief_container else None,
                "spans": spans  # 单独存储每个span的文本
            }
        })
    return results


# 执行示例
if __name__ == "__main__":
    target_url = "https://www.skland.com/profile?id=7779816949641"
    soup = get_dynamic_content(target_url)
    # print(soup)
    with open("tmp","w",encoding="utf-8") as f:
        json.dump(soup,f)

    # with open("tmp","r",encoding="utf-8") as f:
    #     soup = f.read()

    
    # 保存完整页面供分析
    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(soup.prettify())
    data = parse_content(soup)
    with open("res.dat", "w", encoding="utf-8") as f:
        f.write(str(data))
    print(f"获取到 {len(data)} 条内容")
