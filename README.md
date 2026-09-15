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
插件会把图推到 `push.targets` 里的会话——列表为空时，第一个发 `/甘特图` 的会话会被自动填进去
（零配置就能用上推送），之后就在设置页里增删：**想停掉某个群的推送，把那一项删掉即可**。
会话标识可以在目标群里发 `/甘特图状态` 查看。

平台：插件只用「发图片」和「主动发消息」两个平台无关能力，`metadata.yaml` 里据此声明了
`qq_official`（作者实例实测）与 `aiocqhttp`；其他适配器只要能发图片，用起来是一样的。

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

## 故障排查

**群里回「甘特图生成失败了」，日志里是 `ModuleNotFoundError: No module named 'matplotlib'`**

插件能加载、指令能回话，只是画不出图——**AstrBot 的解释器里没装本插件的依赖**。
原因：AstrBot 只在「从市场 / 仓库 URL 安装」「上传 zip 安装」「更新插件」「插件导入失败后修复、重载」时
才会自动跑插件的 `requirements.txt`；**普通的加载与重载都不跑**（`core/star/star_manager.py`）。

正常情况下你**不需要**动手：`main.py` 在导入期就 `import matplotlib`（先设好 `MPLCONFIGDIR`），
缺依赖时插件的导入会失败，AstrBot 收到这个信号后会自己执行 `requirements.txt`、装好再重试导入——
走的是你自己配置的 PyPI 镜像与 AstrBot 的核心依赖约束。若依赖装不上（比如网络不通），插件会在仪表盘
显示加载失败，点错误提示里的「尝试一键重载修复」即会先装依赖再加载；也可以手动装：

1. 在 AstrBot 插件页里用「从仓库安装 / 上传 zip」**重装一次**本插件——这条安装路径会顺带装依赖
   （若提示目录已存在，先删掉 `data/plugins/astrbot_plugin_ganttknights`；`data/plugin_data/` 里的数据不会被删）；
2. 或装进 **AstrBot 的解释器**（不是系统 Python）：

```powershell
& "<AstrBot 安装目录>\Scripts\python.exe" -m pip install -r "<插件目录>\requirements.txt"
```

装完重载插件（或重启 AstrBot）。

## 开发与测试

零依赖测试（不需要 AstrBot、不需要 matplotlib、不联网）：

```bash
pip install pytest apscheduler      # apscheduler 已在 requirements.txt 里；pytest 是开发用
pytest -q                           # tests/ 下六个文件：配置契约 / 元数据契约 / 入口契约 / 时间解析 / 数据日差 / 推送
```

`tests/` 钉住的是**契约**而不是业务：配置字段与 README 一致、越界值被夹取、
`metadata.yaml` 的必填字段/平台白名单/版本三处一致、入口的 `import matplotlib` 与 `MPLCONFIGDIR` 顺序、
公告年份按父活动时间窗推断、日差语义、推送目标与幂等记账。
需要真实 AstrBot 的端到端检查（模拟实例加载插件、真渲染、真抓取）不在仓库里，属于本地验证脚本。

## 许可与素材来源

- **代码**：[MIT](./LICENSE)，Copyright (c) 2026 Zrief。
- **游戏素材与数据**：明日方舟的图片、名称等版权属于上海鹰角网络科技有限公司及其关联公司；
  [PRTS Wiki](https://prts.wiki) 的页面内容遵循其站点声明。本项目仅用于**非商业**的信息展示，
  与鹰角网络、PRTS 均无隶属关系。
- **示例素材**：`背景图/` 里的两张图只是让插件开箱可用，**不在 MIT 覆盖范围内**；
  若要再分发或用于其他场合，请自行替换成你有权使用的图片。
- **致谢**：指令元数据与配置夹取的做法参考了 [astrbot_plugin_ark_calendar](https://github.com/zhewang448/astrbot_plugin_ark_calendar)（罗德岛行动终端）；
  插件骨架与"配置即契约"的测试思路参考了 AstrBot 插件 `astrbot_plugin_palette`。感谢 AstrBot 与各插件的作者。

<!-- 配置项:开始 -->

## 配置项

在 AstrBot 的插件配置页里改；下表与 `_conf_schema.json` 一一对应（`tests/test_配置契约.py` 会核对两边一致）。

### render · 出图

影响画面的参数。数值范围由后端强制夹取；这里的 minimum/maximum 只是文档，表单不读它们。改动任何一项，下一次出图就按新值渲染。

| 键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `render.title` | string | 近期活动一览 | 图片主标题 |
| `render.left_offset_days` | int | 3（0~30） | 时间窗左侧回溯天数（图上显示今天之前多少天的活动（0 表示只看今天起）。） |
| `render.right_offset_days` | int | 22（7~30） | 时间窗右侧前瞻天数（图上显示今天之后多少天；实际右边界会对齐到当周周日。上限 30：再长时一条活动的色条会被压得很窄，名字与日期刻度的摆放判定开始贴边（实测 35 天余量已到 0~4px）。） |
| `render.remind_days` | int | 3（1~30） | 过期提醒天数（提醒文案里提前多少天提醒即将结束的活动。） |
| `render.background_file` | string | （空） | 指定背景图文件（背景图目录内的文件名（如 沉沦者.WEBP），也可写绝对路径。留空则每天按日期自动取一张（同一天固定是同一张，换天才换）——同一天里群里看到的图长得一样，不会因为谁先谁后而换配色。） |
| `render.background_dir` | string | （空） | 背景图目录（留空 = 插件自带的 背景图/ 目录（两张示例图）。换成自己的图建议放到 data/plugin_data/astrbot_plugin_ganttknights/ 下再指过来——插件升级不会覆盖那里。） |

### panels · 底栏面板

控制底栏三个上新区是否出现在图里。关掉的区不会画，提醒文案里也不会再提它。

| 键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `panels.voucher` | bool | 开 | 展示「凭证兑换」面板 |
| `panels.outfit` | bool | 开 | 展示「新增时装」面板 |
| `panels.module` | bool | 开 | 展示「新增模组」面板 |

### data · 数据源

数据来自 PRTS Wiki，需要网络。请求条数与「进行中」判定的小时宽限是内部旋钮，不在这里暴露（内核默认 50 条 / 4 小时，可用 GK_API_LIMIT / GK_FUTURE_BUFFER_HOURS 覆盖）。

| 键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `data.auto_refresh_daily` | bool | 开 | 每天首次出图时自动更新数据（关闭后只出图不爬取，数据靠自己跑 python cli.py --force 更新。） |

### push · 每日推送

开启后，每天在指定时刻把甘特图推送到下面的目标会话列表。

| 键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `push.enabled` | bool | 关 | 开启每日推送（开启前要有推送目标（见下一项）。一份图只渲染一次，然后发给列表里的每个会话。） |
| `push.time` | string | 08:00 | 每日推送时刻（HH:MM，24 小时制）（按运行 AstrBot 那台机器的本地时间。别设在 00:00~04:00：游戏数据在北京时间 04:00 日切，那段时间出图可能还是前一天的数据。格式不对或越界会退回 08:00。） |
| `push.targets` | list | （空） | 推送目标会话列表（列表为空时，第一个发 /甘特图 的会话会自动被加进来（省去手动填）；之后由你在这里增删——**想停掉某个群的推送，把它从这一项里删掉即可**。会话标识可在目标群发 /甘特图状态 查看。） |

<!-- 配置项:结束 -->
