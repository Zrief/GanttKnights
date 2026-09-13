"""卡池解析 — 通过 MediaWiki API 取 卡池一览 的 wikitext 并解析

卡池一览页由 bot 维护（页面内含 Bot Edit Anchor 标记），wikitable 格式稳定：
时间列是带年份的 `YYYY-MM-DD HH:MM~<br/>YYYY-MM-DD HH:MM`，干员名在
{{干员头像|名字}} 模板里，因此直接按分区标题 + 表格结构解析 wikitext，
不依赖 HTML 渲染结果。页面仅记录本年度寻访，对按周绘图足够。
"""

from __future__ import annotations

import logging
import re

from .获取_prts import PRTS_API, 请求

logger = logging.getLogger(__name__)

# 分区标题关键词 → 名称前缀 → 是否带序号列
分区规则: list[tuple[str, str, bool]] = [
    ("限时寻访", "【寻访】", False),
    ("常驻标准寻访", "【标准池】", True),
    ("常驻中坚寻访", "【中坚池】", True),
]

时间_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})\s*~\s*(?:<br\s*/?>)?\s*(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})"
)
链接_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
干员_RE = re.compile(r"\{\{干员头像\|([^|}]+)")
标题_RE = re.compile(r"^==+(.+?)==+", re.M)
单元格属性_RE = re.compile(r'^\s*(?:style|class|colspan|rowspan)="[^"]*"\s*\|\s*')


def 抓取卡池一览() -> list[dict]:
    """请求 卡池一览 的 wikitext，解析全部限时/标准/中坚卡池"""
    resp = 请求(
        PRTS_API,
        params={"action": "parse", "page": "卡池一览", "prop": "wikitext", "format": "json"},
    )
    if resp is None:
        logger.warning("卡池一览请求失败")
        return []
    字段 = resp.json().get("parse", {}).get("wikitext", {})
    wikitext = 字段.get("*", "") if isinstance(字段, dict) else str(字段)
    if not wikitext:
        logger.warning("卡池一览 wikitext 为空")
        return []
    return 解析卡池wikitext(wikitext)


def 解析卡池wikitext(wikitext: str) -> list[dict]:
    """把 卡池一览 wikitext 解析为卡池条目（纯函数，便于离线测试）"""
    结果: list[dict] = []
    for 关键词, 前缀, 带序号 in 分区规则:
        区文本 = _提取分区(wikitext, 关键词)
        if not 区文本:
            logger.warning("卡池一览未找到分区: %s", 关键词)
            continue
        条目 = _解析分区表格(区文本, 前缀, 带序号)
        logger.info("  %s: %d 条", 关键词, len(条目))
        结果.extend(条目)
    logger.info("解析卡池一览: %d 条", len(结果))
    return 结果


def _提取分区(wikitext: str, 关键词: str) -> str:
    """截取 ==标题== 含关键词的分区正文"""
    标题们 = list(标题_RE.finditer(wikitext))
    for i, m in enumerate(标题们):
        if 关键词 not in m.group(1):
            continue
        终点 = 标题们[i + 1].start() if i + 1 < len(标题们) else len(wikitext)
        return wikitext[m.end():终点]
    return ""


def _表格行(区文本: str) -> list[list[str]]:
    """把分区里的第一个 wikitable 拆成行，每行是单元格文本列表。

    甄选池的单元格内嵌套了折叠 wikitable，用深度计数保证嵌套内容
    整体留在所在单元格里，不被外层的 |- 和 | 切开。
    """
    行们: list[list[str]] = []
    当前行: list[str] = []
    当前列: list[str] = []
    深度 = -1  # -1=尚未进入表格, 0=顶层表格, >0=嵌套表格

    def _收列() -> None:
        nonlocal 当前列
        if 当前列:
            当前行.append("\n".join(当前列).strip())
            当前列 = []

    def _收行() -> None:
        nonlocal 当前行
        _收列()
        if 当前行:
            行们.append(当前行)
            当前行 = []

    for line in 区文本.splitlines():
        s = line.strip()
        if 深度 == -1:
            if s.startswith("{|"):
                深度 = 0
            continue
        if 深度 > 0:
            if s.startswith("{|"):
                深度 += 1
            elif s.startswith("|}"):
                深度 -= 1
            当前列.append(line)
            continue
        if s.startswith("{|"):
            深度 += 1
            当前列.append(line)
        elif s.startswith("|}"):
            break
        elif s == "|-":
            _收行()
        elif s.startswith("|") or s.startswith("!"):
            _收列()
            当前列.append(单元格属性_RE.sub("", s[1:]))
        else:
            当前列.append(line)
    _收行()
    return 行们


def _解析分区表格(区文本: str, 前缀: str, 带序号: bool) -> list[dict]:
    结果: list[dict] = []
    for cells in _表格行(区文本):
        try:
            if 带序号:
                序号, 名单元格, 时间单元格, 六星单元格 = cells[0], cells[1], cells[2], cells[3]
            else:
                序号 = ""
                名单元格, 时间单元格, 六星单元格 = cells[0], cells[1], cells[2]
        except IndexError:
            continue
        tm = 时间_RE.search(时间单元格)
        if not tm:
            continue
        名称 = _卡池名称(前缀, 带序号, 序号, 名单元格)
        if not 名称:
            continue
        干员们 = list(dict.fromkeys(m.group(1).strip() for m in 干员_RE.finditer(六星单元格)))
        if 干员们:
            名称 = f"{名称} · {' / '.join(干员们)}"
        结果.append({
            "名称": 名称,
            "开始时间": f"{tm.group(1)} {tm.group(2)}:00",
            "结束时间": f"{tm.group(3)} {tm.group(4)}:00",
            "类型": 0,
        })
    return 结果


def _卡池名称(前缀: str, 带序号: bool, 序号: str, 名单元格: str) -> str:
    if 带序号:
        序号文本 = 序号.strip()
        if not 序号文本:
            return ""
        return f"{前缀}#{序号文本}" if 序号文本.isdigit() else f"{前缀}{序号文本}"
    for m in 链接_RE.finditer(名单元格):
        目标 = m.group(1).strip()
        if 目标.startswith(("文件:", "File:", "Image:")):
            continue
        名称 = (m.group(2) or 目标).strip().removeprefix("寻访模拟/")
        return f"{前缀}{re.sub(r'^【[^】]*】', '', 名称).strip()}"
    return ""
