"""筛选 — 读活动数据 CSV，解析时间、丢弃坏行、按时间窗与类型过滤、排序。

改造自 pandas 版（见 docs/插件化路线.md 阶段二·五）。行为必须与旧实现等价，
三个容易改错的点已就地标注：

1. 旧版 `pd.to_datetime(..., errors="coerce")` 是**静默降级**：解析不了的行
   记一条 warning 后被丢弃，而不是让整条流程崩溃。这里保留该行为。
2. 旧版 `df[col] != -1` 与 `int(row)` 依赖 read_csv 把「类型」推成 int；
   这里显式 `int()` 转换。
3. 旧版排序是 `sort_values(by=[类型, 结束, 开始], ascending=False)`（三键全降序），
   随后渲染层再 `iloc[::-1]` 倒序，两处配合才得到"卡池在上、长期在下"。
   这里保持完全相同的排序契约。
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta

from .config import settings
from .活动 import 活动, 排序键

logger = logging.getLogger(__name__)

# 时间列接受的格式：主格式来自本项目自己写的 CSV，其余为容错
时间格式们 = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def _解析时间(原始: str) -> datetime | None:
    """解析时间列；失败返回 None（调用方据此丢弃该行，与旧版 coerce 行为一致）"""
    文本 = (原始 or "").strip()
    if not 文本:
        return None
    for 格式 in 时间格式们:
        try:
            return datetime.strptime(文本, 格式)
        except ValueError:
            continue
    # 兜底：容忍 ISO 形式（如 2026-09-13T12:00:00）
    try:
        return datetime.fromisoformat(文本)
    except ValueError:
        return None


def _读CSV(路径) -> tuple[list[活动], int]:
    """读 CSV → (记录列表, 坏行数)。文件缺失或读取失败返回空列表。"""
    记录: list[活动] = []
    坏行 = 0
    try:
        with open(路径, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                名称 = (row.get("名称") or "").strip()
                if not 名称:
                    continue
                开始 = _解析时间(row.get("开始时间", ""))
                结束 = _解析时间(row.get("结束时间", ""))
                if 开始 is None or 结束 is None:
                    坏行 += 1
                    continue
                try:
                    类型 = int((row.get("类型") or "").strip())
                except ValueError:
                    坏行 += 1
                    continue
                记录.append(活动(
                    名称=名称,
                    开始=开始,
                    结束=结束,
                    类型=类型,
                    来源=(row.get("来源") or "").strip(),
                ))
    except FileNotFoundError:
        logger.error("数据文件不存在: %s", 路径)
    except Exception:
        logger.exception("读取数据文件失败: %s", 路径)
    return 记录, 坏行


def preprocess_data(
    all_data_path: str | None = None,
    *,
    now: datetime | None = None,
    left_border: datetime | None = None,
    right_border: datetime | None = None,
) -> list[活动]:
    """按时间窗过滤出"近期活动"，按类型/结束/开始三键降序返回。

    返回 `list[活动]`（不再是 DataFrame）。空列表表示无符合条件的活动。
    """
    路径 = all_data_path or settings.all_data_path
    now = now or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    left_border = left_border or now - timedelta(days=settings.left_offset_days)
    right_border = right_border or now + timedelta(
        days=settings.right_offset_days - now.weekday()
    )

    记录, 坏行 = _读CSV(路径)
    if not 记录:
        if 坏行:
            logger.warning("数据文件无可用行（丢弃 %d 条日期/类型无法解析的行）", 坏行)
        else:
            logger.warning("数据文件为空: %s", 路径)
        return []

    if 坏行:
        logger.warning("丢弃 %d 条日期或类型无法解析的活动", 坏行)

    # 过滤：剔除已结束超过 future_buffer_hours 的、以及起点晚于右边界的、以及商店(-1)
    截止 = now + timedelta(hours=settings.future_buffer_hours)
    筛选后 = [
        e for e in 记录
        if e.结束 > 截止 and e.开始 < right_border and e.类型 != -1
    ]

    if not 筛选后:
        logger.warning(
            "过滤后无近期活动数据 (窗口 %s ~ %s)", left_border.date(), right_border.date()
        )
        return []

    筛选后.sort(key=排序键, reverse=True)
    return 筛选后
