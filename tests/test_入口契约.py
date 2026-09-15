"""入口契约：`main.py` 的两行"功能性导入" + `requirements.txt` 的清单。

这两件事现在**没有代码兜底**（2026-09-15 把自建的依赖关卡删掉，改成生态的约定俗成做法，见
docs/插件化路线.md §19）：`main.py` 导入期 `import matplotlib`，缺依赖时宿主才会替我们跑
`requirements.txt` 并重试导入。删掉它不会有任何报错，只会让"缺依赖"重新变成用户要自己处理的故障，
所以用测试钉住——顺便钉住 `MPLCONFIGDIR` 必须**先于**它被设置（§5.5 的顺序约束）。

零依赖：只读文件、只 parse 源码，不 import astrbot / matplotlib。
"""

from __future__ import annotations

import ast
from pathlib import Path

仓库根 = Path(__file__).resolve().parent.parent
源码 = (仓库根 / "main.py").read_text(encoding="utf-8")


def _顶层导入() -> set[str]:
    树 = ast.parse(源码)
    顶层: set[str] = set()
    for 子 in 树.body:
        if isinstance(子, ast.Import):
            顶层 |= {名.name.split(".")[0] for 名 in 子.names}
        elif isinstance(子, ast.ImportFrom) and 子.module:
            顶层.add(子.module.split(".")[0])
    return 顶层


def test_导入期_import_matplotlib():
    """缺依赖时唯一能让宿主替我们装依赖的信号，就是"插件导入失败"（§19.2）。"""
    assert "matplotlib" in _顶层导入(), (
        "main.py 导入期的 import matplotlib 没了：缺依赖时插件会照常加载，"
        "宿主收不到任何信号，用户只能到第一次出图才看到失败（docs/插件化路线.md §19）"
    )


def test_mplconfig_先于_matplotlib_导入():
    """`MPLCONFIGDIR` 只在 matplotlib 首次导入时被读取（§5.5）：顺序反了就等于没设。"""
    文本 = 源码.splitlines()
    设 = next((i for i, 行 in enumerate(文本) if "MPLCONFIGDIR" in 行 and "environ" in 行), None)
    导 = next((i for i, 行 in enumerate(文本) if 行.startswith("import matplotlib")), None)
    assert 设 is not None, "找不到设置 MPLCONFIGDIR 的那一行"
    assert 导 is not None, "找不到 import matplotlib 那一行"
    assert 设 < 导, f"MPLCONFIGDIR 必须在 import matplotlib 之前设置（现在是 L{设 + 1} vs L{导 + 1}）"


def test_requirements_写上了宿主不带的两个():
    """AstrBot 自带 httpx / pillow / apscheduler，**不带 numpy / matplotlib**（§19.4）。

    少写这两个 → 用户机器上永远不会装它们；多写宿主的库 → 没必要（也不碍事）。
    """
    裸依赖 = {
        行.split("#")[0].strip().split("==")[0].split(">=")[0].strip().lower()
        for 行 in (仓库根 / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if 行.split("#")[0].strip()
    }
    assert {"matplotlib", "numpy"} <= 裸依赖, f"requirements.txt 缺东西：{sorted(裸依赖)}"
