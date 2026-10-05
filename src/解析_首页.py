"""解析层 — PRTS 首页"新增时装/新增模组"板块

亮点干员板块由 wiki 动态生成（首页 wikitext 源码里没有），只能解析渲染
HTML。以板块标题文本为主锚点、mp-operators-title 类名做板块边界；
href/title/图标 src 逐属性独立提取，不依赖标签内属性顺序。
板块本身没有时间信息，展示时挂到当前活动/版本窗口。

另含一套**备用取法**（解析数据子页/自算凭证）：PRTS 首页在皮肤迁移，
三栏的真身是两个机器可读数据子页（旧版 HTML 与新版共用这份数据）。
主路径（HTML 解析）整块失效时由 流水线.更新增预告 切过来用。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import quote, urljoin

from .获取_prts import PRTS_API, 请求
from .日志 import logger

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
        logger.debug("  首页新增%s: %d 条", 类型, len(条目们))
    return 结果


def _缓存文件名(类型: str, 干员: str, 名称: str) -> str:
    名 = f"{类型}_{干员}" + (f"_{名称}" if 名称 else "")
    return 非法文件字符.sub("_", 名) + ".png"


# ---------------- 备用取法：数据子页（主路径整块失效时顶上，见 流水线.更新增预告） ----------------
#
# 三栏数据的真身是「首页/亮点干员/新增皮肤(模组)/数据」两个机器可读子页——旧版 HTML
# 结构与新版首页共用这份数据，皮肤迁移删掉 /旧版 页后它们仍在。
# 图标不在数据页里，但 wiki 模板的文件名规则是确定的，零请求本地构造：
#   时装 头像_{干员}_skin{N}.png / 模组 头像_{干员}_2.png（"2" 是 wiki 模板硬编码）/ 凭证 头像_{干员}.png
# URL 的散列目录取文件名 MD5（MediaWiki 规则），实测与首页引用逐字一致。

MEDIA = "https://media.prts.wiki"
甄选排除 = {"中坚甄选", "跨年欢庆·中坚"}

时装数据解析 = re.compile(r"1=([^:,]+):skin=(\d+)")
模组数据解析 = re.compile(r"1=([^:,]+):2=([^:,]+):3=([^,]+)")


def 构造图标URL(文件名: str) -> str:
    摘要 = hashlib.md5(文件名.encode()).hexdigest()
    return f"{MEDIA}/{摘要[0]}/{摘要[:2]}/{quote(文件名)}"


def 解析数据子页(时装文本: str, 模组文本: str) -> dict[str, list[dict]]:
    """两个数据子页 → 与 解析新增内容 同构的预告 dict（凭证另由 自算凭证 补上）。

    数据页格式（页名即上面的注释）：时装 `1=空构:skin=1,1=承曦格雷伊:skin=3`，
    模组 `1=结城理:2=PUM-Y:3=彼此的声音,…`。"""
    时装们 = []
    for 干员, skin in 时装数据解析.findall(时装文本 or ""):
        干员 = 干员.strip()
        时装们.append({
            "干员": 干员, "名称": "",
            "图标": 构造图标URL(f"头像_{干员}_skin{skin}.png"),
            "图标文件名": _缓存文件名("时装", 干员, ""),
        })
    模组们 = []
    for 干员, _代号, 模组名 in 模组数据解析.findall(模组文本 or ""):
        干员, 模组名 = 干员.strip(), 模组名.strip()
        模组们.append({
            "干员": 干员, "名称": 模组名,
            "图标": 构造图标URL(f"头像_{干员}_2.png"),
            "图标文件名": _缓存文件名("模组", 干员, 模组名),
        })
    return {"时装": 时装们, "模组": 模组们, "凭证": []}


def 自算凭证(现在时间: datetime) -> list[dict]:
    """凭证兑换自算：与 wiki「凭证兑换」板块同款的两条 ask（查当前开放池的商店兑换干员）。

    注：SMW 的 [[属性::!值]] 否定经 api.php 会静默返回空（wiki 页面上能用），
    所以中坚寻访的「排除中坚甄选/跨年欢庆·中坚」在这里用 Python 过滤。"""
    截至时刻 = 现在时间.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    条目们: list[dict] = []
    seen: set[str] = set()
    for 分类, 带名 in (("常驻标准寻访", False), ("中坚寻访", True)):
        查询 = (f"[[分类:国服寻访]][[分类:{分类}]]"
                f"[[寻访开启时间cn::<<{截至时刻}]][[寻访关闭时间cn::>>{截至时刻}]]|?商店兑换干员"
                + ("|?寻访名cn" if 带名 else ""))
        resp = 请求(PRTS_API, params={"action": "ask", "format": "json", "query": 查询})
        if resp is None:
            continue
        results = resp.json().get("query", {}).get("results", {})
        for _, 数据 in (results.items() if isinstance(results, dict) else ()):
            printouts = 数据.get("printouts", {})
            if 带名 and any(名 in 甄选排除 for 名 in printouts.get("寻访名cn", [])):
                continue
            for 名 in printouts.get("商店兑换干员", []):
                名 = str(名).strip()
                if not 名 or 名 in seen:
                    continue
                seen.add(名)
                条目们.append({
                    "干员": 名, "名称": "",
                    "图标": 构造图标URL(f"头像_{名}.png"),
                    "图标文件名": _缓存文件名("凭证", 名, ""),
                })
    return 条目们
