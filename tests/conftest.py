"""pytest 公共装置：把仓库挂成合成包 `gk`，好让插件/内核模块的相对导入成立。

插件在宿主里是被当成 `data.plugins.<目录名>` 导入的，模块内部写着 `from ..src...`。
测试里我们不给每个模块造完整包路径，而是造一个 `__path__ = [仓库根]` 的合成包 `gk`，
于是 `gk.插件.推送` / `gk.src.解析_公告` 都能正常导入，且 `..src` 也能解析。

设计约束（照 §6 的"零依赖"要求）：
- 不 import astrbot、不 import matplotlib、不联网；
- 只依赖标准库 + `pytest`（`插件/推送.py` 的调度器断言另外需要 `apscheduler`）。
"""

from __future__ import annotations

import importlib
import shutil
import sys
import types
import uuid
from pathlib import Path

import pytest

仓库根 = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _合成包() -> None:
    if "gk" not in sys.modules:
        包 = types.ModuleType("gk")
        包.__path__ = [str(仓库根)]
        sys.modules["gk"] = 包
    if str(仓库根) not in sys.path:
        sys.path.insert(0, str(仓库根))


@pytest.fixture
def tmp_path() -> Path:
    """覆盖 pytest 自带的 `tmp_path`：它在 Windows 上用 `tempfile.mkdtemp()`。

    `mkdtemp` 会按 mode=0o700 建目录并写一个"只给创建者 SID"的 DACL；
    在受限环境（本机沙箱 / 某些 CI）里进程的 SID 与之不符 → 之后连子目录都建不了
    （`PermissionError: [WinError 5]`）。用普通 mkdir 建在仓库 tmp/ 下就没这个问题。
    """
    目录 = 仓库根 / "tmp" / f"pytest_{uuid.uuid4().hex[:8]}"
    目录.mkdir(parents=True, exist_ok=True)
    try:
        yield 目录
    finally:
        shutil.rmtree(目录, ignore_errors=True)


@pytest.fixture(scope="session")
def 插件模块(_合成包):
    """按需导入插件侧的模块（导入期不碰 matplotlib）。"""
    def _取(名字: str):
        return importlib.import_module(f"gk.插件.{名字}")
    return _取


@pytest.fixture(scope="session")
def 内核模块(_合成包):
    def _取(名字: str):
        return importlib.import_module(f"gk.src.{名字}")
    return _取
