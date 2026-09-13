"""流水线 — CLI 与 AstrBot 插件共用的渲染入口。

设计约束（决定这里放什么、不放什么）：

1. **单一入口**：`render_once()` 完成"数据 → 图片 + 警告"，参数显式传入，
   不读 argparse、不自己决定"今天要不要爬"这类**策略**（策略属于入口层）。
2. **不认识 AstrBot**：本模块不 import astrbot，也不知道插件/命令/会话。
3. **路径全部走 settings**：可被构造参数或 GK_* 环境变量覆盖，
   入口层想换数据位置不必改这里。

数据获取（爬取 / 合并 CSV / 新增预告）与"今天是否已爬过"的判断，
以独立函数形式导出，由 CLI 与插件各自按自己的节奏调用——
CLI 用 `今天写过()` 做每日一次的新鲜度检查，插件则可能按缓存签名判断。

## 关于重依赖的延迟导入（重要）

本模块**故意不在顶层 import 会拖入 matplotlib 的子模块**（绘图_图表 / 绘图_主题 /
绘图_排版 / 字体）。原因：同步 `import matplotlib` 实测会让 AstrBot 事件循环
停顿 0.5s 以上（见 docs/插件化路线.md §5.5），而插件加载期是同步执行的。

顶层只保留"轻"依赖（config / 获取_prts / 汇总_活动 / 解析_* / 生成_警告）；
matplotlib 相关一律在 `render_once()` 内部按需导入——而 render_once 由入口层放进
`asyncio.to_thread` 执行，导入开销落在工作线程，不阻塞事件循环。
代价是首次渲染多花约 1s（一次性），之后走 sys.modules 缓存。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from random import choice

from .config import settings
from .获取_prts import 下载图片, 获取事件列表, 获取首页
from .汇总_活动 import 合并保存CSV, 合并商店, 去重排序
from .解析_API活动 import API转活动列表
from .生成_警告 import 生成警告
from .筛选_活动 import preprocess_data

logger = logging.getLogger("ganttknights")

_DEFAULT_TITLE = "近期活动一览"
_WARN_SECTIONS = ("凭证兑换", "新增时装", "新增模组")


@dataclass(frozen=True)
class 渲染结果:
    """render_once() 的产出：产物路径 + 可播报的概要"""

    图片路径: Path
    概况: str
    警告: str
    标题: str
    条目数: int
    名称数: int
    分区计数: dict[str, int]


# ============================ 数据获取（入口层按需调用）============================

def 读取已解析来源() -> set[str]:
    """从 store 读出公告解析成功过的活动名，用于跳过重复解析"""
    import csv

    来源: set[str] = set()
    路径 = Path(settings.all_data_path)
    if not 路径.exists():
        return 来源
    try:
        with open(路径, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                值 = (row.get("来源") or "").strip()
                if 值:
                    来源.add(值)
    except Exception:
        logger.exception("读取已解析来源失败")
    return 来源


def 更新数据(现在字符串: str, 回溯已结束: bool = False) -> None:
    """爬取 + 解析 + 合并 + 保存活动数据（不含首页新增预告）

    首页新增预告（凭证/时装/模组）不在活动数据里，由 更新增预告() 单独按天刷新。
    """
    try:
        api原始 = 获取事件列表(settings.api_limit)
    except Exception:
        logger.exception("获取事件列表失败（网络可能断开了）")
        return
    if not api原始:
        logger.warning("API 未返回数据")
        return

    活动列表 = API转活动列表(api原始, 现在字符串, 读取已解析来源(), 回溯已结束=回溯已结束)

    活动列表 = 合并商店(活动列表)

    # 卡池数据
    try:
        from .解析_卡池 import 抓取卡池一览

        活动列表.extend(抓取卡池一览())
    except Exception:
        logger.exception("获取卡池数据失败")

    活动列表 = 去重排序(活动列表)

    if 活动列表:
        合并保存CSV(活动列表, settings.all_data_path, 现在字符串)
        logger.info("数据更新完成，共 %d 条活动", len(活动列表))
    else:
        logger.warning("未获取到有效活动")


def _写新增预告(新增: dict, 现在字符串: str) -> None:
    Path(settings.new_items_path).write_text(
        json.dumps(新增, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _清理图标缓存(缓存目录: Path, 引用名们: set[str]) -> None:
    """删除不再被当前预告引用的孤儿图标"""
    删了 = 0
    for f in 缓存目录.iterdir():
        if f.is_file() and f.name not in 引用名们:
            f.unlink()
            删了 += 1
    if 删了:
        logger.info("  清理孤儿图标 %d 个", 删了)


def 更新增预告(现在时间: datetime, 现在字符串: str) -> dict:
    """抓首页新增时装/模组/凭证，图标缓存到 数据/图片缓存/，写 新增预告.json"""
    from .解析_首页 import 解析新增内容, 预告键

    首页 = 获取首页()
    if 首页 is None:
        logger.warning("首页获取失败，沿用上次预告数据")
        return {}
    新增 = 解析新增内容(首页)
    if not any(新增.values()):
        # 覆盖为带时间戳的空预告，避免警告里长期播报早已结束的上新
        logger.warning("首页未解析到新增内容，预告清空")
        新增 = {键: [] for 键 in 预告键}
        新增["更新时间"] = 现在字符串
        _写新增预告(新增, 现在字符串)
        return 新增

    缓存目录 = Path(settings.icon_cache_dir)
    缓存目录.mkdir(parents=True, exist_ok=True)
    for 条目们 in 新增.values():
        for 条目 in 条目们:
            目标 = 缓存目录 / 条目["图标文件名"]
            if 下载图片(条目["图标"], 目标):
                条目["图标文件"] = 条目["图标文件名"]

    新增["更新时间"] = 现在字符串
    _写新增预告(新增, 现在字符串)
    引用名们 = {t["图标文件名"] for ts in 新增.values() if isinstance(ts, list) for t in ts}
    _清理图标缓存(缓存目录, 引用名们)
    logger.info(
        "新增预告: " + " / ".join(f"{键} {len(新增[键])}" for 键 in 预告键) + "，图标缓存于 %s",
        缓存目录,
    )
    return 新增


def 今天写过(路径: Path, 现在时间: datetime) -> bool:
    """文件存在且是今天写的 —— 用于"每天只做一次"的新鲜度检查

    现在时间 必须由调用方传入：作为长驻进程（AstrBot 插件）运行时，
    "今天"要按每次调用的实际时间算，不能是模块导入时刻。
    """
    return 路径.exists() and datetime.fromtimestamp(路径.stat().st_mtime).date() == 现在时间.date()


# ============================ 渲染 ============================

def 挑选背景图(背景路径: str | Path | None = None) -> str:
    """未指定背景时从 bg_dir 随机取一张；目录为空则抛 SystemExit（与改造前一致）"""
    if 背景路径:
        return str(背景路径)
    背景列表 = list(Path(settings.bg_dir).glob("*"))
    if not 背景列表:
        logger.error("背景图目录为空: %s", settings.bg_dir)
        raise SystemExit(1)
    return str(choice(背景列表))


def 读取新增内容() -> dict:
    """读 数据/新增预告.json；缺失或损坏时按空预告处理（底栏上新区留空）"""
    路径 = Path(settings.new_items_path)
    if not 路径.exists():
        logger.warning("新增预告不存在，底栏上新区留空: %s", 路径)
        return {}
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("新增预告解析失败，底栏上新区留空")
        return {}


def 布置头像(分区: list[tuple[str, list[dict]]]) -> None:
    """底栏条目的头像补齐到 数据/图片缓存/（已存在的跳过），失败只记数不中断"""
    缓存目录 = Path(settings.icon_cache_dir)
    缓存目录.mkdir(parents=True, exist_ok=True)
    失败 = 0
    for _, 条目们 in 分区:
        for 条目 in 条目们:
            url, 文件名 = 条目.get("图标"), 条目.get("图标文件名")
            if not url or not 文件名:
                continue
            if not 下载图片(url, 缓存目录 / 文件名):
                失败 += 1
    if 失败:
        logger.warning("%d 个头像下载失败，渲染时会跳过", 失败)


def render_once(
    现在时间: datetime | None = None,
    强制刷新: bool = False,
    回溯已结束: bool = False,
    输出路径: str | Path | None = None,
    背景路径: str | Path | None = None,
    标题: str = _DEFAULT_TITLE,
    提醒天数: int = 3,
    控制台打印警告: bool = True,
) -> 渲染结果:
    """数据 → 图片 + 警告。不碰 argparse，也不判断"今天要不要爬"。

    参数:
        现在时间      : 渲染基准时间；None 时取当前时间
        强制刷新      : True 时先重新爬取活动数据与首页新增预告
        回溯已结束    : 传给爬虫，补录剿灭/保全等长期任务（首次建数据用）
        输出路径      : None 时用 settings.output_path
        背景路径      : None 时从 settings.bg_dir 随机取一张
        标题          : 图片主标题
        提醒天数      : 过期警告的提醒窗口
        控制台打印警告: 是否把警告同时打到 stdout（CLI 用；插件应关掉）
    """
    现在时间 = 现在时间 or datetime.now()
    现在字符串 = 现在时间.strftime("%Y-%m-%d %H:%M:%S")
    输出 = Path(输出路径 or settings.output_path)

    # 重依赖按需导入：matplotlib 只在这里被拖进来，而 render_once 由入口层
    # 放进 asyncio.to_thread 执行，因此这 1s 左右的导入不会卡住事件循环。
    from .绘图_排版 import 建分区, 绘制甘特图
    from .绘图_主题 import 建主题

    # 可选的数据刷新（策略由调用方决定，这里只执行）
    if 强制刷新:
        更新数据(现在字符串, 回溯已结束=回溯已结束)
        try:
            更新增预告(现在时间, 现在字符串)
        except Exception:
            logger.exception("新增预告获取失败")

    # 按时间窗口过滤
    今天 = 现在时间.replace(hour=0, minute=0, second=0, microsecond=0)
    左边界 = 今天 - timedelta(days=settings.left_offset_days)
    右边界 = 今天 + timedelta(days=settings.right_offset_days - 今天.weekday())

    df = preprocess_data(
        all_data_path=settings.all_data_path,
        now=今天,
        left_border=左边界,
        right_border=右边界,
    )
    if df.empty:
        logger.warning("没有即将开始或进行中的活动，请更新数据源。")

    # 背景图 → 整套配色由这一张图推导
    背景 = 挑选背景图(背景路径)
    主题 = 建主题(背景)

    # 底栏上新区（凭证/时装/模组）
    新增内容 = 读取新增内容()
    分区 = 建分区(新增内容)
    try:
        布置头像(分区)
    except Exception:
        logger.exception("头像补下载失败，缺图标的条目按无图渲染")

    概况 = ""
    try:
        概况 = 绘制甘特图(
            输出, 分区, df, 主题, 左边界, 右边界, 背景, 现在时间, 标题=标题,
        )
        logger.info("图表已保存至 %s（%s）", 输出, 概况)
    except Exception:
        logger.exception("绘制图表失败")

    # 过期警告
    警告 = ""
    try:
        警告 = 生成警告(df, 提醒天数=提醒天数, 新增内容=新增内容)
        if not 警告:
            警告 = "博士，罗德岛当前所有行动均在正常排期内，无需提醒。"
        if 控制台打印警告:
            print("\n" + "=" * 54)
            print(警告)
            print("=" * 54)
        Path(settings.warning_path).write_text(警告, encoding="utf-8")
        logger.info("过期警告已保存至 %s", settings.warning_path)
    except Exception:
        logger.exception("生成警告失败")

    return 渲染结果(
        图片路径=输出,
        概况=概况,
        警告=警告,
        标题=标题,
        条目数=int(len(df)),
        名称数=sum(len(新增内容.get(k) or []) for k in _WARN_SECTIONS),
        分区计数={区名: len(条目们) for 区名, 条目们 in 分区},
    )
