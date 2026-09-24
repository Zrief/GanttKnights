"""汇总层 — 合并商店、去重排序、活动数据 CSV 增量存储"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import 长期活动
from .数据保护 import 校验写回
from .日志 import logger

# store 里过期超过这个天数的条目自动清理
过期保留天数 = 7


@dataclass(frozen=True)
class 合并差异:
    """这次合并相对 CSV 里**原有内容**的变化（都放显示名，给用户看）。

    为什么由合并来回答：**合并动作本身就天然知道**哪些键是新来的、哪些被覆盖改了、
    哪些因为过了清理线被删掉——不需要事后再拿两份数据对比（用户 2026-09-14 指出的）。

    ⚠️ 刻意**没有**"不再列出"这一项：抓取是增量的（公告页没变化就不再重读，
    见 `解析_API活动._需重取公告`），所以"这次没抓到"根本推不出"源里没了"——
    实测它会每天把只有公告才有的条目（如剿灭）误报成"不再列出"。
    真被撤下的活动只能等它过期，由 `过期清理` 体现。
    """

    新增: tuple[str, ...] = field(default_factory=tuple)
    改动: tuple[str, ...] = field(default_factory=tuple)
    过期清理: int = 0
    原有条数: int = 0

    @property
    def 有变化(self) -> bool:
        return bool(self.新增 or self.改动 or self.过期清理)

    @property
    def 首次(self) -> bool:
        """CSV 原本不存在 → 这不是"变化"，是"初次建立"（别报成几千条新增）"""
        return self.原有条数 == 0


# ---------- 商店合并 ----------

def 合并商店(活动列表: list[dict]) -> list[dict]:
    """合并同一父活动下的多条礼包为一条"""
    groups: dict[str, list[dict]] = {}
    for it in 活动列表:
        key = it.get("_parent", "")
        groups.setdefault(key, []).append(it)

    结果 = []
    for 父名, 组 in groups.items():
        礼包 = [i for i in 组 if i["类型"] == -1]
        其他 = [i for i in 组 if i["类型"] != -1]

        if len(礼包) >= 2:
            最早 = min(礼包, key=lambda x: x["开始时间"])
            最晚 = max(礼包, key=lambda x: x["结束时间"])
            结果.append({
                "名称": f"{父名} 礼包" if 父名 else "礼包",
                "开始时间": 最早["开始时间"],
                "结束时间": 最晚["结束时间"],
                "类型": -1,
                "_parent": 父名,
            })
        else:
            结果.extend(礼包)
        结果.extend(其他)
    return 结果


# ---------- 去重排序 ----------

def _提取干员(名称: str) -> str:
    """从卡池名称中提取 · 后面的干员名，用于卡池去重"""
    if " · " in 名称:
        return 名称.split(" · ", 1)[1]
    return ""


def _身份键(名称: str, 类型: int) -> str:
    """合并与去重共用的**身份**键：卡池用干员名，长期剥掉开头的 `【玩法】` 前缀，其余用原始名。

    长期条目的前缀（玩法名）在数据源里换过写法——公告简写 `【剿灭】`、官方名
    `【剿灭作战】`、还有裸名无前缀（`长期活动.py` 的"两副面孔"）——拿原始名当键，
    改名前后的两行就互相覆盖不到，会在 CSV 里**永久并存**、越抓越多
    （2026-09-24 实测：`默祷圣祠`×2、`重启锚点`×2，bootstrap 也清不掉——
    它们 2027 年才结束，永远不过期）。前缀语义归 `长期活动` 唯一定义管，
    这里只认"类型 99 的开头【…】是玩法前缀"，不另起一张表。
    """
    if 类型 == 0:
        干员 = _提取干员(名称)
        if 干员:
            return 干员
    if 类型 == 长期活动.类型值 and 名称.startswith("【") and "】" in 名称:
        return 名称.split("】", 1)[1]
    return 名称


def 去重排序(活动列表: list[dict]) -> list[dict]:
    """按身份键+时间去重，按开始时间排序"""
    seen = set()
    seen登录窗口 = set()
    去重后 = []
    for a in 活动列表:
        if a["类型"] == 2:
            # 登录/签到活动：公告里的签到板块常不带本名（如月行水上的
            # 签到其实就是此夜同行），按时间窗去重，保留先出现的 ask 官方名
            key = ("登录", a["开始时间"], a["结束时间"])
            if key in seen登录窗口:
                continue
            seen登录窗口.add(key)
            去重后.append(a)
            continue
        key = (_身份键(a["名称"], a["类型"]), a["开始时间"], a["结束时间"], a["类型"])
        if key not in seen:
            seen.add(key)
            去重后.append(a)
    去重后.sort(key=lambda e: e["开始时间"])
    return 去重后


# ---------- 增量存储 ----------


def 合并保存CSV(
    新活动列表: list[dict],
    输出路径: str | Path,
    现在时间: str,
    允许大幅清理: bool = False,
) -> 合并差异:
    """增量保存：读已有数据 + 新数据覆盖 + 清理过期条目 + 写回；返回本次的**合并差异**

    store 带"来源"列（条目出自哪个活动公告；卡池和 API 兜底条目为空）。
    来源非空说明该公告解析成功过，主流程据此知道"这组的公告读出过内容"。

    注意 现在时间 不只用于记录，它还推导清理线（`现在时间 - 过期保留天数`），
    因此传错时间会静默丢数据。写回前由 `数据保护.校验写回` 兜一道：
    若本次会把已有数据清空、或清理比例过高，则抛 `数据保护拦截` 且**不写盘**。
    确实需要大清理时显式传 `允许大幅清理=True`。
    """
    路径 = Path(输出路径)
    字段 = ["名称", "开始时间", "结束时间", "类型", "子类型", "来源"]

    已有: dict[str, dict] = {}
    if 路径.exists():
        with open(路径, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if not row.get("名称", "").strip():
                    continue
                类型 = int(row["类型"])
                键名 = _身份键(row["名称"], 类型)
                已有[键名] = {
                    "名称": row["名称"],
                    "开始时间": row["开始时间"],
                    "结束时间": row["结束时间"],
                    "类型": 类型,
                    "子类型": (row.get("子类型") or "").strip(),
                    "来源": row.get("来源", ""),
                }

    # 合并进新数据之前先记下"原文件里实际有几条"，供护栏判断丢失幅度
    原有条数 = len(已有)
    原有快照 = {k: (r["名称"], r["开始时间"], r["结束时间"], r["类型"]) for k, r in 已有.items()}

    清理线 = (
        datetime.strptime(现在时间, "%Y-%m-%d %H:%M:%S") - timedelta(days=过期保留天数)
    ).strftime("%Y-%m-%d %H:%M:%S")

    本次: dict[str, tuple[str, str, str, int]] = {}
    for a in 新活动列表:
        键 = _身份键(a["名称"], a["类型"])
        本次[键] = (a["名称"], a["开始时间"], a["结束时间"], a["类型"])
        已有[键] = {
            "名称": a["名称"],
            "开始时间": a["开始时间"],
            "结束时间": a["结束时间"],
            "类型": a["类型"],
            "子类型": a.get("子类型", ""),
            "来源": a.get("_parent", ""),
        }

    所有 = [r for r in 已有.values() if r["结束时间"] >= 清理线]
    删了 = len(已有) - len(所有)
    if 删了:
        logger.debug("  清理过期条目 %d 条（结束时间早于 %s）", 删了, 清理线)

    # —— 差异：这次抓取相对原有内容改了什么 ——
    # 只算**能留下来**的行：抓取源里总会带回一堆早已结束的条目（卡池一览尤其多），
    # 它们进来就被清理线删掉，不该每天在日差里刷一遍（实测未过滤时每天 54 条"新增"）。
    存活键 = {k for k, r in 已有.items() if r["结束时间"] >= 清理线}
    新增 = tuple(v[0] for k, v in 本次.items() if k in 存活键 and k not in 原有快照)
    改动 = tuple(v[0] for k, v in 本次.items()
                if k in 存活键 and k in 原有快照 and v != 原有快照[k])
    # `过期清理` = **原本就在 store 里、这次没留下来**的条数（含"新时间已经过期"那种）。
    # 不数那些抓取源每天都会带回、进来就被清理线删掉的条目（卡池一览尤其多）——
    # 它们从没进过 store，每天报一次"清理了 53 条"纯属噪音。
    清理了原有的 = sum(1 for k in 原有快照 if k not in 存活键)
    if 原有条数 == 0:
        # 首次建立没有"原有内容"可比：不该报成"新增了 300 条活动"（`首次` 标记已经说明一切）
        新增 = 改动 = ()

    if not 允许大幅清理:
        校验写回(原有条数, len(所有))
    elif 原有条数 and len(所有) * 2 < 原有条数:
        logger.warning(
            "  大幅清理已放行：%d 条 → %d 条（调用方显式传了 允许大幅清理=True）",
            原有条数, len(所有),
        )

    所有.sort(key=lambda e: e["开始时间"])
    with open(路径, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=字段)
        writer.writeheader()
        writer.writerows(所有)

    差异 = 合并差异(新增=新增, 改动=改动, 过期清理=清理了原有的, 原有条数=原有条数)
    if 差异.有变化:
        logger.debug("  本次合并：新增 %d / 改动 %d / 过期清理 %d",
                    len(新增), len(改动), 清理了原有的)
    return 差异
