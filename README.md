# GanttKnights
针对游戏明日方舟特化的甘特图绘图工具，基于matplotlib | A Gantt chart plotting tool specialized for the mobile game "Arknights", developed using matplotlib.

效果展示
![效果展示](./Gantt.jpg)

## 使用

```bash
uv sync          # 或 pip install httpx matplotlib Pillow numpy

python cli.py                        # 生成 Gantt.jpg（数据每天只爬一次）
python cli.py --force                # 强制重新爬取
python cli.py --bootstrap --force    # 数据初次建立：回溯已结束活动的公告，补录剿灭/保全等长期任务
python prts_scraper.py               # 只爬取活动数据并在控制台打印
```

## AstrBot 插件

`main.py` 是 AstrBot 插件入口（聊天指令出图），`cli.py` 是命令行入口，两者共用 `src/流水线.py` 这一条渲染内核。

把仓库放进 `data/plugins/astrbot_plugin_ganttknights/`（目录名须与 `metadata.yaml` 的 `name` 一致），
依赖由 AstrBot 按 `requirements.txt` 安装，然后在群里发 `/甘特图`。

| 指令 | 说明 |
|---|---|
| `/甘特图`（别名 `/方舟甘特`、`/舟甘特`） | 出图；每次按当前数据渲染 |
| `/甘特图状态` | 数据更新时间、最近一次数据变化、每日推送情况、本会话标识 |
| `/甘特图刷新`（管理员） | 强制重新抓取并重画 |
| `/甘特图初始化`（管理员） | 初始化：扫**所有**活动的公告（含剿灭轮换、复刻排期），从零重建数据；全新安装时会自动做一次 |
| `/甘特图帮助` | 指令列表 |

**每日推送**：在插件配置里打开 `push.enabled` 并设好 `push.time`（默认 08:00），
插件会把图推到「用过 `/甘特图` 的会话」——先在目标群里发一次指令，它就记住了，不需要填群号或会话 ID。

抓取策略：**初始化一次拿全量，之后每天只扫"进行中 + 近 30 天结束过"的活动**，
把新出现的加进来、过期的删掉；数据来自 [PRTS Wiki](https://prts.wiki)（SMW ask 查活动时间、
卡池一览与活动公告的 wikitext 解析卡池和子活动），需要网络。

## 版面

一张图从上到下三段，全部按像素排布（`src/绘图_排版.py`，dpi150 下 1 数据单位 = 1 像素）：

- **页眉**：大字粗体标题（无衬线） + 右侧"数据来源 / 更新时间"块；
- **甘特图**：固定宽左信息列（类型色条 + 关键词）+ 顶部日期轴带 + 每日竖网格 + TODAY 柱带；
  事件名优先写在条上，条太短时用细箭头引到条外；
- **底栏**：凭证兑换 / 新增时装 / 新增模组 三区卡片（圆角头像 + 干员名 + 模组名），
  行数与格宽由试排搜索决定：行数最少 → 填得最满 → 格宽最接近理想值。

配色不写死：整套色值由**当天选中的那张背景图**推导（`src/绘图_主题.py`），推导规则见 [配色规范.md](./docs/配色规范.md)。

可选素材：`背景图/` 放任意背景图（**每天按日期固定取一张**，也可以在配置里指定某一张；整套色系由它推导）；字体 `字体/NotoSansCJKsc-Regular.otf` 等静态字重不在仓库里——**缺失时会按平台回退到系统中文字体**（Windows 微软雅黑 / macOS 苹方 / Linux Noto CJK），若你按 AstrBot 的约定把 ttf 命名为 `font.ttf` 放进 `data/` 目录，那支字体会被优先使用。

## 许可与素材来源

- **代码**：[MIT](./LICENSE)，Copyright (c) 2026 Zrief。
- **游戏素材与数据**：明日方舟的图片、名称等版权属于上海鹰角网络科技有限公司及其关联公司；
  [PRTS Wiki](https://prts.wiki) 的页面内容遵循其站点声明。本项目仅用于**非商业**的信息展示，
  与鹰角网络、PRTS 均无隶属关系。
- **示例素材**：`背景图/` 里的两张图只是让插件开箱可用，**不在 MIT 覆盖范围内**；
  若要再分发或用于其他场合，请自行替换成你有权使用的图片。
- **致谢**：指令元数据与配置夹取的做法参考了 [astrbot_plugin_ark_calendar](https://github.com/zhewang448/astrbot_plugin_ark_calendar)（罗德岛行动终端）；
  插件骨架与"配置即契约"的测试思路参考了 AstrBot 插件 `astrbot_plugin_palette`。感谢 AstrBot 与各插件的作者。
