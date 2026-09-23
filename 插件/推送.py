"""每日推送 —— 定时、目标会话（配置项）、幂等记账（阶段五）。

## 第一性原理下的取舍（为什么这么小）

目标只有一句：**每天把那张图发到用户常待的会话里**。据此砍掉了下面这些"看起来专业"的东西：

| 没做的 | 为什么 |
|---|---|
| **不自己记住会话**（阶段六改成配置项） | 起初的写法是"谁发过 `/方舟日程` 就记住谁"（`event.unified_msg_origin`）。但用户要**能在设置页里删掉某个群的推送**，于是目标会话搬进配置项 `push.targets`：在要推送的会话里发 `/订阅甘特图` 加入（群聊/私聊都可以，多个会话各订各的）、`/退订甘特图` 移出，也能在设置页增删（「每日推送」） |
| **不做预热任务** | 渲染 1.2s。"提前 10 分钟渲染好"只是把同一件事挪个时间，却要多一个 job、一段配置和一份状态 |
| **不做退避重试** | 数据文件的 mtime 天然就是重试判据（当天任何触发都会重抓一次）；投递失败记进状态、在 `/甘特图状态` 里可见即可 |
| **不做平台能力预检** | `meta().support_proactive_message` 是 4.28 才有的字段且**默认 True**（信不过）。真要知道能不能推，发一次并把结果记下来比读字段更可靠 |
| **不做多会话限流/错峰** | 目标通常是 1~2 个会话；顺序 await 本身就够 |
| **不做 SQLAlchemyJobStore** | 停机错过的每日推送就该**静默跳过**（宁可不推，也不在重启后补推一张过期图）。`MemoryJobStore` 正好是这个语义 |
| **不加 `__del__`** | `star_manager.py` 是 `if __del__ … elif terminate`——加了 `__del__` 会让 `terminate()` 永不执行，热重载后变成双实例双推送（「宿主硬事实」） |

## 必须做对的三件事

1. **幂等**：热重载/重启后可能出现两个实例，靠磁盘上的"已推记账"（`{umo: 日期}`）兜住，
   **只在投递成功后记账**。状态文件与数据（CSV / 日差）同在 `data/plugin_data/<插件名>/`，
   `fsync` + `os.replace` 原子写。
2. **投递在渲染锁之外**：渲染由 `渲染服务` 的单飞锁串行化，投递是网络 I/O——不能占着锁发消息。
   这里只用一把**推送自己的**锁，保证同一次推送不会并发跑两遍。
3. **调度器的生命周期**：`AsyncIOScheduler` 在 3.11.x 必须在事件循环里 `start()`（内部走
   `asyncio.get_running_loop()`）→ 只能放 `initialize()`；`start()` 不幂等；
   `shutdown()` 是 `call_soon_threadsafe` 投递，之后要让循环转一圈（`await asyncio.sleep(0)`）；
   `misfire_grace_time` 库默认只有 **1 秒**，必须显式写。

本模块**不 import astrbot、不 import apscheduler、不 import matplotlib**：
发送动作由入口层注入（`发送(umo, 文本, 图片路径) -> bool`），调度器在 `确保任务()` 里按需导入。
于是状态与调度判据都是纯 Python，可以在没装 AstrBot 的机器上直接测（`tmp/检查推送.py`）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .配置 import 运行配置

if TYPE_CHECKING:               # 只给注解用：运行时不建立到渲染模块的依赖
    from .渲染 import 渲染服务

logger = logging.getLogger("ganttknights")

# ---------- 推送目标的增删（纯函数：不碰配置、也不碰宿主的保存接口）----------


def 加进目标(目标们: tuple[str, ...], 会话: str) -> tuple[str, ...]:
    """订阅：把一个会话追加到推送目标末尾。

    幂等：已经在列表里就原样返回——调用方据此区分"订阅成功"与"重复订阅"，
    不必自己再去查一遍（去重按字符串完全相等比较，`unified_msg_origin` 就是会话的唯一标识）。
    """
    return 目标们 if 会话 in 目标们 else (*目标们, 会话)


def 移出目标(目标们: tuple[str, ...], 会话: str) -> tuple[str, ...]:
    """退订：从推送目标里去掉一个会话（不在列表里则原样返回）。"""
    return tuple(项 for 项 in 目标们 if 项 != 会话)

任务ID = "ganttknights_daily_push"
"""稳定的 job id：同一插件只会有一个每日推送任务（`replace_existing=True`）。"""

宽限秒 = 600
"""`misfire_grace_time`：机器人正忙/刚重启时，迟到 10 分钟内仍然补推一次。

