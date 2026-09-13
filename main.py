"""AstrBot 插件入口 —— 明日方舟近期活动甘特图。

入口布局（`astrbot/core/star/star_manager.py::PluginManager._get_modules()`）：

    main.py      ← AstrBot 认它（与目录同名的 <目录名>.py 也会被认，但 main.py 优先）
    cli.py       ← 命令行入口（python cli.py），单人调试时比重启 AstrBot 快得多

两者共用 `src/流水线.py` 这一条渲染内核。

设计要点（详见 docs/插件化路线.md）：

* **加载期不碰重依赖**：matplotlib 只在工作线程里被导入（§5.5），
  `initialize()` 立即返回，不会拖慢 AstrBot 启动；
* **一切阻塞都在 `asyncio.to_thread` 里**：渲染是秒级 CPU 占用，取数是同步 httpx（§5.6）；
* **数据与代码分家**：数据写 `data/plugin_data/<插件名>/`（官方 storage 写法），
  字体/背景图留在插件目录里只读（§5.3）；
* **出图走签名缓存**：数据内容、显示配置、背景图、字体都没变时直接发缓存图，
  不重画（`插件/缓存.py`，§7）；
* 指令元数据只有一份：`插件/指令.py` 的 `CommandSpec`（§6.3）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .插件 import 文案
from .插件.配置 import 读取配置
from .插件.指令 import 帮助命令, 甘特图命令, 生成帮助文本
from .插件.渲染 import 渲染服务

PLUGIN_NAME = "astrbot_plugin_ganttknights"

插件版本 = "0.1.0"
"""与 metadata.yaml 的 version 一致（帮助页会显示它）。"""


def _额外字体(数据根: Path | None = None) -> dict[str, str]:
    """AstrBot 文档化的自定义字体插槽：`data/font.ttf` / `font-bold.ttf` / `font-mono.ttf`。

    官方提示原文："当使用 local 时，将 ttf 字体命名为 'font.ttf' 放在 data/ 目录下可自定义字体"
    （`astrbot/core/config/default.py` 的 t2i_strategy 说明）。三个名字按角色排：
    正文 / 粗体 / 等宽——存在哪个收哪个，内核把它插到候选表最前面。
    """
    根 = Path(数据根) if 数据根 is not None else Path(get_astrbot_data_path())
    约定 = (("正文", "font.ttf"), ("粗体", "font-bold.ttf"), ("等宽", "font-mono.ttf"))
    return {角色: str(根 / 名) for 角色, 名 in 约定 if (根 / 名).exists()}


class GanttKnightsPlugin(Star):
    """指令 + 生命周期；渲染细节全部委托给 `渲染服务`。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)  # 注意：config 不走 super()，自己存
        # 只有存在 _conf_schema.json 时 AstrBot 才传 config；取不到就退回全默认值，
        # 不让一个加载期 TypeError 把插件整个毙掉（§9 版本敏感点）。
        self.config: AstrBotConfig | dict = config if config is not None else {}
        self.plugin_dir = Path(__file__).resolve().parent

        # 官方 storage 写法：get_astrbot_data_path() + plugin_data/<插件名>。
        # 插件名优先用 AstrBot 注入的 self.name，取不到时回落常量（§5.3）。
        插件名 = getattr(self, "name", None) or PLUGIN_NAME
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / 插件名

        self.渲染 = 渲染服务(插件目录=self.plugin_dir, 数据目录=self.data_dir,
                             额外字体=_额外字体())
        # 构造期只准备缓存目录与环境变量，不 import matplotlib（那会阻塞加载 1s 以上）
        self.mplconfig_dir = self.渲染.准备matplotlib环境()

    async def initialize(self) -> None:
        """插件激活：只建目录、记日志——爬取与渲染都推迟到指令触发时。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "罗德岛甘特图已加载：插件目录 %s｜数据目录 %s｜matplotlib 缓存 %s",
            self.plugin_dir,
            self.data_dir,
            self.mplconfig_dir,
        )

    async def terminate(self) -> None:
        """插件禁用/重载：阶段三/四没有后台任务与调度器（阶段五才加）。

        渲染缓存**故意不清**：它落在 `data/plugin_data/<插件名>/渲染缓存/` 下，
        存在的意义就是跨重启复用（重新加载插件不该让当天的图重画一遍）。
        """
        logger.info("罗德岛甘特图已卸载。")

    # ==================== 指令 ====================

    @filter.command(甘特图命令.name, alias=甘特图命令.alias_set)
    async def 出图(self, event: AstrMessageEvent):
        """生成明日方舟近期活动甘特图长图。"""
        现在时间 = datetime.now()
        运行配置 = 读取配置(self.config)
        try:
            素材缺失 = self.渲染.素材问题(运行配置)
            if 素材缺失 is not None:
                yield event.plain_result(文案.缺背景图.format(目录=素材缺失))
                return

            # 命中签名缓存时几乎是瞬时的，就别再发一句"请稍候"打扰用户
            # （这一步只是预判，真正的判定在 出图() 的锁内重做）
            if not self.渲染.查现成图(现在时间, 运行配置):
                需数据, 需预告 = self.渲染.更新计划(现在时间, 运行配置)
                yield event.plain_result(文案.更新数据中 if (需数据 or 需预告) else 文案.渲染中)

            结果 = await self.渲染.出图(
                现在时间=现在时间,
                运行配置=运行配置,
                自动更新=运行配置.每日自动更新,
            )

            图片 = Path(结果.图片路径)
            if not self.渲染.产物可用(图片):
                # render_once() 内部会吞掉绘制异常（只记日志）；这里按"文件头魔数完整"
                # 再判一次，截断/空文件都不会当成品发出去
                yield event.plain_result(文案.渲染失败)
                return
            yield event.image_result(str(图片))
        except Exception:
            logger.exception("生成甘特图失败")
            yield event.plain_result(文案.渲染失败)

    @filter.command(帮助命令.name, alias=帮助命令.alias_set)
    async def 帮助(self, event: AstrMessageEvent):
        """查看本插件全部指令。"""
        yield event.plain_result(生成帮助文本(插件版本))
