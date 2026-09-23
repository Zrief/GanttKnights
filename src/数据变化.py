"""最近一次数据变化 —— "今天和昨天比变了什么"的落盘记录。

## 为什么不在渲染时对比两份数据

每天要回答的**唯一**问题是"今天和昨天比，多了什么、少了什么、时间改了什么"。
这件事**不需要快照、也不需要事后对比**：抓取完做合并的那一刻，`合并保存CSV`
手里就有原有内容和本次抓取的内容，天然知道谁是新来的、谁被改了、谁被清理线删了
（`src/汇总_活动.py::合并差异`）。本模块只负责把那份差异**记下来**：

- 为什么要落盘：合并一天只发生一次（`今天写过()` 守着），而**推送发生在几小时之后**，
  还可能经历插件重载 —— 差异必须能在那时被重新读到；
- 为什么按天冻结：当天第一次合并的结果就是"今天的日差"。之后同一天再刷新数据
  （手动 `--force`）不再改写它，这样早上推的和晚上看的说的是同一件事。

文件：`<数据目录>/最近数据变化.json`，形如

```json
{"日期": "2026-09-14", "对比日期": "2026-09-13",
 "新增": ["【剿灭】默祷圣祠"], "改动": ["重启锚点"], "过期清理": 3}
```

刻意**没有**"不再列出"：抓取是增量的（公告页没变化就不重读），"这次没抓到"推不出"源里没了"
——那段推理见 `src/汇总_活动.py::合并差异` 的 docstring。

模块只用到标准库（连同 `src/汇总_活动.py`、`src/提醒文案.py` 这两个同包依赖——
后者只 import `re`），可以在没装 AstrBot / matplotlib 的机器上直接测。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .汇总_活动 import 合并差异
from .提醒文案 import 展示名

logger = logging.getLogger("ganttknights")

文件名 = "最近数据变化.json"
最大列名数 = 3
"""文案里最多列几个活动名，超出用"等 N 个"（推送文字要短）。"""


@dataclass(frozen=True)
class 数据变化:
    """一次合并带来的变化 + 它对比的是哪一天。"""

    日期: str = ""
    对比日期: str = ""
    新增: tuple[str, ...] = field(default_factory=tuple)
    改动: tuple[str, ...] = field(default_factory=tuple)
    过期清理: int = 0
    首次: bool = False

    @property
    def 有变化(self) -> bool:
        return bool(self.新增 or self.改动 or self.过期清理)

    def 文本(self) -> str:
        """一行日差；没有可说的返回空串（调用方据此决定要不要附这句话）。

        "首次建立"与"没有任何变化"都返回空串：前者不该在群里刷一长串，
        后者本来就无话可说。

        刻意写短（2026-09-15 精简）：`较 09-14：🆕 甲、乙 等 6 个｜✏️ 丙｜🧹 清理 3`
        —— 日期只留月-日、段间用竖线、最多列 3 个名字。每天一条的推送，
        长文案只会让人不看。
        """
        if self.首次 or not self.有变化:
            return ""
        段: list[str] = []

        def 列(图标: str, 名们: tuple[str, ...]) -> str:
            头 = "、".join(展示名(名) for 名 in 名们[:最大列名数])   # 与图上同一套名字规范
            多 = f" 等 {len(名们)} 个" if len(名们) > 最大列名数 else ""
            return f"{图标} {头}{多}"

        if self.新增:
            段.append(列("🆕", self.新增))
        if self.改动:
            段.append(列("✏️", self.改动))
        if self.过期清理:
            段.append(f"🧹 清理 {self.过期清理}")
        前缀 = f"较 {self.对比日期[5:]}" if self.对比日期 else "本次"
        return f"{前缀}：" + "｜".join(段)

    # ---------- 存取 ----------

    def 转存(self) -> dict:
        return {
            "日期": self.日期,
            "对比日期": self.对比日期,
            "新增": list(self.新增),
            "改动": list(self.改动),
            "过期清理": self.过期清理,
            "首次": self.首次,
        }

    @staticmethod
    def 自存(数据: dict) -> 数据变化 | None:
        """JSON → 数据变化；坏字段逐个退化（不因为一个计数坏掉就丢掉整天的日差）"""
        if not isinstance(数据, dict):
            return None

        def 名们(键: str) -> tuple[str, ...]:
            值 = 数据.get(键)
            return tuple(str(x) for x in 值) if isinstance(值, list) else ()

        try:
            计数 = int(数据.get("过期清理") or 0)
        except (TypeError, ValueError):
            logger.warning("记录里的过期清理不是数字，按 0 处理")
            计数 = 0
        return 数据变化(
            日期=str(数据.get("日期") or ""),
            对比日期=str(数据.get("对比日期") or ""),
            新增=名们("新增"),
            改动=名们("改动"),
            过期清理=计数,
            首次=bool(数据.get("首次")),
        )


def 默认路径(数据目录: Path | str) -> Path:
    return Path(数据目录) / 文件名


def _原子写(路径: Path, 体: str) -> None:
    """同目录临时文件 + `os.replace`：读到的永远是完整 JSON"""
    路径.parent.mkdir(parents=True, exist_ok=True)
    fd, 临时 = tempfile.mkstemp(dir=str(路径.parent), prefix=".变化-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(体)
            f.flush()
            os.fsync(f.fileno())
        os.replace(临时, 路径)
    finally:
        if os.path.exists(临时):
            os.unlink(临时)


def 读(路径: Path | str, 日期: str = "") -> 数据变化 | None:
    """读记录；`日期` 非空时只接受那一天的（坏文件/缺字段/日期不符都返回 None）。"""
    try:
        数据 = json.loads(Path(路径).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("数据变化记录解析失败（按没有处理）：%s", 路径)
        return None
    变化 = 数据变化.自存(数据)
    if 变化 is None:
        return None
    if 日期 and 变化.日期 != 日期:
        return None
    return 变化


def 记下并取(路径: Path | str, 差异: 合并差异, 今天: str) -> 数据变化:
    """把这次合并的差异记下来；**同一天已有记录就不再改写**。

    返回"今天的日差"（新的或当天早先记下的那份）。
    写盘失败只记日志：日差是锦上添花，绝不能因为它把出图/推送带崩。
    """
    已有 = 读(路径)
    if 已有 is not None and 已有.日期 == 今天:
        return 已有
    变化 = 数据变化(
        日期=今天,
        对比日期=已有.日期 if 已有 is not None else "",
        新增=tuple(差异.新增),
        改动=tuple(差异.改动),
        过期清理=差异.过期清理,
        首次=差异.首次,
    )
    try:
        _原子写(Path(路径), json.dumps(变化.转存(), ensure_ascii=False, indent=1))
    except OSError:
        logger.exception("数据变化记录写不进去（不影响出图）：%s", 路径)
    if 变化.文本():
        logger.info("数据日差 %s", 变化.文本())
    return 变化
