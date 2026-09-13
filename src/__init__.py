"""GanttKnights 渲染内核。

本包**不认识 AstrBot**：不 import astrbot、不读插件配置。
CLI（cli.py）与插件适配层都把这里当作普通库调用。

全部内部导入使用相对导入（`from .config import ...`），
因此本包可以被 importlib 以任意包名加载（例如作为 AstrBot 插件的一部分）。
"""
