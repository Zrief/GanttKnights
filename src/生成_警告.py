"""生成过期警告文本 — 供聊天机器人 / 控制台输出"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

type 图标表 = dict[int, str]

类型图标: 图标表 = {0: "🎯", 1: "📅", 2: "🎁", -1: "🛒", 99: "📌"}
类型名称: 图标表 = {0: "卡池", 1: "行动", 2: "福利", -1: "商店", 99: "长期"}


def 生成警告(
    df: pd.DataFrame,
    提醒天数: int = 3,
    紧急天数: int = 1,
    新增内容: dict | None = None,
) -> str:
    """生成过期警告文本。

    参数:
        df: 经过 preprocess_data 过滤后的活动 DataFrame
        提醒天数: 多少天内过期就提醒
        紧急天数: 当天内过期标为紧急
        新增内容: 首页解析出的新增时装/模组（{"时装": [...], "模组": [...]}）

    返回:
        格式化的警告文本，无内容时返回空字符串
    """
    段 = _新增段落(新增内容 or {})

    if df.empty:
        return "\n".join(段)

    now = datetime.now()
    now_date = now.date()
    截止日期 = now + pd.Timedelta(days=提醒天数)

    # 筛选将要过期的活动
    col_end = df.columns[2]
    col_type = df.columns[3]
    col_name = df.columns[0]

    mask = (df[col_end] > now) & (df[col_end] <= 截止日期)
    警告df = df[mask].copy()

    # 按结束时间排序（最紧急的在前）
    警告df = 警告df.sort_values(by=col_end)

    紧急行: list[str] = []
    普通行: list[str] = []

    for _, row in 警告df.iterrows():
        name = row[col_name]
        end_time: datetime = row[col_end]
        atype = int(row[col_type])

        icon = 类型图标.get(atype, "📋")
        tname = 类型名称.get(atype, "?")

        剩余天数 = (end_time.date() - now_date).days
        end_str = end_time.strftime("%m月%d日 %H:%M")

        if 剩余天数 == 0:
            标记 = "🔥 今天结束"
        elif 剩余天数 <= 紧急天数:
            标记 = "⚠️ 明天结束" if 剩余天数 == 1 else f"⚠️ 剩 {剩余天数} 天"
        else:
            标记 = f"剩 {剩余天数} 天"

        行 = f"  {icon} [{tname}] {name}"
        行 += f"\n    截止: {end_str}  {标记}"

        if 剩余天数 <= 紧急天数:
            紧急行.append(行)
        else:
            普通行.append(行)

    # 组装
    有紧急 = bool(紧急行)
    有普通 = bool(普通行)
    if 有紧急:
        段.append("🔴 博士，以下行动即将结束——")
        段.extend(紧急行)
    if 有普通:
        header = "📋 还有这些即将到期" if 有紧急 else "📋 博士，以下行动即将到期"
        段.append(f"\n{header}（{提醒天数}天内）")
        段.extend(普通行)
    if 有紧急 or 有普通:
        段.append(f"\n⏰ 共 {len(警告df)} 项行动即将到期，博士请留意。")

    return "\n".join(段)


def _新增段落(新增内容: dict) -> list[str]:
    """把首页新增凭证/时装/模组拼成提醒段落（顺序与底栏三区一致），无内容返回空列表"""
    凭证 = 新增内容.get("凭证") or []
    时装 = 新增内容.get("时装") or []
    模组 = 新增内容.get("模组") or []
    if not 凭证 and not 时装 and not 模组:
        return []

    数据日期 = str(新增内容.get("更新时间", ""))[5:10]
    header = "✨ 罗德岛上新" + (f"（{数据日期} 数据）" if 数据日期 else "") + "——"
    段 = [header]
    if 凭证:
        段.append("  🎖 凭证兑换：" + "、".join(i["干员"] for i in 凭证))
    if 时装:
        段.append("  👗 新增时装：" + "、".join(i["干员"] for i in 时装))
    if 模组:
        名单 = "、".join(
            f"{i['干员']}「{i['名称']}」" if i.get("名称") else i["干员"] for i in 模组
        )
        段.append("  🔩 新增模组：" + 名单)
    return 段
