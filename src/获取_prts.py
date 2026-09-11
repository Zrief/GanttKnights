"""网络层 — 只负责发 HTTP 请求，返回原始数据"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("src.网络")

PRTS_API = "https://prts.wiki/api.php"

CLIENT = httpx.Client(timeout=30, follow_redirects=True)
logging.getLogger("httpx").setLevel(logging.WARNING)

_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError)


def 请求(url: str, **kwargs) -> httpx.Response | None:
    """带 3 次重试的 GET 请求，网络完全不可用时返回 None"""
    for attempt in range(3):
        try:
            r = CLIENT.get(url, **kwargs)
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise
            if attempt == 2:
                logger.warning("HTTP %s: %s", e.response.status_code, url)
                return None
        except _RETRYABLE:
            if attempt == 2:
                logger.warning("网络不可达（已重试 3 次）: %s", url)
                return None
        except Exception:
            if attempt == 2:
                logger.warning("请求异常: %s", url, exc_info=True)
                return None
    return None


def 获取事件列表(limit: int = 50) -> list[dict]:
    """从 PRTS Wiki API 获取近期活动的结构化数据

    联动等活动不在 Category:活动 里（如 月行水上 只挂在
    分类:支线故事/分类:联动活动），所以用类型分类的并集一次查全。
    """
    活动分类 = [
        "活动", "支线故事", "联动活动", "故事集", "合作活动", "危机合约",
        "集成战略", "生息演算", "纪念活动", "其他活动", "主线", "登录活动",
        "签到", "剿灭", "保全", "矢量突破", "卫戍协议", "争锋频道", "纷争演绎",
    ]
    query = (
        "[[Category:" + "||".join(活动分类) + "]]"
        "|?活动开始时间"
        "|?活动结束时间"
        "|?活动开始时间cn"
        "|?活动类型"
        "|sort=活动开始时间"
        "|order=desc"
        f"|limit={limit}"
    )
    resp = 请求(PRTS_API, params={"action": "ask", "format": "json", "query": query})
    if resp is None:
        return []
    results = resp.json().get("query", {}).get("results", {})
    if isinstance(results, dict):
        return list(results.items())
    return []


def 获取公告wikitext(事件名: str) -> str | None:
    """获取活动公告页的 wikitext 源码，页面不存在或为空则返回 None"""
    try:
        resp = 请求(
            PRTS_API,
            params={
                "action": "parse",
                "page": f"{事件名}/活动公告",
                "prop": "wikitext",
                "format": "json",
            },
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
    if resp is None:
        return None
    数据 = resp.json()
    if "error" in 数据:  # missingtitle 等错误以 HTTP 200 + error body 返回
        return None
    字段 = 数据.get("parse", {}).get("wikitext", {})
    wikitext = 字段.get("*", "") if isinstance(字段, dict) else str(字段)
    return wikitext or None