⚠️ APScheduler 3.11.3 的库默认值只有 **1 秒**——不显式写就等于"迟到 1 秒静默丢弃"。
"""



def _原子写(路径: Path, 体: str) -> None:
    """同目录临时文件 + `fsync` + `os.replace`：读到的永远是完整 JSON"""
    路径.parent.mkdir(parents=True, exist_ok=True)
    fd, 临时 = tempfile.mkstemp(dir=str(路径.parent), prefix=".push-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(体)
            f.flush()
            os.fsync(f.fileno())
        os.replace(临时, 路径)
    finally:
        if os.path.exists(临时):
            os.unlink(临时)


class 推送状态:
    """`<数据目录>/推送状态.json`：当日已推记账 + 上次结果。

**推送目标不在这里**：它是配置项 `push.targets`（`list` 型），这样用户能在 AstrBot 设置页里
直接增删——"想停掉某个群的推送就把它删掉"。这里只留"今天推过谁"的记账。

    ```json
    {
      "已推": {"aiocqhttp:GroupMessage:200000": "2026-09-14"},
      "上次": {"时刻": "2026-09-14T08:00:03", "成功": 2, "失败": 0, "说明": ""}
    }
    ```

    为什么用文件而不是 AstrBot 的 KV 存储：数据目录已经是"用户数据与代码分离"的落点
    （`data/plugin_data/<插件名>/`），多一个 JSON 不引入新依赖，也便于人工查看/删除。
    """

    def __init__(self, 路径: Path) -> None:
        self.路径 = Path(路径)

    # ---------- 读写 ----------

    def 读(self) -> dict:
        try:
            数据 = json.loads(self.路径.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception("推送状态解析失败，按空状态处理：%s", self.路径)
            return {}
        return 数据 if isinstance(数据, dict) else {}

    def _写(self, 数据: dict) -> None:
        try:
            _原子写(self.路径, json.dumps(数据, ensure_ascii=False, indent=2, sort_keys=True))
        except OSError:
            logger.exception("推送状态写不进去（不影响本次推送）：%s", self.路径)

    # ---------- 幂等记账 ----------

    def 该推吗(self, unified_msg_origin: str, 今天: str) -> bool:
        """今天这个会话还没推成功过 → 该推。"""
        已推 = self.读().get("已推")
        已推 = 已推 if isinstance(已推, dict) else {}
        return 已推.get(unified_msg_origin) != 今天

    def 记成功(self, unified_msg_origin: str, 今天: str, 目标们: tuple[str, ...] = ()) -> None:
        数据 = self.读()
        已推 = 数据.get("已推")
        已推 = dict(已推) if isinstance(已推, dict) else {}
        已推[unified_msg_origin] = 今天
        # 顺手把已经从"推送目标"里删掉的记账清掉，免得文件里留一堆旧会话
        if 目标们:
            已推 = {k: v for k, v in 已推.items() if k in set(目标们)}
        数据["已推"] = 已推
        self._写(数据)

    def 记失败(self, 说明: str) -> None:
        数据 = self.读()
        self._写({**数据, "上次": {"时刻": _现在(), "成功": 0, "失败": 1, "说明": 说明}})

    def 记结果(self, 成功: int, 失败: int, 说明: str = "") -> None:
        数据 = self.读()
        self._写({**数据, "上次": {"时刻": _现在(), "成功": 成功, "失败": 失败, "说明": 说明}})

    def 上次(self) -> dict:
        上次 = self.读().get("上次")
        return 上次 if isinstance(上次, dict) else {}

    def 今天推过吗(self, 今天: str, 目标们: tuple[str, ...] = ()) -> bool:
        """所有目标会话今天都推过了吗（给 `/甘特图状态` 用）"""
        return bool(目标们) and all(not self.该推吗(s, 今天) for s in 目标们)


def _现在() -> str:
    return datetime.now().isoformat(timespec="seconds")


class 推送服务:
    """把"每天推一次图"接到 APScheduler 上；发送动作由入口层注入。"""

    def __init__(
        self,
        渲染: 渲染服务,
        状态: 推送状态,
        发送: Callable[[str, str, str], Awaitable[bool]],
        配置读取: Callable[[], 运行配置] | None = None,
    ) -> None:
        self.渲染 = 渲染
        self.状态 = 状态
        self.发送 = 发送              # async (umo, 文本, 图片路径) -> bool
        # 定时任务触发时**现读**配置：用户在 WebUI 改了时刻/开关，下一次指令后就会重新武装
        self.配置读取 = 配置读取 or 运行配置
        self._调度器 = None
        self._任务锁 = asyncio.Lock()
        self._上次武装: tuple | None = None

    # ==================== 调度器生命周期 ====================

    def 确保任务(self, 运行配置: 运行配置) -> str:
        """按配置与"有没有会话"决定要不要武装定时任务；返回一句话状态（给日志/状态页）。

        幂等且便宜（一次字符串比较），所以入口层可以在 `initialize()` 与**每次指令**后都调一次
        ——这样 WebUI 里改开关/改时刻不用重启插件就能生效。
        """
        会话数 = len(运行配置.推送目标)
        时, 分 = 运行配置.推送时点()
        该武装 = 运行配置.推送开关 and 会话数 > 0
        # 指纹必须带上"开关本身"：否则"关掉了"与"开着但还没会话"都是 (False, …)，
        # 第二次调用会走早退分支、返回一句与实际不符的状态（探针抓到过）
        指纹 = (运行配置.推送开关, 该武装, 时, 分, 会话数)

        if 指纹 == self._上次武装:
            return self.一句话(运行配置)
        self._上次武装 = 指纹

        if not 该武装:
            self._关()
            if not 运行配置.推送开关:
                return "推送：未开启"
            return ("推送：已开启，但推送目标列表还是空的"
                    "（在要推送的会话里发一次 /订阅甘特图，也可以到插件设置里填）")

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception:
            logger.exception("装不上 APScheduler（AstrBot 自带 apscheduler>=3.11，出现这条说明环境异常）")
            return "推送：调度器不可用（见日志）"

        self._关()
        # 时区跟随进程本地（APScheduler 默认 get_localzone()），与内核的 naive datetime.now() 一致
        调度器 = AsyncIOScheduler()
        调度器.add_job(
            self._任务,
            CronTrigger(hour=时, minute=分),
            id=任务ID,
            replace_existing=True,
            coalesce=True,          # 错过多次只补一次
            max_instances=1,        # 同一任务不并发
            misfire_grace_time=宽限秒,
        )
        # ⚠️ 3.11.x 起必须在事件循环里 start()：内部会 asyncio.get_running_loop()
        调度器.start()
        self._调度器 = 调度器
        logger.info("每日推送已武装：%02d:%02d，目标 %d 个会话", 时, 分, 会话数)
        return self.一句话(运行配置)

    def _关(self) -> None:
        """同步关停（`shutdown()` 只是投递，真正的收尾在事件循环转一圈时发生）"""
        调度器, self._调度器 = self._调度器, None
        if 调度器 is not None:
            try:
                if 调度器.running:
                    调度器.shutdown(wait=False)
            except Exception:
                logger.exception("关停推送调度器失败")

    async def 停(self) -> None:
        """`terminate()` 里调：关停并给事件循环一次转动的机会。

        `AsyncIOExecutor` 会 cancel 未完成的协程任务，所以 `_任务` 容忍 `CancelledError`。
        """
        self._关()
        self._上次武装 = None
        await asyncio.sleep(0)

    def 一句话(self, 运行配置: 运行配置) -> str:
        """状态页/日志用的一行摘要"""
        if not 运行配置.推送开关:
            return "推送：未开启"
        if self._调度器 is None:
            return (f"推送：已开启（{运行配置.推送时刻}），但推送目标列表是空的"
                    "（用 /订阅甘特图 订阅本会话）")
        下次 = getattr(self._调度器.get_job(任务ID), "next_run_time", None)
        下次文本 = 下次.strftime("%m-%d %H:%M") if 下次 else "未排定"
        return f"推送：每天 {运行配置.推送时刻}，下次 {下次文本}"

    # ==================== 任务体 ====================

    async def _任务(self) -> None:
        """APScheduler 调用的入口（在事件循环里）"""
        try:
            await self.推一次(运行配置=self.配置读取())
        except asyncio.CancelledError:
            logger.info("每日推送任务被取消（插件卸载/重载）")
            raise
        except Exception:
            logger.exception("每日推送失败")

    async def 推一次(self, *, 运行配置: 运行配置) -> str:
        """渲染一次 → 投递给每个"今天还没推成功"的会话 → 记账。返回一句话结果。

        幂等靠磁盘上的记账：热重载后即便有两个实例，第二个也会在这里看到"今天已推过"。
        """
        async with self._任务锁:
            目标们 = 运行配置.推送目标
            if not 目标们:
                self.状态.记失败("没有配置推送目标")
                return ("还没有配置推送目标"
                        "（用 /订阅甘特图 订阅本会话，或在插件设置 → 每日推送 → 推送目标会话列表里填）")
            今天 = datetime.now().date().isoformat()
            待推 = [s for s in 目标们 if self.状态.该推吗(s, 今天)]
            if not 待推:
                return f"{今天} 已经推过了，跳过"

            结果 = await self.渲染.出图(
                现在时间=datetime.now(), 运行配置=运行配置, 自动更新=运行配置.每日自动更新
            )
            图片 = Path(结果.图片路径)
            if not self.渲染.产物可用(图片):
                self.状态.记失败("出图失败")
                return "出图失败，已记入推送状态（详见日志）"

            # 渲染只做一次，投递循环在渲染锁之外
            文本 = self._文案(结果)
            成功, 失败 = 0, []
            for umo in 待推:
                try:
                    if await self.发送(umo, 文本, str(图片)):
                        self.状态.记成功(umo, 今天, 目标们)
                        成功 += 1
                    else:
                        失败.append(umo)
                except Exception:
                    logger.exception("投递失败：%s", umo)
                    失败.append(umo)
            说明 = "" if not 失败 else f"投递失败 {len(失败)} 个会话"
            self.状态.记结果(成功, len(失败), 说明)
            logger.info("每日推送：成功 %d / 失败 %d", 成功, len(失败))
            return f"推送完成：成功 {成功}，失败 {len(失败)}"

    @staticmethod
    def _文案(结果) -> str:
        """推送附带的文字：**只有节点提醒**，没有就一句都不发（只发图）。

        - 不再带日差（"今天和昨天比变了什么"）——2026-09-15 定：只在关键节点说话；
        - `渲染结果.有提醒` 为假时直接丢掉那句回落文案，否则每天固定发一句废话（docs「两次自我推翻」）。
        """
        return 结果.提醒 if getattr(结果, "有提醒", False) else ""
