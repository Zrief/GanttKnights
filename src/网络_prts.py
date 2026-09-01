"""网络层 — 只负责发 HTTP 请求，返回原始数据"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("src.网络")

PRTS_API = "https://prts.wiki/api.php"
PRTS_BASE = "https://prts.wiki/w"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
CLIENT = httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
logging.getLogger("httpx").setLevel(logging.WARNING)


def _请求(url: str, **kwargs) -> httpx.Response:
    """带 3 次重试的 GET 请求"""
    for attempt in range(3):
        try:
            r = CLIENT.get(url, **kwargs)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise
            if attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
    raise RuntimeError("请求失败")


def 获取事件列表(limit: int = 10) -> list[dict]:
    """从 PRTS Wiki API 获取最近活动的结构化数据"""
    query = (
        "[[Category:活动]]"
        "|?活动开始时间"
        "|?活动结束时间"
        "|?活动类型"
        "|sort=活动开始时间"
        "|order=desc"
        f"|limit={limit}"
    )
    resp = _请求(PRTS_API, params={"action": "ask", "format": "json", "query": query})
    results = resp.json().get("query", {}).get("results", {})
    if isinstance(results, dict):
        return list(results.items())
    return []


def 获取公告页(事件名: str) -> BeautifulSoup | None:
    """获取活动公告页 HTML，不存在则返回 None"""
    page = quote(f"{事件名}/活动公告", safe="")
    try:
        resp = _请求(f"{PRTS_BASE}/{page}")
        return BeautifulSoup(resp.text, "html.parser")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
