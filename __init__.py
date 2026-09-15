"""AstrBot 插件包标识（同时也是 CLI 的仓库根）。

本文件**故意只放 docstring**：AstrBot 会把插件目录当包导入，
`__init__.py` 里的任何导入都会在插件加载阶段同步执行（`astrbot/core/star/star_manager.py`
的 `__import__("data.plugins.<目录名>.main")`），而重依赖（matplotlib）必须留在
渲染线程里，见 docs/插件化.md「起点」。
"""
