"""活动数据快照与「和昨天比」的日差。

## 为什么有这个模块（2026-09-14 与用户对齐后的结论）

这个插件每天要回答的**唯一**问题是：**"今天和昨天比，多了什么、少了什么、时间改了什么。"**
性能不是问题（一次渲染 1.5s、长期开机），所以阶段四那套"签名缓存 + manifest + 跨日失效"
整套被删掉了（docs §17.4）；真正需要的是**一份昨天的数据**。

## 设计

- **快照** = `{名称: [开始时间, 结束时间, 类型]}` 的 JSON，写在 `<数据目录>/历史/活动_YYYY-MM-DD.json`；
- **每天第一次出图时冻结当天快照**：之后当天再刷新数据也不改它，
  这样同一天的多次出图与推送看到的是同一份"日差"（否则 08:00 推的和 10:00 看的会不一样）；
- **对比对象** = 时间上最近的那份**更早**的快照；中间隔了几天就写明"对比 N 天前"；
- **"消失"只报还该在未来发生的活动**：数据清理（`合并保存CSV` 的过期裁剪）会把早就结束的行删掉，
  那不是用户眼里的"活动没了"，`生成_警告` 已经在讲"已结束"。被 wiki 撤下/改期的才是新闻。

模块不 import matplotlib，只读写 CSV/JSON，可以直接在没装 AstrBot 的机器上测。
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger("ganttknights")

保留天数 = 14
"""历史快照保留多少天（一天一个几 KB 的 JSON，留着是为了"对比 N 天前"与人工回看）。"""

快照前缀 = "活动_"
最大列名数 = 5
"""文案里最多列几个活动名，超出用"等 N 个"（推送文字要短）。"""


def 读活动(csv路径: Path | str) -> dict[str, list[str]]:
    """`所有活动数据.csv` → `{名称: [开始时间, 结束时间, 类型]}`

    只取对比需要的列；同一名称重复出现时保留第一条（合并阶段的去重已经保证不会重复，
    这里只是不让坏数据把整个对比搞崩）。
    """
    结果: dict[str, list[str]] = {}
    try:
        with Path(csv路径).open(newline="", encoding="utf-8-sig") as f:
            for 行 in csv.DictReader(f):
                名称 = (行.get("名称") or "").strip()
                if 名称 and 名称 not in 结果:
                    结果[名称] = [(行.get(列) or "").strip()
                                  for 列 in ("开始时间", "结束时间", "类型")]
    except FileNotFoundError:
        logger.warning("活动数据还不存在，按空数据对比：%s", csv路径)
    except Exception:
        logger.exception("读取活动数据失败：%s", csv路径)
    return 结果


def _写JSON(路径: Path, 数据) -> None:
    """同目录临时文件 + `os.replace`（与渲染产物的原子写同一套做法）"""
    路径.parent.mkdir(parents=True, exist_ok=True)
    fd, 临时 = tempfile.mkstemp(dir=str(路径.parent), prefix=".快照-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(数据, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(临时, 路径)
    finally:
        if os.path.exists(临时):
            os.unlink(临时)


def 快照路径(历史目录: Path, 日期: date) -> Path:
    return Path(历史目录) / f"{快照前缀}{日期.isoformat()}.json"


def _已有快照(历史目录: Path) -> list[tuple[date, Path]]:
    """(日期, 路径) 列表，按日期升序；解析不出来的文件名直接跳过"""
    出: list[tuple[date, Path]] = []
    try:
        文件们 = list(Path(历史目录).glob(f"{快照前缀}*.json"))
    except OSError:
        return 出
    for p in 文件们:
        文本 = p.stem[len(快照前缀):]
        try:
            出.append((date.fromisoformat(文本), p))
        except ValueError:
            logger.warning("快照文件名不是日期，忽略：%s", p.name)
    return sorted(出)


def _清理(历史目录: Path, 保留: int) -> None:
    """只留最近 N 份（按日期）"""
    if 保留 <= 0:
        return
    for _, 路径 in _已有快照(历史目录)[:-保留]:
        try:
            路径.unlink(missing_ok=True)
        except OSError:
            logger.warning("旧快照删不掉：%s", 路径)


@dataclass(frozen=True)
class 日差:
    """"和上一次相比"的结果；`文本()` 直接给推送/状态页用。"""

    新日期: date
    旧日期: date | None = None
    新增: list[str] = field(default_factory=list)
    消失: list[str] = field(default_factory=list)
    改动: list[str] = field(default_factory=list)

    @property
    def 有变化(self) -> bool:
        return bool(self.新增 or self.消失 or self.改动)

    def 文本(self) -> str:
        """一行日差；没有变化时返回空串（调用方据此决定要不要附这句话）。"""
        if not self.有变化:
            return ""
        段 = []
        if self.旧日期 is None:
            前缀 = "首次记录"
        else:
            间隔 = (self.新日期 - self.旧日期).days
            前缀 = f"与 {self.旧日期:%m-%d} 相同" if 间隔 == 1 else f"与 {self.旧日期:%m-%d}（{间隔} 天前）相比"

        def 列(标题: str, 名们: list[str]) -> str:
            头 = "、".join(名们[:最大列名数])
            多 = f" 等 {len(名们)} 个" if len(名们) > 最大列名数 else ""
            return f"{标题}{头}{多}"

        if self.新增:
            段.append(列("🆕 新增 ", self.新增))
        if self.改动:
            段.append(列("✏️ 时间调整 ", self.改动))
        if self.消失:
            段.append(列("⏹ 不再列出 ", self.消失))
        return f"{前缀}：" + "；".join(段)


def 对比(旧: dict[str, list[str]], 新: dict[str, list[str]], 今天: date) -> tuple[list[str], list[str], list[str]]:
    """返回 (新增, 消失, 改动)。

    `消失` 只保留**结束时间在今天之后**的活动：更早结束的行是数据清理删掉的，
    不是"活动没了"（那属于 `生成_警告` 的"已结束"）。
    """
    新增 = sorted(set(新) - set(旧))
    消失 = sorted(名 for 名 in set(旧) - set(新)
                 if (旧[名][1] or "9999") >= 今天.isoformat())
    改动 = sorted(名 for 名 in set(旧) & set(新) if 旧[名] != 新[名])
    return 新增, 消失, 改动


def 记录并对比(csv路径: Path | str, 历史目录: Path | str, 今天: date,
               保留: int = 保留天数) -> 日差:
    """每天第一次调用时冻结当天快照，并返回与上一份快照的日差。

    - 当天快照已存在 → 不覆盖（当天多次出图/推送看到同一份日差）；
    - 没有任何更早的快照 → `旧日期=None`，只报"首次记录"。
    """
    历史目录 = Path(历史目录)
    快照 = 读活动(csv路径)
    今天路径 = 快照路径(历史目录, 今天)
    已有 = _已有快照(历史目录)
    更早 = [(日期, 路径) for 日期, 路径 in 已有 if 日期 < 今天]

    if not 今天路径.exists():
        _写JSON(今天路径, 快照)
        _清理(历史目录, 保留)

    旧日期, 旧数据 = None, {}
    if 更早:
        旧日期, 旧路径 = 更早[-1]
        try:
            旧数据 = json.loads(旧路径.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("旧快照读不出来，按首次记录处理：%s", 旧路径)
            旧日期, 旧数据 = None, {}

    新增, 消失, 改动 = 对比(旧数据, 快照, 今天) if 旧日期 else ([], [], [])
    return 日差(新日期=今天, 旧日期=旧日期, 新增=新增, 消失=消失, 改动=改动)


def 上次快照日期(历史目录: Path | str) -> str:
    """最近一份快照的日期（给 `/甘特图状态` 用）；没有则空串"""
    已有 = _已有快照(Path(历史目录))
    return 已有[-1][0].isoformat() if 已有 else ""
