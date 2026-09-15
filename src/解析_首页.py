"""解析层 — PRTS 首页"新增时装/新增模组"板块

亮点干员板块由 wiki 动态生成（首页 wikitext 源码里没有），只能解析渲染
HTML。以板块标题文本为主锚点、mp-operators-title 类名做板块边界；
href/title/图标 src 逐属性独立提取，不依赖标签内属性顺序。
板块本身没有时间信息，展示时挂到当前活动/版本窗口。
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

logger = logging.getLogger("src.解析")

PRTS_BASE = "https://prts.wiki"

目标板块 = {"新增时装": "时装", "新增模组": "模组", "凭证兑换": "凭证"}
预告键 = tuple(目标板块.values())   # 预告 JSON 的板块键，缺板块时也要留空键

条目正则 = re.compile(r'<a\s([^>]*?)>((?:(?!</a>).)*)</a>', re.S)
属性href正则 = re.compile(r'href="([^"]+)"')
属性title正则 = re.compile(r'title="([^"]+)"')
图标标签正则 = re.compile(r'<img[^>]*\bid="charicon"[^>]*>')
图标src正则 = re.compile(r'src="([^"]+)"')
板块边界正则 = re.compile(r'mp-operators-title"')
非法文件字符 = re.compile(r'[\\/:*?"<>|#\s]')


def 解析新增内容(首页html: str) -> dict[str, list[dict]]:
    """提取首页新增时装/模组/凭证条目，返回 {"时装": [...], "模组": [...], "凭证": [...]}

    三个板块都先建空列表：板块没解析到（页面改版、临时缺区块）时键仍在，
    下游（底栏分区）见到的是"这块为空"，而不是整个板块凭空消失。
    时装条目的 名称 为空串；模组条目标题形如"干员#模组名"，拆成
    干员 + 名称 两个字段。
    """
    边界们 = [m.start() for m in 板块边界正则.finditer(首页html)]
    结果: dict[str, list[dict]] = {键: [] for 键 in 预告键}

    for 板块标题, 类型 in 目标板块.items():
        锚点 = 首页html.find(板块标题 + "</div>")
        if 锚点 < 0:
            logger.warning("首页未找到板块: %s", 板块标题)
            continue
        区域起点 = 锚点 + len(板块标题) + len("</div>")
        区域终点 = next((b for b in 边界们 if b > 锚点), len(首页html))

        条目们: list[dict] = []
        seen: set[str] = set()
        for a in 条目正则.finditer(首页html[区域起点:区域终点]):
            href = 属性href正则.search(a.group(1))
            标题属性 = 属性title正则.search(a.group(1))
            if not href or not 标题属性:
                continue
            标题文本 = 标题属性.group(1).strip()
            if not 标题文本 or 标题文本 in seen:
                continue
            图标标签 = 图标标签正则.search(a.group(2))
            if not 图标标签:
                continue
            图标 = 图标src正则.search(图标标签.group(0))
            if not 图标:
                continue
            seen.add(标题文本)
            干员, _, 模组名 = 标题文本.partition("#")
            干员 = 干员.strip()
            模组名 = 模组名.strip()
            条目们.append({
                "干员": 干员,
                "名称": 模组名,
                "页面": urljoin(PRTS_BASE + "/", href.group(1)),
                "图标": 图标.group(1),
                "图标文件名": _缓存文件名(类型, 干员, 模组名),
            })

        结果[类型] = 条目们
        logger.info("  首页新增%s: %d 条", 类型, len(条目们))
    return 结果


def _缓存文件名(类型: str, 干员: str, 名称: str) -> str:
    名 = f"{类型}_{干员}" + (f"_{名称}" if 名称 else "")
    return 非法文件字符.sub("_", 名) + ".png"
