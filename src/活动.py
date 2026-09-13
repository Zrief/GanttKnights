"""活动记录 — 数据在流水线里的唯一形态。

为什么不用 pandas
-----------------
这些数据在本项目里只做纯 CRUD：读 CSV → 解析时间 → 过滤 → 排序 → 逐行渲染。
没有一处用到 groupby / pivot / merge / resample / 时间索引。

而 `import pandas` 在 AstrBot 实例环境（Python 3.12 / pandas 3.0.5）实测要
**1186 ms**，是插件加载路径上最大的单笔开销（详见 docs/插件化路线.md §5.5）。
换成这个 dataclass 后，`src.流水线` 的导入从 1319 ms 降到约 200 ms。

字段命名刻意与 CSV 列名对应，便于对照数据文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# 类型编码：与 CSV 的「类型」列一致（见 main/流水线 的类型关键词表）
类型_卡池 = 0
类型_活动 = 1
类型_福利 = 2
类型_商店 = -1
类型_长期 = 99


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
    来源: str = ""


def 排序键(条目: 活动) -> tuple[int, datetime, datetime]:
    """与改造前 pandas 的 `sort_values(by=[类型, 结束, 开始], ascending=False)` 等价。

    pandas 是**三键全降序**，因此调用方用 `sorted(条目们, key=排序键, reverse=True)`。
    int 与 datetime 都支持比较，无需额外转换。
    """
    return (条目.类型, 条目.结束, 条目.开始)
