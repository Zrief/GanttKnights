# GanttKnights

用一张长图查看《明日方舟》近期排期：活动、卡池、凭证兑换、时装和模组。
数据来自 [PRTS Wiki](https://prts.wiki)。

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
python cli.py --bootstrap --force  # 初始化：全量扫描老公告后覆盖重建（旧数据不保留，可顺带换掉旧格式）
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
| `/方舟日程 初始化` | 管理员 | 全量扫描老公告后**覆盖重建**（旧数据不保留；怀疑缺内容或换格式时用） |
| `/方舟日程 帮助` | 所有人 | 指令列表 |

首次生成图片会抓取数据，通常需要几十秒；之后每天第一次生成时更新数据，后续生成会直接使用当天数据。

`初始化` 会重新扫描最近半年公告并覆盖重建活动数据；日常刷新只做增量合并。数据来源不完整时，其他活动仍会继续更新，并在图片中提示。

背景图默认按日期顺序轮换，每天更换一张，同一天内保持不变；如需固定图片，请在配置中填写 `render.background_file`。
标题、时间范围、底栏面板、提醒和推送也都可在配置页修改，修改后下次生成图片生效。

## 每日推送

1. 在要收图的会话中发送 `/方舟日程 订阅`。
2. 在插件设置中开启推送并选择时间（默认每天 08:00）。
3. 不想接收时发送 `/方舟日程 退订`，或从设置页删除目标会话。

默认在活动结束前 3 天、前 1 天和开启当天提醒；提醒日期、是否只在有提醒时推送、附带文案均可配置。

## 常见问题

### 配置从哪里改？

AstrBot 管理面板 → 插件 → 明日方舟甘特图。设置分为「出图」「底栏面板」「数据源」「提醒节点」「每日推送」五组；每项都有简短说明。大多数修改无需重载插件，下次出图即可生效。


**到点了没收到图？（QQ 官方机器人）**

QQ 官方机器人若要在群里定时推送，请在手机 QQ 的「群设置 → 机器人」中开启「机器人主动在群聊内发言」。否则命令出图不受影响，但定时推送会被拒收。若无法开启，请改用 OneBot（aiocqhttp）群聊。

**Docker 里中文全变成方块？**

当前环境缺中文字体。更新官方镜像后重建容器即可；也可以将中文字体（如思源黑体）放入 AstrBot 数据目录的 `font.ttf`，重启后生效。需要分别指定正文、粗体或等宽字体时，可使用 `font-bold.ttf`、`font-mono.ttf`。

更多问题或建议请提交到 [Issues](https://github.com/Zrief/GanttKnights/issues)。

## 计划中

> 仅列尚未完成的事项；已完成内容见 [CHANGELOG](./CHANGELOG.md)。

- 更灵活的提醒文案

欢迎在 [Issues](https://github.com/Zrief/GanttKnights/issues) 提交建议。

## 许可与素材来源

- 代码 [MIT](./LICENSE)，Copyright (c) 2026 Zrief。
- 明日方舟的图片和名称归上海鹰角网络所有；PRTS 页面内容遵循其站点声明。本项目仅用于非商业信息展示，与上述主体无隶属关系。
- `背景图/` 中的图片仅作示例，不包含在 MIT 许可内，请确认拥有使用权后再替换使用。

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
