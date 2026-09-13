"""渲染缓存 —— 按「业务签名」复用已渲染好的图（docs/插件化路线.md §7）。

## 签名 = 业务语义 + 影响画面的东西，剔除「元信息」

```text
签名 = sha256(json({"版本", "日期", "显示配置", "数据", "图标", "背景", "字体"}, sort_keys))
```

| 组成 | 为什么进签名 |
|---|---|
| **版本**（`签名版本`） | 排版内核改了（像素会变）就 +1；否则新代码可能命中老图 |
| **日期** | 时间窗、TODAY 柱带、页眉都按天走；与"次日 00:00 失效"双保险 |
| **显示配置** | 标题 / 左右时间窗 / 提醒天数 / 底栏面板组合——任一变化即失效 |
| **数据内容哈希** | `所有活动数据.csv` 与 `新增预告.json` 的 **sha256 前 16 位**：数据没变但重爬了一次（mtime 变了）**不**击穿缓存；内容真变了必然重画 |
| **图标指纹** | `图片缓存/` 的 (文件名, 大小)：缺头像→补下载后画面会变 |
| **背景** | **实际选中的那张**背景图的 (路径, 大小, mtime_ns)：整套配色由它推导 |
| **字体** | 插件 `字体/` 目录的 (文件名, 大小) + `settings.额外字体` 每个文件的 (路径, 大小, mtime_ns) |

两条刻意的「剔除」：

1. **背景三件套（随机 / 指定文件 / 目录）不进签名**。它们只是"选出哪张图"的规则，
   真正决定画面的是**选出来的那张图**。因此：`指定背景="a.webp"` 与"随机恰好抽到 a.webp"
   得到同一个签名（画面确实一样）；往背景目录里**新增**一张图也不会让已有缓存失效。
   代价是"随机背景"开着时，同一天里重复出图会**逐渐**命中各张背景各自的缓存
   （详见 `插件/渲染.py` 的说明）。
2. **不哈希 CSV 里随时间变化的列**。整天只抓一次数据的流程下，同一天内文件内容不会自己变；
   用户手动 `--force` 重爬会改内容 → 重画一张，这正是想要的行为。

## 配套三件套（参考物 `core/render_cache.py`）

1. **成品校验后才入缓存**：读文件头 8 字节判 JPEG / PNG 魔数，截断/空的产物既不入缓存也不发出去；
2. **tmp + `os.replace()` 原子写**：manifest 与图片都是"先写临时文件再替换"，不存在半个文件；
3. **跨自然日强制失效**：`失效时刻 = 次日 00:00`（日程图语义；比"缓存 N 小时"更符合直觉）。

单进程假设：插件侧渲染由 `渲染服务` 的 `asyncio.Lock` 串行化，manifest 的读改写不并发；
CLI 不读这张缓存（调试时就是要看真实渲染）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from ..src.config import Settings

logger = logging.getLogger("ganttknights")

签名版本 = 1
"""排版内核的像素契约版本：改了会改变出图的代码就 +1（否则可能命中老缓存）。"""

保留个数 = 8
"""缓存里最多留几张图（超出丢最旧的）。一天正常只会用到 1~2 张（随机背景各一张）。"""

_PNG魔数 = b"\x89PNG\r\n\x1a\n"
_JPEG魔数 = b"\xff\xd8\xff"
_魔数长度 = 8


def _文件哈希(路径: Path) -> str:
    """内容 sha256 前 16 位；不存在返回 "缺"（"缺"与"空文件"必须能区分开）"""
    try:
        return hashlib.sha256(路径.read_bytes()).hexdigest()[:16]
    except FileNotFoundError:
        return "缺"
    except OSError:
        return "读不到"


def _文件指纹(路径: Path) -> list:
    """[大小, mtime_ns]；读不到时给 [-1, -1]（负值不会与真实文件撞上）"""
    try:
        st = 路径.stat()
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return [-1, -1]


def _目录指纹(目录: Path) -> list:
    """目录下文件的 (名字, 大小) 列表，按名字排序；目录不存在返回空表。

    只取大小不取 mtime：图标/字体是"内容决定画面"的只读素材，
    重新下载或 `git checkout` 改的是 mtime，不该让缓存白失效。
    """
    try:
        return sorted([f.name, f.stat().st_size] for f in 目录.iterdir() if f.is_file())
    except OSError:
        return []


def 图是完整的(路径: Path | str) -> bool:
    """只读文件头 8 字节判魔数：截断/空的产物不算成品，不入缓存、也不发给用户。

    > 这是**便宜的**校验（参考物 `core/render_cache.py` 同样只看文件头），上限也在这里：
    > 一个"8 字节 JPEG 头 + 后面被截断"的文件仍会被放行。要更严就得整图解码，
    > 代价是每次发图前多花几十毫秒——不划算：真出问题的是"完全没画出来"和"空文件"。
    """
    try:
        with Path(路径).open("rb") as f:
            头 = f.read(_魔数长度)
    except OSError:
        return False
    return 头.startswith(_JPEG魔数) or 头.startswith(_PNG魔数)


def _次日零点(现在时间: datetime) -> datetime:
    return datetime.combine(现在时间.date() + timedelta(days=1), time.min)


@dataclass(frozen=True)
class 缓存条目:
    """manifest 里的一条：图片位置 + 失效时刻 + 可播报的概要（命中时还原成渲染结果）。"""

    签名: str
    图片: str
    生成时刻: str        # ISO
    失效时刻: str        # ISO
    概况: str
    警告: str
    标题: str
    条目数: int
    名称数: int
    分区计数: dict[str, int]

    @staticmethod
    def 从渲染结果(签名: str, 图片: Path, 结果, 现在时间: datetime) -> 缓存条目:
        return 缓存条目(
            签名=签名,
            图片=str(图片),
            生成时刻=现在时间.isoformat(timespec="seconds"),
            失效时刻=_次日零点(现在时间).isoformat(timespec="seconds"),
            概况=结果.概况,
            警告=结果.警告,
            标题=结果.标题,
            条目数=结果.条目数,
            名称数=结果.名称数,
            分区计数=dict(结果.分区计数),
        )

    def 过期(self, 现在时间: datetime) -> bool:
        try:
            return 现在时间 >= datetime.fromisoformat(self.失效时刻)
        except ValueError:
            return True     # 时间戳坏了就当过期：宁可重画，不发旧图


class 渲染缓存:
    """`数据目录/渲染缓存/` 下的图片 + manifest；每次读盘，不在内存里留状态。"""

    def __init__(self, 数据目录: Path, 保留数: int = 保留个数) -> None:
        self.目录 = Path(数据目录) / "渲染缓存"
        self.保留数 = 保留数

    # ==================== 签名 ====================

    @property
    def manifest路径(self) -> Path:
        return self.目录 / "manifest.json"

    def 算签名(self, 运行配置, 现在时间: datetime, 设置: Settings, 背景路径: str | Path) -> str:
        """按模块 docstring 的表算签名。只 stat + 读两个小文件，实测量级 1~3ms。

        `背景路径` 必须是**已经选定的那张图**（不是目录、不是"随机"这个规则）。
        """
        分区 = 运行配置.底栏分区()
        材料 = {
            "版本": 签名版本,
            "日期": 现在时间.date().isoformat(),
            "显示配置": {
                "标题": 运行配置.标题,
                "左边界天数": 运行配置.左边界天数,
                "右边界天数": 运行配置.右边界天数,
                "提醒天数": 运行配置.提醒天数,
                # 三个面板全开在内核里是 None（按默认路径走）；必须与"三个都关"区分开
                "面板": "全部" if 分区 is None else list(分区),
            },
            "数据": {
                "活动数据": _文件哈希(Path(设置.all_data_path)),
                "新增预告": _文件哈希(Path(设置.new_items_path)),
            },
            "图标": _目录指纹(Path(设置.icon_cache_dir)),
            "背景": [str(背景路径), *_文件指纹(Path(背景路径))],
            "字体": {
                "随包": _目录指纹(Path(设置.字体目录)),
                "额外": sorted(
                    ([角色, str(路径), *_文件指纹(Path(路径))]
                     for 角色, 路径 in (设置.额外字体 or {}).items()),
                    key=lambda 项: 项[0],
                ),
            },
        }
        return hashlib.sha256(
            json.dumps(材料, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def 图片路径(self, 签名: str) -> Path:
        return self.目录 / f"渲染_{签名[:16]}.jpg"

    # ==================== 查 / 存 ====================

    def 查(self, 签名: str, 现在时间: datetime) -> 缓存条目 | None:
        """命中要求：签名在 manifest 里、未过期、图片存在且魔数完整。"""
        条目 = self._读manifest().get(签名)
        if 条目 is None:
            return None
        if 条目.过期(现在时间):
            return None
        图片 = Path(条目.图片)
        if not 图是完整的(图片):
            logger.warning("缓存图片缺失或损坏，按未命中处理：%s", 图片)
            return None
        return 条目

    def 存入(self, 签名: str, 结果, 现在时间: datetime) -> 缓存条目 | None:
        """把成品登记进 manifest；魔数不完整就**不登记**（宁可不缓存，也不发坏图）。"""
        图片 = Path(结果.图片路径)
        if not 图是完整的(图片):
            logger.warning("产物不是完整图片，跳过入缓存：%s", 图片)
            return None
        条目 = 缓存条目.从渲染结果(签名, 图片, 结果, 现在时间)
        manifest = self._读manifest()
        manifest[签名] = 条目
        self._清理(manifest, 现在时间, 保护签名=签名)
        self._写manifest(manifest)
        logger.info("已入渲染缓存：%s（共 %d 条）", 图片.name, len(manifest))
        return 条目

    # ==================== manifest 读写 ====================

    def _读manifest(self) -> dict[str, 缓存条目]:
        try:
            data = json.loads(self.manifest路径.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception("manifest 解析失败，按空缓存处理：%s", self.manifest路径)
            return {}
        结果: dict[str, 缓存条目] = {}
        for 签名, 项 in (data.get("条目") or {}).items():
            try:
                结果[签名] = 缓存条目(**项)
            except TypeError:
                logger.warning("manifest 条目字段对不上，跳过：%s…", 签名[:12])
        return 结果

    def _写manifest(self, manifest: dict[str, 缓存条目]) -> None:
        """原子写：同目录临时文件 + `os.replace()`（跨进程读到的永远是完整 JSON）"""
        self.目录.mkdir(parents=True, exist_ok=True)
        体 = json.dumps(
            {"版本": 签名版本, "条目": {k: vars(v) for k, v in manifest.items()}},
            ensure_ascii=False, indent=2, sort_keys=True,
        )
        fd, 临时 = tempfile.mkstemp(dir=str(self.目录), prefix=".manifest-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(体)
                f.flush()
                os.fsync(f.fileno())
            os.replace(临时, self.manifest路径)
        finally:
            if os.path.exists(临时):
                os.unlink(临时)

    def _清理(self, manifest: dict[str, 缓存条目], 现在时间: datetime, 保护签名: str) -> None:
        """先删过期项，再按生成时间保留最新 N 条（正在存的那条永不被删）"""
        for 签名, 条目 in list(manifest.items()):
            if 签名 != 保护签名 and 条目.过期(现在时间):
                self._删条目(manifest, 签名)
        多余 = len(manifest) - self.保留数
        if 多余 > 0:
            for 签名, _ in sorted(manifest.items(), key=lambda kv: kv[1].生成时刻)[:多余]:
                if 签名 != 保护签名:
                    self._删条目(manifest, 签名)

    def _删条目(self, manifest: dict[str, 缓存条目], 签名: str) -> None:
        条目 = manifest.pop(签名, None)
        if 条目 is None:
            return
        try:
            Path(条目.图片).unlink(missing_ok=True)
        except OSError:
            logger.warning("缓存图片删不掉：%s", 条目.图片)
