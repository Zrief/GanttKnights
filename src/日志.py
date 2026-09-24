"""logger 的**唯一出处** —— 内核（`src/`）、插件层（`插件/`）、CLI 都从这里拿。

为什么需要这个文件
------------------
AstrBot 上架规范：插件的 logger 只能 `from astrbot.api import logger`，
禁用标准库 `logging.getLogger`。但本仓另有两条同样硬的约束：
内核不认识 AstrBot（`src/流水线.py` docstring）、裸机可直测（单测在无
AstrBot 的环境加载内核模块）、CLI 独立运行。所以在这里做一次分流——
**全仓只此一处** try-import，其余模块一律 `from .日志 import logger`。

两个后端，一张脸
----------------
- 有 AstrBot：转发给 `astrbot.api.logger`（loguru）。
- 裸机（CLI / 单测）：`_裸机` 极简实现，带时间戳与级别写 stderr。

⚠️ 调用点全部是 logging 的 `%s` 惰性格式，而 loguru 用 `{}` 风格、**不解释 `%s`**
（直接换后端会把 `%s` 原样打出来——main.py 两处旧调用就是这么坏的）。
所以出口统一先 `msg % args` 落实再转发，两个后端行为一致。

⚠️ 本文件是全仓**唯一**碰标准库 logging 的地方，且只用于压制第三方 httpx 的
噪音（AstrBot 把 root logger 开在 INFO，httpx 每个请求打两行 INFO，一次出图
几十个请求会淹掉宿主日志）——这不是插件自己的 logger，规范管的是后者。
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime

try:
    from astrbot.api import logger as _原始
except ImportError:                      # 裸机：CLI / 单测（无 AstrBot 环境）
    _原始 = None

if _原始 is not None:
    import logging
    logging.getLogger("httpx").setLevel(logging.WARNING)   # 见模块 docstring 的 ⚠️


def _格(msg, args) -> str:
    """logging 风格的 % 惰性格式在转发前落实（loguru 不解释 %s）"""
    if args:
        try:
            return str(msg) % args
        except Exception:                # 格式串与实参不匹配也不能炸掉业务
            return str(msg)
    return str(msg)


class _适配:
    """转发给 loguru 后端：`exc_info=True` 这类 logging 关键字在这里翻译成 exception()。"""

    def __init__(self, 后) -> None:
        self._后 = 后

    def debug(self, msg, *a, **k):
        self._后.debug(_格(msg, a))

    def info(self, msg, *a, **k):
        self._后.info(_格(msg, a))

    def warning(self, msg, *a, **k):
        if k.get("exc_info"):
            self._后.exception(_格(msg, a))
        else:
            self._后.warning(_格(msg, a))

    def error(self, msg, *a, **k):
        self._后.error(_格(msg, a))

    def exception(self, msg, *a, **k):
        self._后.exception(_格(msg, a))


class _裸机:
    """无 AstrBot 时的极简 logger。

    刻意不碰标准库 logging：上架规范字面禁止 logging.getLogger，全仓保持零出现
    （例外只有本文件 AstrBot 分支里压 httpx 的那一处）。裸机日志只给人看，print 足够；
    没有 stdlib handler 挂着，httpx 等依赖的 INFO 日志天然静默，原 `获取_prts` 的
    降噪在裸机分支因此不需要。
    """

    _级表 = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}

    def __init__(self) -> None:
        self._级别 = 1                   # 默认 INFO；`config.setup_logging` 可调

    def 设级别(self, 名: str) -> None:
        self._级别 = self._级表.get(str(名).upper(), 1)

    def _打(self, 级: int, 名: str, msg: str) -> None:
        if 级 >= self._级别:
            print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{名}] {msg}", file=sys.stderr)

    def debug(self, msg, *a, **k):
        self._打(0, "DEBUG", _格(msg, a))

    def info(self, msg, *a, **k):
        self._打(1, "INFO", _格(msg, a))

    def warning(self, msg, *a, **k):
        self._打(2, "WARN", _格(msg, a))
        if k.get("exc_info"):
            traceback.print_exc(file=sys.stderr)

    def error(self, msg, *a, **k):
        self._打(3, "ERROR", _格(msg, a))

    def exception(self, msg, *a, **k):
        self._打(3, "ERROR", _格(msg, a))
        traceback.print_exc(file=sys.stderr)


logger = _适配(_原始) if _原始 is not None else _裸机()
"""全仓唯一的 logger 实例。两个后端方法名一致（info/warning/error/debug/exception），
调用点用 `%s` 风格传参即可，格式化在出口统一落实。"""
