"""卡池解析 — 从 PRTS 限时寻访页提取卡池数据"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PRTS_URL = "https://prts.wiki/w/卡池一览/限时寻访"
总览_URL = "https://prts.wiki/w/卡池一览"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# 匹配 "2026-05-01 07:00~2026-05-15 03:59"
时间_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*[~\u301c\uff5e\u2010-\u2015]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})"
)

# 提取核心卡池名（去掉前缀，去掉"寻访"等后缀）
卡池名_RE = re.compile(r"[【「](.+?)[】」]")

# 提取六星干员名（在【】内，且不含"加入""仅限""从未""寻访"等关键词）
六星干员_RE = re.compile(r"[【「]([^】」]+)[】」]")


def 提取六星(文本: str) -> str:
    """从六星列文本中提取干员名，多个用/分隔"""
    跳过 = {"寻访", "加入", "标准寻访", "中坚寻访", "限定寻访",
            "春节", "庆典", "夏季", "精英", "特殊", "战术",
            "仅限", "从未", "以下", "期间", "获取", "新春"}
    names = []
    for m in 六星干员_RE.finditer(文本):
        name = m.group(1).strip()
        if name and not any(kw in name for kw in 跳过):
            # 去掉后缀如" [限定]"
            name = name.replace(" [限定]", "").split("[")[0].strip()
            if name and name not in names:
                names.append(name)
    return " / ".join(names) if names else ""


def 截短卡池名(原标题: str) -> str:
    """把长标题截短为简洁名"""
    # 取【】中的核心名
    for m in 卡池名_RE.finditer(原标题):
        short = m.group(1)
        if short not in ("限定寻访·庆典", "限定寻访·春节", "限定寻访·夏季", "跨年欢庆寻访"):
            return short
    # 直接取原标题去掉前导描述
    return 原标题.strip()


def 抓取限时寻访() -> list[dict]:
    """解析 PRTS 限时寻访一览表，返回卡池列表"""
    try:
        r = httpx.get(PRTS_URL, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
    except Exception:
        logger.exception("获取限时寻访页面失败")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    parser = soup.find("div", class_="mw-parser-output")
    if not parser:
        return []

    tables = parser.find_all("table")
    if not tables:
        return []

    # 主表格是第一个大表格
    main = tables[0]
    rows = main.find_all("tr")

    结果 = []
    for ri, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        if ri == 0 or len(cells) < 4:
            continue

        # 第一列：卡池名（可能有链接）
        name_cell = cells[0]
        link = name_cell.find("a")
        卡池名 = name_cell.get_text(strip=True).replace("\u200b", "")

        # 第二列：时间
        时间文本 = cells[1].get_text(strip=True).replace("\u200b", "")
        tm = 时间_RE.search(时间文本)
        if not tm:
            continue

        # 第三列：六星干员
        六星文本 = cells[2].get_text(strip=True).replace("\u200b", "").replace("限兑兑", "")
        six = 提取六星(六星文本)

        短名 = 截短卡池名(卡池名)
        名称 = f"【寻访】{短名}" + (f" · {six}" if six else "")

        结果.append({
            "名称": 名称,
            "开始时间": tm.group(1) + ":00",
            "结束时间": tm.group(2) + ":00",
            "类型": 0,
        })

    logger.info("解析限时寻访: %d 条", len(结果))
    return 结果


def 抓取常驻寻访() -> list[dict]:
    """从卡池总览页解析常驻标准寻访和常驻中坚寻访"""
    try:
        r = httpx.get(总览_URL, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
    except Exception:
        logger.exception("获取卡池总览页面失败")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    parser = soup.find("div", class_="mw-parser-output")
    if not parser:
        return []

    结果 = []
    目标标题 = {
        "常驻标准寻访": "【标准池】",
        "常驻中坚寻访": "【中坚池】",
    }

    for h in parser.find_all("h2"):
        标题文本 = h.get_text(strip=True)
        prefix = None
        for kw, pre in 目标标题.items():
            if kw in 标题文本:
                prefix = pre
                break
        if not prefix:
            continue

        table = h.find_next_sibling("table")
        if not table:
            continue

        rows = table.find_all("tr")
        for ri, row in enumerate(rows):
            cells = row.find_all(["th", "td"])
            if ri == 0 or len(cells) < 5:
                continue

            序号 = cells[0].get_text(strip=True)
            时间文本 = cells[2].get_text(strip=True).replace("\u200b", "")
            tm = 时间_RE.search(时间文本)
            if not tm or not 序号:
                continue

            # 从链接中提取六星干员名（第4列，索引3）
            from urllib.parse import unquote
            operators = []
            for a in (cells[3].find_all("a") if len(cells) > 3 else []):
                href = a.get("href", "")
                if href.startswith("/w/"):
                    name = unquote(href[3:])
                    if name and name not in operators:
                        operators.append(name)

            op_str = " / ".join(operators)
            名称 = f"{prefix}#{序号}" + (f" · {op_str}" if op_str else "")

            结果.append({
                "名称": 名称,
                "开始时间": tm.group(1) + ":00",
                "结束时间": tm.group(2) + ":00",
                "类型": 0,
            })

    logger.info("解析常驻寻访: %d 条", len(结果))
    return 结果


def 合并卡池CSV(卡池列表: list[dict], 文件路径: str | Path, 现在时间: str) -> list[dict]:
    """从 卡池.csv 合并未结束的标准/中坚寻访"""
    路径 = Path(文件路径)
    if not 路径.exists():
        return 卡池列表

    try:
        import csv
        with open(路径, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            已有名称 = {a["名称"] for a in 卡池列表}
            for row in reader:
                名称 = row.get("名称", "").strip()
                if not 名称 or 名称 in 已有名称:
                    continue
                if row.get("结束时间", "") >= 现在时间:
                    卡池列表.append({
                        "名称": 名称,
                        "开始时间": row["开始时间"],
                        "结束时间": row["结束时间"],
                        "类型": 0,
                        "_parent": "",
                    })
                    已有名称.add(名称)
            logger.info("  合并卡池CSV: %s", 路径.name)
    except Exception:
        logger.exception("读取卡池文件失败: %s", 路径)
    return 卡池列表
