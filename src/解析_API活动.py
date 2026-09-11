"""解析层 — 把 SMW ask 的查询结果转成活动条目

只负责"看懂 API 返回"：类型归类、时间戳转换、逐个活动调公告页
拆子活动。合并与存储见 汇总_活动.py。
"""

from __future__ import annotations

import logging

from src.获取_prts import 获取公告wikitext
from src.解析_公告 import 解析分区

logger = logging.getLogger("src.解析")

# ---------- API 活动类型 → 数值 ----------

API类型映射 = {
    "支线故事": 1, "主线": 1, "故事集": 1, "合作活动": 1,
    "其他活动": 1, "纪念活动": 1, "危机合约": 1,
    "矢量突破": 1, "卫戍协议": 1, "争锋频道": 1, "纷争演绎": 1,
    "登录活动": 2, "签到": 2,
    "生息演算": 99, "集成战略": 99, "剿灭": 99, "保全": 99,
}

名称类型规则 = [
    (["寻访", "中坚", "甄选", "招募", "限定", "标准池", "中坚池", "跨年"], 0),
    (["战斗", "SideStory", "故事集", "资源收集", "复刻", "联动"], 1),
    (["签到", "赠送", "领取", "月卡", "专享", "补给"], 2),
    (["家具", "时装", "新装", "主题", "上架", "风尚"], -1),
    (["剿灭", "保全", "生息", "集成战略"], 99),
]


def 分类事件(API类型: str = "", 事件名: str = "") -> int:
    if API类型 and API类型 in API类型映射:
        return API类型映射[API类型]
    for 关键词列表, 类型 in 名称类型规则:
        for kw in 关键词列表:
            if kw in 事件名:
                return 类型
    return 1


def 解析API时间戳(ts_info) -> str | None:
    """把 SMW 的 raw 时间转成 'YYYY-MM-DD HH:MM:00'

    raw 形如 1/2026/9/4/12/0/0，首段是日历标识（格里高利历=1）；
    兼容缺少首段的 6 段写法。
    """
    if isinstance(ts_info, dict):
        parts = ts_info.get("raw", "").split("/")
        if len(parts) >= 7:
            _, y, m, d, h, mi = parts[:6]
        elif len(parts) >= 6:
            y, m, d, h, mi = parts[:5]
        else:
            return None
        return f"{y}-{m.zfill(2)}-{d.zfill(2)} {h.zfill(2)}:{mi.zfill(2)}:00"
    return None


def 提取API时间(属性: dict, 键: str) -> str | None:
    值 = 属性.get(键)
    return 解析API时间戳(值[0]) if 值 else None


def API转活动列表(api原始: list[dict], 现在时间: str, 已解析来源: set[str] | None = None) -> list[dict]:
    """SMW ask 结果 → 活动条目列表

    开始时间优先取 活动开始时间cn（国服实际开跑时刻；无 cn 后缀的主属性
    记的是 4:00 日切时间）。公告解析成功过的活动（来源在 已解析来源 里）
    直接跳过——公告里的剿灭/保全等长期条目已增量存在 store 里，无需重复
    抓取。解析失败回退 API 时间的条目不记来源，下次运行会重试公告。
    """
    已解析来源 = 已解析来源 or set()
    活动列表: list[dict] = []
    for idx, (事件名, 条目) in enumerate(api原始):
        属性 = 条目.get("printouts", {})
        开始 = 提取API时间(属性, "活动开始时间cn") or 提取API时间(属性, "活动开始时间")
        结束 = 提取API时间(属性, "活动结束时间")
        if not (开始 and 结束 and 结束 > 现在时间):
            continue

        api类型 = (属性.get("活动类型") or [None])[0] or ""
        类型 = 分类事件(API类型=api类型 or "", 事件名=事件名)

        显示名 = 事件名
        if api类型 == "集成战略":
            显示名 = f"【肉鸽】{事件名}"
        elif api类型 == "合作活动":
            显示名 = f"【联动】{事件名}"

        if 显示名 in 已解析来源:
            logger.info("  [%d] %s 公告已解析过，跳过", idx + 1, 显示名)
            continue

        公告 = 获取公告wikitext(事件名)
        if 公告 is None:
            活动列表.append({"名称": 显示名, "开始时间": 开始, "结束时间": 结束, "类型": 类型, "_parent": ""})
            logger.info("  [%d] %s → API 时间（%s）", idx + 1, 显示名, 类型)
            continue

        子活动 = 解析分区(公告, 显示名)
        if 子活动:
            活动列表.extend(子活动)
            logger.info("  [%d] %s → %d 条子活动", idx + 1, 事件名, len(子活动))
        else:
            # 公告页存在但没解析到子活动（页面结构特殊），回退 API 时间，
            # 不记来源，下次运行会重试
            活动列表.append({"名称": 显示名, "开始时间": 开始, "结束时间": 结束, "类型": 类型, "_parent": ""})
            logger.info("  [%d] %s 公告页无子活动，回退 API 时间（%s）", idx + 1, 显示名, 类型)

    return 活动列表
