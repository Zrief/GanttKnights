"""网络层 — 只负责发 HTTP 请求，返回原始数据"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger("src.网络")

PRTS_API = "https://prts.wiki/api.php"
PRTS_HOME = "https://prts.wiki/"

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
        "|?官网链接"
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
                "page": 公告页标题(事件名),
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


def 公告页标题(事件名: str) -> str:
    """活动公告页的页面名（`获取公告wikitext()` 与修订探测共用同一份拼接规则）"""
    return f"{事件名}/活动公告"


def 取页面修订时间(标题们: list[str]) -> dict[str, str]:
    """一次请求拿多份公告页的**最后修订时间**（ISO），用于"这页被追加过内容吗"。

    为什么需要它：公告页会被追加（新的剿灭轮换就写在当期活动的公告页里），
    所以"以前解析过"不等于"内容没变"。逐页重新抓取太贵（每天几十个页面），
    而 MediaWiki 允许一次 `titles=A|B|C…`（普通用户上限 50 个）拿全部修订时间 ——
    一次请求就能知道该抓哪几页。

    返回 `{页面名: 修订时间}`；请求失败或页面不存在时**不**出现在结果里
    （调用方据此退回"只在没解析过时才抓"的保守行为）。
    """
    结果: dict[str, str] = {}
    if not 标题们:
        return 结果
    for i in range(0, len(标题们), 50):
        批 = 标题们[i:i + 50]
        # ⚠️ 多标题查询**不能**带 rvlimit（MediaWiki 报 invalidparammix：
        # "titles … may only be used on a single page"）。不带就默认每页取最新一条。
        resp = 请求(PRTS_API, params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "revisions",
            "rvprop": "timestamp",
            "titles": "|".join(批),
        })
        if resp is None:
            continue
        try:
            页们 = resp.json().get("query", {}).get("pages", [])
        except Exception:
            logger.exception("修订时间返回体解析失败")
            continue
        if isinstance(页们, dict):        # 没有 formatversion 时是 {pageid: {...}}
            页们 = list(页们.values())
        for 页 in 页们:
            标题 = 页.get("title")
            修订 = (页.get("revisions") or [{}])[0].get("timestamp")
            if 标题 and 修订:
                结果[标题] = str(修订)
    return 结果


def 获取首页() -> str | None:
    """获取首页渲染后的 HTML（亮点干员板块是动态生成的，wikitext 里没有）"""
    resp = 请求(PRTS_HOME)
    if resp is None:
        return None
    return resp.text


def 下载图片(url: str, 目标路径: str | Path) -> bool:
    """下载图片到本地，目标文件已存在（缓存命中）则跳过下载"""
    目标 = Path(目标路径)
    if 目标.exists() and 目标.stat().st_size > 0:
        return True
    resp = 请求(url)
    if resp is None:
        return False
    目标.write_bytes(resp.content)
    logger.info("  已缓存图片: %s", 目标.name)
    return True
