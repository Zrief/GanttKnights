"""活动记录 — 数据在流水线里的唯一形态。

为什么不用 pandas
-----------------
这些数据在本项目里只做纯 CRUD：读 CSV → 解析时间 → 过滤 → 排序 → 逐行渲染。
没有一处用到 groupby / pivot / merge / resample / 时间索引。

而 `import pandas` 在 AstrBot 实例环境（Python 3.12 / pandas 3.0.5）实测要
**1186 ms**，是插件加载路径上最大的单笔开销（详见 docs/插件化.md「起点」）。
换成这个 dataclass 后，`src.流水线` 的导入从 1319 ms 降到约 200 ms。

字段命名刻意与 CSV 列名对应，便于对照数据文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class 活动:
    """一条活动/卡池/福利条目。

    `开始` / `结束` 一定是已解析的 datetime —— 解析失败的行在
    `筛选_活动.preprocess_data` 里就被丢弃了，因此下游无需再判空。
    """

    名称: str
    开始: datetime
    结束: datetime
    类型: int
    子类型: str = ""
    """大类里的细分，目前只有卡池在用：`限时` / `中坚` / `标准` / `甄选`。

    它只做两件事：甘特图左列据此分组（同名相邻）、`提醒文案.展示名` 据此把名字里的
    前缀与期号剥掉。空串 = 这个大类不细分（活动 / 福利 / 长期）。
    """
    来源: str = ""


子类型顺序 = ("限时", "中坚", "标准", "甄选")
"""同大类里的细分顺序 —— 甘特图左列从上到下就是这个次序；不认识的排最后。"""


def 子类型序数(子类型: str) -> int:
    return 子类型顺序.index(子类型) if 子类型 in 子类型顺序 else len(子类型顺序)


def 排序键(条目: 活动) -> tuple[int, int, datetime, datetime]:
    """在改造前 pandas 的 `sort_values(by=[类型, 结束, 开始], ascending=False)` 上，
    多插一档 `子类型`（2026-09-24：卡池要按池子种类成块，见 `子类型顺序`）。

    四键仍**全降序**，因此调用方用 `sorted(条目们, key=排序键, reverse=True)`；
    渲染层再 `reversed` 一次，图上从上到下就是"限时 → 中坚 → 标准 → 甄选 → …"。
    """
    return (条目.类型, 子类型序数(条目.子类型), 条目.结束, 条目.开始)
