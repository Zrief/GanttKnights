"""AstrBot 插件入口 —— 明日方舟近期活动甘特图。

入口布局（`astrbot/core/star/star_manager.py::PluginManager._get_modules()`）：

    main.py      ← AstrBot 认它（与目录同名的 <目录名>.py 也会被认，但 main.py 优先）
    cli.py       ← 命令行入口（python cli.py），单人调试时比重启 AstrBot 快得多

两者共用 `src/流水线.py` 这一条渲染内核。

设计要点（详见 docs/插件化路线.md）：

* **导入期只碰 matplotlib 一个重依赖**：它在顶层就被 import（缺依赖时宿主据此自动装依赖，§19），
  而 pyplot 与绘图模块仍留在渲染线程里（§5.5），`initialize()` 立即返回；
* **一切阻塞都在 `asyncio.to_thread` 里**：渲染是秒级 CPU 占用，取数是同步 httpx（§5.6）；
* **数据与代码分家**：数据写 `data/plugin_data/<插件名>/`（官方 storage 写法），
  字体/背景图留在插件目录里只读（§5.3）；
* **不留渲染缓存**：每次出图按当天数据现画（一次 matplotlib 几秒），
  从而不必维护签名、失效与落盘三套状态（§17.4）；
* **入口层只做四件事**：读配置、说一句进度、出图、发图。判断（数据要不要刷、背景选哪张）
  全在 `渲染服务` 里——入口层多做一份"预判"只会多一条会分叉的路径；
* 指令与回调的元数据只有一份：`插件/指令.py` 的 `CommandSpec`（§6.3）。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import astrbot.api.message_components as 组件
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

PLUGIN_NAME = "astrbot_plugin_ganttknights"

# ==================== 依赖：按生态的约定俗成来（2026-09-15 定，见 docs/插件化路线.md §19）====================
#
# **matplotlib 在导入期就 import**：宿主唯一会替插件装依赖的时刻，就是"插件导入抛
# `ModuleNotFoundError`"的时候（`core/star/star_manager.py` 的
# `_import_plugin_with_dependency_recovery`：预检 requirements.txt → pip 装缺的 → 重试导入）。
# 顶层 import 它 = 缺依赖时导入失败 = 宿主自动装好再重试，用户零操作——和生态里 9/13 的插件同形。
#
# ⚠️ `MPLCONFIGDIR` 必须在 matplotlib **首次导入之前**设好（§5.5）：容器/只读环境里默认配置目录
# 不可写，会报错或反复重建字体缓存。
#
# 🚫 这两行（环境变量 + import）是**功能性的**，不是装饰：删掉之后一切照常运行，只是"缺依赖"会
# 重新变成用户要自己处理的故障（`tests/test_入口契约.py` 钉着它们和它们的先后顺序）。
_mplconfig = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME / "mplconfig"
_mplconfig.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(_mplconfig)

import matplotlib  # noqa: E402,F401  —— 导入本身即"检查依赖"，别删

from .插件 import 文案  # noqa: E402
from .插件.配置 import 读取配置  # noqa: E402
from .插件.指令 import 刷新命令, 帮助命令, 甘特图命令, 状态命令, 初始化命令, 生成帮助文本  # noqa: E402
from .插件.渲染 import 素材缺失, 渲染服务  # noqa: E402
from .插件.推送 import 推送状态, 推送服务  # noqa: E402

插件版本 = "0.1.0"
"""与 metadata.yaml 的 version 一致（帮助页会显示）。"""


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
    """指令 + 生命周期；渲染细节全部委托给 `渲染服务`，推送委托给 `推送服务`。"""

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

        self.推送状态 = 推送状态(self.data_dir / "推送状态.json")
        self.推送 = 推送服务(
            渲染=self.渲染,
            状态=self.推送状态,
            发送=self._发送,
            配置读取=self.运行配置,
        )

    # ==================== 生命周期 ====================

    async def initialize(self) -> None:
        """只建目录、清一次旧版本残留、读一次配置、武装定时任务——爬取与渲染都推迟到真正出图时。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.渲染.清理旧缓存()      # 阶段四的 渲染缓存/ 已废弃，顺手删掉
        logger.info(
            "罗德岛甘特图已加载：插件目录 %s｜数据目录 %s｜matplotlib 缓存 %s",
            self.plugin_dir, self.data_dir, self.mplconfig_dir,
        )
        logger.info("每日推送：%s", self.推送.确保任务(self.运行配置()))

    async def terminate(self) -> None:
        """插件禁用/重载：关停调度器。

        数据（`所有活动数据.csv`、当天日差、推送记账）留在 `data/plugin_data/` 下，
        跨重启自然复用；渲染产物不在状态里，下次出图重画一遍即可（§17.4）。

        ⚠️ 不要给这个类加 `__del__`：`star_manager.py` 是 `if __del__ … elif terminate`，
        加了之后 `terminate()` 永远不会执行（§16）。
        """
        await self.推送.停()
        logger.info("罗德岛甘特图已卸载。")

    # ==================== 内部工具 ====================

    def 运行配置(self):
        """现读配置（WebUI 改完无需重载插件；定时任务也走这里）"""
        return 读取配置(self.config)

    # ==================== 推送目标 ====================

    def _补齐首个推送目标(self, unified_msg_origin: str, 运行配置) -> None:
        """`push.targets` 为空时，把"第一个用指令的会话"写进配置。

        为什么写配置而不是状态文件：用户要能**在设置页里删掉某个群的推送**，
        所以推送目标必须是配置项（`list` 型）。列表非空时一律不再自动添加——
        用户删掉的那一项不该被下一次指令又加回来。
        """
        if 运行配置.推送目标:
            return
        节 = self.config.get("push") if hasattr(self.config, "get") else None
        if not isinstance(节, dict):
            logger.warning("配置里没有 push 节，跳过自动填写推送目标")
            return
        节["targets"] = [unified_msg_origin]
        保存 = getattr(self.config, "save_config", None)
        if callable(保存):
            try:
                保存()
            except Exception:
                logger.exception("推送目标写回配置失败（本次运行仍然生效）")
        logger.info("推送目标列表为空 → 已把本会话记进配置 push.targets：%s（可在插件设置里增删）",
                    unified_msg_origin)

    async def _发送(self, unified_msg_origin: str, 文本: str, 图片路径: str) -> bool:
        """把一条消息投递到指定会话。

        - 只用 `unified_msg_origin`（裸 session_id 会在宿主的 `split(":", 2)` 处炸，§16）；
        - `send_message()` 返回 `False` 只表示"没找到匹配的平台实例"，非法 umo 直接抛
          `ValueError` → 这里两者都当失败，异常向上抛给推送服务记进状态；
        - 不预检平台能力：`support_proactive_message` 是 4.28 新增且默认 True（信不过），
          发一次并把结果记下来比读字段可靠（§16）。
        """
        链 = [组件.Plain(text=文本)] if 文本 else []
        链.append(组件.Image.fromFileSystem(图片路径))
        结果 = await self.context.send_message(unified_msg_origin, MessageChain(链))
        if 结果 is False:
            logger.warning("投递未找到平台实例：%s", unified_msg_origin)
            return False
        return True

    # ==================== 指令 ====================

    @filter.command(甘特图命令.name, alias=甘特图命令.alias_set)
    async def 出图(self, event: AstrMessageEvent):
        """生成明日方舟近期活动甘特图长图。"""
        运行配置 = self.运行配置()
        # 推送目标列表为空时，把"第一个用指令的会话"写进配置项 `push.targets`：
        # 零配置也能用上推送；写进配置之后它就在设置页里可见、可删（用户要的"能删订阅"）。
        self._补齐首个推送目标(event.unified_msg_origin, 运行配置)
        # 顺手重新武装一次定时任务（配置在 WebUI 里改过时不必重启插件）
        self.推送.确保任务(self.运行配置())
        yield event.plain_result(文案.准备中)
        try:
            结果 = await self.渲染.出图(
                现在时间=datetime.now(), 运行配置=运行配置, 自动更新=运行配置.每日自动更新
            )
            图片 = Path(结果.图片路径)
            if not self.渲染.产物可用(图片):
                # render_once() 内部会吞掉绘制异常（只记日志）；这里按"文件头魔数完整"再判一次
                yield event.plain_result(文案.渲染失败)
                return
            yield event.image_result(str(图片))
        except 素材缺失 as exc:
            yield event.plain_result(文案.说明素材缺失(exc))
        except Exception:
            logger.exception("生成甘特图失败")
            yield event.plain_result(文案.渲染失败)

    @filter.command(状态命令.name, alias=状态命令.alias_set)
    async def 状态(self, event: AstrMessageEvent):
        """查看数据/缓存/每日推送的现状。"""
        # 顺手重新武装：状态页里报的"下次推送"必须与实际生效的一致
        self.推送.确保任务(self.运行配置())
        yield event.plain_result(self._状态文本(event))

    @filter.command(刷新命令.name, alias=刷新命令.alias_set)
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 刷新(self, event: AstrMessageEvent):
        """强制重新抓数据并重画（管理员）。"""
        yield event.plain_result(文案.强制刷新中)
        try:
            结果 = await self.渲染.出图(
                现在时间=datetime.now(), 运行配置=self.运行配置(),
                自动更新=True, 强制刷新=True,
            )
            图片 = Path(结果.图片路径)
            if not self.渲染.产物可用(图片):
                yield event.plain_result(文案.渲染失败)
                return
            yield event.image_result(str(图片))
        except 素材缺失 as exc:
            yield event.plain_result(文案.说明素材缺失(exc))
        except Exception:
            logger.exception("强制刷新失败")
            yield event.plain_result(文案.渲染失败)

    @filter.command(初始化命令.name, alias=初始化命令.alias_set)
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def 初始化(self, event: AstrMessageEvent):
        """全量重建数据（管理员）：连更老的已结束活动的公告一起扫。

        等价 `python cli.py --bootstrap --force`。什么时候需要：wiki 会**复用老活动页**
        来排复刻/长期轮换，这些内容只有全量扫描才看得到（日常维护只看"进行中 ∪ 近 30 天内
        结束过"的活动）。全新安装时插件会自动做一次，所以这条指令是"我怀疑数据不全"时的手动入口。
        """
        yield event.plain_result(文案.初始化中)
        try:
            self.渲染.重建数据()      # 删掉旧 CSV 与当天日差 → 从零重建（多余/错年份的行一并清掉）
            结果 = await self.渲染.出图(
                现在时间=datetime.now(), 运行配置=self.运行配置(),
                自动更新=True, 强制刷新=True, 回溯已结束=True,
            )
            图片 = Path(结果.图片路径)
            if not self.渲染.产物可用(图片):
                yield event.plain_result(文案.渲染失败)
                return
            if 结果.变化:
                yield event.plain_result(结果.变化)
            yield event.image_result(str(图片))
        except 素材缺失 as exc:
            yield event.plain_result(文案.说明素材缺失(exc))
        except Exception:
            logger.exception("全量初始化失败")
            yield event.plain_result(文案.渲染失败)

    @filter.command(帮助命令.name, alias=帮助命令.alias_set)
    async def 帮助(self, event: AstrMessageEvent):
        """查看本插件全部指令。"""
        yield event.plain_result(生成帮助文本(插件版本))

    # ==================== 状态文本 ====================

    def _状态文本(self, event: AstrMessageEvent) -> str:
        """`/甘特图状态`：数据新鲜度 / 日差 / 推送武装情况 / 本会话标识。

        刻意不报"缓存条数"之类的东西——渲染不留缓存（§17.4），状态页只回答
        "数据新不新、今天推送会不会来、上次推得怎么样"。
        """
        运行配置 = self.运行配置()
        设置 = self.渲染.内核设置(运行配置)

        数据 = Path(设置.all_data_path)
        if 数据.exists():
            时刻 = datetime.fromtimestamp(数据.stat().st_mtime)
            新鲜 = "今天已更新" if 时刻.date() == datetime.now().date() else "不是今天的"
            数据行 = f"{时刻:%Y-%m-%d %H:%M}（{新鲜}）"
        else:
            数据行 = "还没有数据（首次出图时抓取）"
        快照日期 = self.渲染.最近变化日期() or "无"
        目标们 = 运行配置.推送目标
        本会话 = event.unified_msg_origin
        在列 = "已在推送目标里" if 本会话 in 目标们 else "不在推送目标里"
        上次 = self.推送状态.上次()
        上次行 = ""
        if 上次:
            上次行 = (f"\n上次推送：{上次.get('时刻', '?')} 成功 {上次.get('成功', 0)}"
                      f" / 失败 {上次.get('失败', 0)}")
            if 上次.get("说明"):
                上次行 += f"（{上次['说明']}）"
        return (
            f"罗德岛甘特图 v{插件版本}\n"
            f"数据：{数据行}｜最近快照 {快照日期}\n"
            f"{self.推送.一句话(运行配置)}\n"
            f"推送目标 {len(目标们)} 个（可在插件设置里增删）\n"
            f"本会话：{本会话}（{在列}）"
            f"{上次行}"
        )
