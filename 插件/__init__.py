"""AstrBot 适配层 —— 只有这一层认识 AstrBot。

分层（单向依赖，见 docs/插件化.md「起点」）：

    main.py（Star 子类：指令 + 生命周期）
        ↓ 构造注入
    插件/（指令元数据 · 配置夹取 · 文案 · 渲染服务）
        ↓ 调用
    src/（渲染内核，纯 Python + matplotlib，**不认识 AstrBot**）

因此 `src/**` 里不允许出现 `import astrbot`：CLI（`cli.py`）永远可用，
内核也能脱离插件单测。反向也要守：本层的模块除了 `渲染服务` 之外不碰内核全局状态。
"""
