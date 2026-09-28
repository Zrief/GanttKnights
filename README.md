# GanttKnights

一张长图看清《明日方舟》近期的活动排期：活动、卡池、凭证兑换、新增时装、新增模组。
数据全部来自 [PRTS Wiki](https://prts.wiki)。

<!-- 图片必须用绝对 URL：AstrBot 插件页是把它当 HTML 渲染的，相对路径会相对 dashboard 地址解析 → 404。
     jsDelivr 镜像 GitHub 仓库（写 @main 即跟随主分支），在国内的可达性比 raw.githubusercontent 好。 -->
![效果展示](https://cdn.jsdelivr.net/gh/Zrief/GanttKnights@main/Gantt.jpg)

装在 AstrBot 里当插件用，也可以拿命令行直接跑。

## 安装

### AstrBot
- 插件市场搜「明日方舟甘特图」，装好在群里发 `/方舟日程` 就能用了。
- 手动装的话，把仓库放进
`data/plugins/astrbot_plugin_ganttknights/`（目录名要和 `metadata.yaml` 里的 `name` 一致）。
数据落在 `data/plugin_data/` 下。

### 命令行（Python 3.12）

```bash
pip install httpx matplotlib Pillow numpy
python cli.py                      # 出图到 数据/Gantt.jpg
python cli.py --force              # 重新抓数据
python cli.py --bootstrap --force  # 首次建数据：翻老公告，把剿灭轮换、复刻排期补进来
```

<!-- 仓库根那份 Gantt.jpg 是开头展示图的快照，要更新就手动覆盖（维护者备注，读者不用管）。 -->

## 用法

命令是 `/方舟日程`（别名 `/方舟甘特`）：

| 用法 | 使用者 | 效果 |
|---|---|---|
| `/方舟日程` | 所有人 | 出图 |
| `/方舟日程 订阅` | 所有人 | 订阅每日推送 |
| `/方舟日程 退订` | 所有人 | 退订每日推送 |
| `/方舟日程 状态` | 所有人 | 看数据新旧、推送情况 |
| `/方舟日程 刷新` | 管理员 | 数据不对劲时重新抓一遍 |
| `/方舟日程 初始化` | 管理员 | 从头把数据重建一遍（怀疑缺内容时用） |
| `/方舟日程 帮助` | 所有人 | 指令列表 |

首次出图需要抓全量数据，大概半分钟内完成；之后每天第一张会重新抓一次（几秒），当天再出都是一份数据。

背景每天换一张（同一天内不变）；想固定某张，在配置里填 `render.background_file`。

标题、时间窗、底栏面板、提醒、推送全在插件配置页里，每项自带说明，改完不用重载，下次出图
生效。

## 每日推送

在想收图的会话里发一次 `/方舟日程 订阅` 就好了，不想收了发 `退订`。

也可以管理员直接在插件设置页里增删。

推送开关和时刻也在配置页，默认关，开了之后每天 08:00。

可通过偏移量自定义通知日期。默认结束前3天、前一天，开启日通知文本消息。

## 常见问题

**到点了没收到图？（QQ 官方机器人）**

群聊推送要在手机 QQ 的群设置 → 机器人里开启「机器人主动在群聊内发言」，不然平台会拒收
（日志里是 `主动消息失败, 无权限`）；命令出图不受影响。群主不是你、开不了这个开关，
就把推送目标挪到 OneBot（aiocqhttp）的群里。

更多问题欢迎反映到issue。

## 计划中

> 只列还没做的，做完就删，历史看 [CHANGELOG](./CHANGELOG.md)。
> 想要哪条可以去 [Issues](https://github.com/Zrief/GanttKnights/issues) 提。

- 提醒预设：内置「只提醒最后一天」「开启前一天也提醒」几套常用配法，直接选
- 提醒增强：提供自定义提醒文本功能
- 保全派驻：等有机会添加进来。
- 自定义事件：把活动提醒做成通用的甘特图提醒（思路要大改，先鸽着）

## 许可与素材来源

- 代码 [MIT](./LICENSE)，Copyright (c) 2026 Zrief。
- 明日方舟的图片、名称归上海鹰角网络；PRTS 页面内容遵循其站点声明。本项目只做非商业的
  信息展示，与两家均无隶属关系。
- `背景图/` 里那两张只是附带的示例图，不在 MIT 覆盖范围内，用之前换成你自己有权用的图。

## 致谢

AstrBot 的开发原则要求写明借鉴来源，实际借过这三家：

- [astrbot_plugin_ark_calendar](https://github.com/zhewang448/astrbot_plugin_ark_calendar)——插件骨架
  （Star 子类、CommandSpec、生命周期顺序），以及「requirements.txt 只写裸依赖名」的规矩
- [astrbot_plugin_palette](https://github.com/Sisyphbaous-DT-Project/astrbot_plugin_palette)——
  「配置即契约」的测试思路（schema 与代码默认值两边一致）
- [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights)——
  「莫奈取色」的实现参考（色相从背景图取、饱和度按角色固定），详见 [docs/配色规范.md](./docs/配色规范.md)

---

开发说明（架构、AstrBot 宿主的行为约束、踩坑清单）见 [docs/插件化.md](./docs/插件化.md)，
版面与配色规则见 [docs/配色规范.md](./docs/配色规范.md)。
