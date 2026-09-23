# GanttKnights

一张长图看清《明日方舟》近期的活动排期：活动与卡池时间轴、凭证兑换、新增时装、新增模组。

<!-- 图片必须用绝对 URL：AstrBot 插件页是把它当 HTML 渲染的，相对路径会相对 dashboard 地址解析 → 404。
     jsDelivr 镜像 GitHub 仓库（写 @main 即跟随主分支），在国内的可达性比 raw.githubusercontent 好。 -->
![效果展示](https://cdn.jsdelivr.net/gh/Zrief/GanttKnights@main/Gantt.jpg)

数据来自 [PRTS Wiki](https://prts.wiki)。既可以在 AstrBot 里当插件用（聊天指令 + 每日推送），
也可以当命令行工具用，两者共用同一套渲染内核。

## 安装

**命令行**（需要 Python 3.12）：

```bash
pip install httpx matplotlib Pillow numpy
python cli.py                        # 生成 数据/Gantt.jpg（数据每天只爬一次）
python cli.py --force                # 强制重新爬取
python cli.py --bootstrap --force    # 首次建立数据：回溯已结束活动的公告，补录剿灭轮换、复刻排期
```

> 产物落在 `数据/` 下（可写、不进 git）；仓库根那份 `Gantt.jpg` 只是上面那张展示图的快照，要更新就手动覆盖它。

**AstrBot 插件**：在插件市场里搜「明日方舟甘特图」安装（或把仓库放进 `data/plugins/astrbot_plugin_ganttknights/`，
目录名要与 `metadata.yaml` 的 `name` 一致）。依赖由插件自己声明，缺依赖时 AstrBot 会在加载插件时自动装好。
然后在群里发 `/方舟日程` 即可。

## 指令

| 指令 | 别名 | 谁可以用 | 说明 |
|---|---|---|---|
| `/方舟日程` | `/方舟甘特` | 所有人 | 出图；首次会自动抓取数据（十几秒），之后几秒 |
| `/订阅甘特图` | — | 所有人 | 把本会话加入每日推送（群聊、私聊都可以，可多个会话各订各的） |
| `/退订甘特图` | — | 所有人 | 把本会话移出每日推送 |
| `/甘特图状态` | — | 所有人 | 数据更新时间、最近一次数据变化、每日推送情况、本会话标识 |
| `/甘特图刷新` | `/甘特图更新` | 管理员 | 强制重新抓取并重画 |
| `/甘特图初始化` | — | 管理员 | 全量重建数据（全新安装时会自动做一次） |
| `/甘特图帮助` | — | 所有人 | 指令列表 |

## 每日推送

在插件配置页里打开 `push.enabled`、设好 `push.time`（默认 08:00），插件就会在每天那个时刻把当天的图
推到 `push.targets` 里的会话。

- 在要推送的会话里发一次 **`/订阅甘特图`** 就订好了，不用手填会话 ID；群聊、私聊都可以，多个会话各订各的；
- 不想收了就发 `/退订甘特图`，或到设置页里增删——**想停掉某个会话，把那一项删掉即可**；
- 推送分两条：先文字，再图片。**文字只在关键节点上出现**——活动「剩 3 天／明天结束／今天开启」
  这类节点命中才发（节点可在配置的 `notify` 一节自己调），平时就只发图、一个字都不发。

```
⚠️ 明天结束
📅 引航者试炼
🔥 今天开启
🎯 【寻访】石白深蓝之夜 · 结城理
```

> 一年里绝大多数日子是"只发图"：**不每天播报数据变化、也不播报首页上新**——那些信息图里都有。

⚠️ **QQ 官方机器人**的群聊推送需要在**手机 QQ 的群设置 → 机器人**里开启「机器人主动在群聊内发言」，
否则会被平台拒绝（日志里是 `主动消息失败, 无权限`）。命令出图不受影响（走被动回复）。
群主不是你、开不了这个开关时，把推送目标换到一个 OneBot（aiocqhttp）实例上的群即可。

## 常见问题

**第一次出图很慢？**
提示「首次出图要抓取数据」时是十几秒：要拉活动时间、卡池与各活动的公告，还要缓存底栏头像图标。
之后每天的第一张图会重新抓一次数据（几秒），当天后续请求直接渲染。


**到点了没收到推送？**
先发 `/甘特图状态` 看「上次」那行：失败会写在这里，且**下一次到点会自动再试**（成功的当天不会重发）。
如果是 QQ 官方机器人，多半是上面那条「机器人主动在群聊内发言」没开。

**图里缺剿灭、复刻这类长期任务？**
它们只写在活动公告里，日常维护只扫「进行中 + 近 30 天内结束过」的活动。发一次 `/甘特图初始化`（管理员）
会全量回溯所有活动的公告重建数据。保全派驻例外：PRTS 上没有任何写明其轮换日期的来源，暂时抓不到
（解析链路已就位，官方一旦公告就能自动跟上）。

**为什么每天背景不一样？怎么固定？**
背景按自然日抽签：同一天里大家看到的图是同一张，换天才换（整套配色由背景推导，所以配色也跟着换）。
想固定就在配置里填 `render.background_file`，或用 `render.background_dir` 换成自己的图。

**中文变成豆腐块 / 想让不同机器出的图完全一致？**
插件不随包字体，按「插件目录 `字体/` → AstrBot 的 `data/font.ttf` 等自定义槽 → 系统字体（雅黑 / 苹方 /
Noto CJK）」三层候选，缺字体不会出豆腐块。要跨机器逐像素一致，把那几支字体放回 `字体/` 即可
（下载地址见 `src/字体.py` 的说明）。

**怎么改标题、时间窗、底栏面板？**
都在插件配置页里，见下面的「配置项」。改完不用重启，下一次出图就生效。

**数据会天天变吗？**
每天第一次出图时重新抓取：新活动加进来、过期的删掉、时间改动更新。数据缓存在
`data/plugin_data/astrbot_plugin_ganttknights/`，与插件代码分开，升级插件不会丢。

**图有点长 / 想只看最近几天？**
把 `render.left_offset_days` 调小、`render.right_offset_days` 调小（最小 7 天）。

## 计划中

> 只列**还没做**的：做完就从这里删掉，历史看 [CHANGELOG](./CHANGELOG.md)。
> 想要哪一条、或者有别的想法，去 [Issues](https://github.com/Zrief/GanttKnights/issues) 说一声，点个 👍 也算票。

- **提醒预设**：一键切换「只提醒最后一天」「连开启前一天一起提醒」这类常用配法
- **自定义事件**：让该项目能泛化到一般的Gantt图提醒中去。（这个整体思路需要大改，还需要评估）

## 配置项

在 AstrBot 的插件配置页里改；下表与 `_conf_schema.json` 一一对应。

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `render.title` | string | 近期活动一览 | 图片主标题 |
| `render.left_offset_days` | int | 3（0~30） | 时间窗左侧回溯天数，0 = 只看今天起 |
| `render.right_offset_days` | int | 22（7~30） | 时间窗右侧前瞻天数；右边界会对齐到当周周日 |
| `render.background_file` | string | （空） | 指定用哪张背景（文件名或绝对路径）；留空则每天按日期自动取一张 |
| `render.background_dir` | string | （空） | 背景图目录；留空 = 插件自带的 `背景图/`。建议把自己的图放到 `data/plugin_data/astrbot_plugin_ganttknights/` 再指过来 |
| `panels.voucher` | bool | 开 | 底栏「凭证兑换」面板 |
| `panels.outfit` | bool | 开 | 底栏「新增时装」面板 |
| `panels.module` | bool | 开 | 底栏「新增模组」面板 |
| `data.auto_refresh_daily` | bool | 开 | 每天首次出图时自动更新数据；关掉后只出图不爬取 |
| `notify.enabled` | bool | 开 | 节点提醒总开关；关掉后一个字的提醒都不发，推送只发图 |
| `notify.end_enabled` | bool | 开 | 是否提醒「活动即将结束」 |
| `notify.start_enabled` | bool | 开 | 是否提醒「活动开启」 |
| `notify.end_offsets` | list | -3, -1 | **距结束**几天时提醒：-3 = 结束前 3 天、-1 = 最后一天、0 = 结束当天；留空 = 这类不提醒 |
| `notify.start_offsets` | list | 0 | **距开始**几天时提醒：0 = 开启当天、-1 = 前一天；留空 = 这类不提醒 |
| `notify.require_reminder` | bool | 关 | 只在有节点提醒时推送：当天没有任何节点命中就整次静默（连图都不发）。注意它和 `notify.enabled` 是一对——总开关关着就永远没有提醒 |
| `push.enabled` | bool | 关 | 开启每日推送 |
| `push.time` | string | 08:00 | 推送时刻（HH:MM，运行 AstrBot 那台机器的本地时间） |
| `push.targets` | list | （空） | 推送目标会话；用 `/订阅甘特图` 加入、`/退订甘特图` 移出，也可以直接在这里增删 |
| `push.text_template` | string | `{提醒}` | 有提醒那天附在图下面的文字；可用 `{提醒}`（提醒原文）、`{日期}`、`{条目数}`，留空 = 只发图 |

改动任何一项，下一次出图就按新值渲染（数值越界会被后端夹到范围内）。

## 许可与素材来源

- **代码**：[MIT](./LICENSE)，Copyright (c) 2026 Zrief。
- **游戏素材与数据**：明日方舟的图片、名称等版权属于上海鹰角网络科技有限公司及其关联公司；
  [PRTS Wiki](https://prts.wiki) 的页面内容遵循其站点声明。本项目仅用于非商业的信息展示，
  与鹰角网络、PRTS 均无隶属关系。
- **示例背景图**：`背景图/` 里的两张图只是让插件开箱可用，**不在 MIT 覆盖范围内**，请自行替换成
  你有权使用的图片。

## 致谢

写插件时读了这些项目的代码/文档（AstrBot 的开发原则也要求写清灵感来源并附链接）：

**有实际借鉴**

| 项目 | 在我们这里起了什么作用 |
|---|---|
| [astrbot_plugin_ark_calendar](https://github.com/zhewang448/astrbot_plugin_ark_calendar)（罗德岛行动终端） | 插件骨架：`Star` 子类 + 双参构造、把指令元数据收进 `CommandSpec`、生命周期顺序（`initialize` / `terminate`）。它还有一份意外贡献：依赖锁版本与宿主冲突的经历，让我们定下「`requirements.txt` 只写裸依赖名」这条规矩 |
| [astrbot_plugin_palette](https://github.com/Sisyphbaous-DT-Project/astrbot_plugin_palette) | 「配置即契约」的测试思路（schema / 代码默认值 / 文档三边一致）。它也帮我们划清了边界：注入 Dashboard `index.html`、改写宿主 `localStorage`、把 1845 行 JS 内嵌在 Python f-string 里这些做法，我们都没有采用（理由见 [`docs/插件化.md`](./docs/插件化.md) 的「明确不做」） |
| [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | [`docs/配色规范.md`](./docs/配色规范.md) 里「莫奈取色」的实现参考（`ColorExtractorHelper.cs` / `MonetPaletteHelper.cs`）：色相从背景图取、饱和度按角色固定 |

**同类产品（对照插件形状与数据做法）**

| 项目 | 作用 |
|---|---|
| [astrbot_plugin_skland](https://github.com/Azincc/astrbot_plugin_skland)（森空岛签到） | 明日方舟系插件的依赖清单与调度写法对照 |
| [astrbot_plugin_mrfzccl](https://github.com/Li-shi-ling/astrbot_plugin_mrfzccl)（明日方舟猜猜乐） | 同类插件怎么在导入期就直接 `import PIL / numpy / aiohttp` 的样本 |
| [astrbot_plugin_maa](https://github.com/Hakuin123/astrbot_plugin_maa)（MAA 远程控制） | 同类插件的最小依赖写法；它的 README 用相对路径图片（`img/*.jpg`），是「AstrBot 插件页看不见图」的样本之一 |
| [astrbot_plugin_endfield](https://github.com/Entropy-Increase-Team/astrbot_plugin_endfield)（终末地协议终端） | 同类游戏数据终端的功能形态与 `requirements`（httpx / jinja2 / playwright）对照 |

**为两件事做的生态抽样**（「依赖到底该怎么装」和「README 图片怎么写」）

| 项目 | 它告诉了我们什么 |
|---|---|
| [astrbot_plugin_code_renderer](https://github.com/Xbodwf/astrbot_plugin_code_renderer) | 导入期就 `import PIL / playwright`；`requirements.txt` 写 Pillow / Pygments / playwright |
| [astrbot_plugin_comfyui](https://github.com/cjxzdzh/astrbot_plugin_comfyui) | 同样的形状，并且源码里有 `ImportError` 兜底 |
| [astrbot_plugin_grok_suite](https://github.com/muqing-kg/astrbot_plugin_grok_suite) | 同上（导入期 `import aiohttp`） |
| [astrbot_plugin_fortnue](https://github.com/Xbodwf/astrbot_plugin_fortnue) | 抽样里**唯一**的懒加载样本（PIL 在函数体里 import） |
| [astrbot_plugin_proactive_chat](https://github.com/DBJD-CR/astrbot_plugin_proactive_chat) | 有 `requirements.txt` 但代码延迟导入；README 用相对路径 SVG |
| [astrbot_plugin_riddlegame](https://github.com/R1ddle1337/astrbot_plugin_riddlegame) | 只依赖宿主自带的库，代码里不 import 重库 |
| [astrbot_plugin_vocabcard](https://github.com/itismygo/astrbot_plugin_vocabcard) | `requirements.txt` 里有 playwright 但导入期不 import；README 用相对路径 `example.png` |
| [astrbot_plugin_daily_card](https://github.com/zhangkai542322/astrbot_plugin_daily_card) | **没有 `requirements.txt`**：直接用宿主自带的 PIL / aiohttp |
| [astrbot_plugin_psychological](https://github.com/Darkness218/astrbot_plugin_psychological) | 同上（无 `requirements.txt`，用宿主 aiohttp） |
| [astrbot_plugin_timeprogress](https://github.com/itismygo/astrbot_plugin_timeprogress) | 无 `requirements.txt`、导入期 `import playwright`；渲染失败时 log 一句 `pip install playwright && playwright install chromium` —— 「依赖装不上就给用户一句话」这个做法我们是照着它做的 |
| [astrbot_plugin_pic_toolbox](https://github.com/lirundong093-glitch/astrbot_plugin_pic_toolbox) | 导入期 `import PIL`、运行期才 `import requests`（同仓库里两种时机都有） |
| [astrbot_plugin_response2image](https://github.com/FloranceYeh/astrbot_plugin_response2image) | 抽样样本之一；它仓库里的 `main.py` 带 UTF-8 BOM 解析失败 —— 顺带确认了我们自己也要清 BOM |

> 统计口径：这 12 个 + 上面 4 个同类产品 + 主要参考共 19 个仓库，看的是各自 `main.py` 与
> `requirements.txt`。结论是**「写 `requirements.txt` + 导入期 import 依赖」是生态主流**（13 个可解析样本里 9 个），
> 所以本插件也把 `import matplotlib` 放在导入期（缺依赖时宿主会自动装好再重试，见
> [`docs/插件化.md`](./docs/插件化.md) 的「装得上、上得了架」）。
> 另外统计了官方市场全部 1332 条记录，用于决定 `tags` / `support_platforms` 怎么写。

感谢 AstrBot 与以上各插件的作者。

---

开发说明（架构、宿主硬事实、踩坑清单、改动时看哪里）见 [`docs/插件化.md`](./docs/插件化.md)；
版面与配色规则见 [`docs/配色规范.md`](./docs/配色规范.md)。
