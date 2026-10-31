"""解析层 — 公告页 / 活动页的 wikitext 解析

- `抽板块` / `板块条目` / `关卡条目`：公告 → 板块表与条目。纯解析，认领策略见 解析_API活动。
- `解析活动信息` / `公告定位` / `页父名`：活动页 `{{活动信息}}` 的 `公告=` 指认——
  wiki 在这里维护着"这条活动的内容在哪个公告页的哪个板块"，可带 #板块锚点
  （如 此夜同行 → 月行水上/活动公告#【…】签到活动开启）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import unescape

from . import 长期活动
from .日志 import logger
from .公告局部识别 import 局部识别结果, 识别局部记录
from .公告时间选用 import 选用公告时间
from .公告身份 import 局部身份依据

# ---------- 正则 ----------

# 年份是**可选**的：公告多数只写"X月X日"，偶尔在跨年处才写"2026年01月02日"。
# 组号因此是 1..5（起：年/月/日/时/分）与 6..10（止：年/月/日/时/分）。
时间正则 = re.compile(
    r"(?:活动时间|售卖时间|开放时间|开启时间|关卡开放时间|家具商店售卖时间)"
    r"[：:]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
    r"\s*[～~\-]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
)

关卡时间正则 = re.compile(
    r"◆.+?[：:]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
    r"\s*[～~\-]\s*"
    r"(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})"
)

寻访名单正则 = re.compile(r"★★★★★★(?:（[^）]*）)?[：:]\s*([^{}\n]+)")
"""寻访池板块的六星名单行。两种真实写法一套通吃（2026-10-05 实测）：

- 甄选：`★★★★★★（6★出率：2%）：Mon3tr / 圣聆初雪 / …`（占比括号在前）
- 普通池：`★★★★★★：克莱门莎（占6★出率的50%）`（占比括号缀在名字后）
- 夏活限定池：`★★★★★★：予愿安洁莉娜[限定] \\ 珊比}}（占6★出率的70%）`
  （反斜杠分隔、[限定] 标签、占比括号在 {{color}} 外）

`[^{}\n]+` 在 }} 处截断。分隔符按 `/` 与 `\\` 切，逐名剥 `[限定]` 与（…）尾注。
只认六颗星：五星行（★★★★★）天然不匹配，与 卡池一览 只取六星同口径。
"""

标题正则 = re.compile(r"^(={2,4})(.+?)\1\s*$", re.M)

# ---------- 类型映射 ----------

章节类型规则 = [
    (["特别招募", "签到", "许愿墙"], 2),   # 特别招募/许愿墙＝福利（2026-10-31 定）
    (["活动关卡", "关卡开启", "SideStory", "锦标", "阵地足球"], 1),
    (["组合包", "采购中心", "礼包"], -1),
    (list(长期活动.关键词们), 长期活动.类型值),   # 长期玩法：定义只有一份（src/长期活动.py）
]

# 池开放板块抽六星名单；寻访次数赠送先识别为福利，不要求干员名单。
# 寻访池条目由 卡池一览 wikitext 提供，但一览是 bot 维护、上新滞后——公告板块是
# 它登记前唯一的预告源（定向甄选08、海渊巡游均实测滞后数天）。所以带「寻访/甄选」
# 的板块不跳过、改抽六星名单生成池条目；名单抽不出来就不生成（宁缺毋重）。
跳过关键词 = ["新装", "时装", "风尚", "复刻上架", "家具", "干员登场", "凭证", "主题场景", "全息作战矩阵",
        "许愿墙", "特别登录活动", "限定寻访每日赠送"]
"""贩售栏目不上图：含"风尚"的是时装复刻贩售（【罗德岛风尚回顾】限时开启，恒远津梁
2026-10-29 实测：标题不带"时装"二字躲过上词）；含"复刻上架"的是系列复刻贩售
（【待予花冠】系列，限时复刻上架 / 【时代】系列，限时复刻上架，辞岁行·危机合约
实测）——都只留贩售期信息，与 新装/时装 同口径。

「许愿墙 / 特别登录活动 / 限定寻访每日赠送」2026-10-31 起**整类不上图**：
三类福利的标题写法各年不一致（七周年的许愿墙叫【泽尔格勒告示板】、春节的十连券并进
签到），要统一就得堆一堆正文特征规则；用户决定不做专门识别，直接跳过。
"""


def 是寻访赠送板块(标题: str) -> bool:
    """寻访次数赠送是福利，不是另一个卡池开放公告。"""
    return "寻访" in 标题 and any(词 in 标题 for 词 in ("每日赠送", "免费寻访"))


def 是寻访池板块(标题: str) -> bool:
    return not 是寻访赠送板块(标题) and ("寻访" in 标题 or "甄选" in 标题)


def _抽干员名单(文本: str) -> list[str]:
    """六星名单原文 → 干员名列表：按 `/`、`\\` 切，逐名剥 [限定] 标签与（…）尾注。"""
    名单 = []
    for 片 in re.split(r"[/\\]", 文本):
        名 = re.sub(r"\[限定\]|［限定］", "", 片)
        名 = re.sub(r"（[^）]*）|\([^)]*\)", "", 名).strip()
        if 名 and 名 not in 名单:
            名单.append(名)
    return 名单


def _匹配关键词(标题: str, 规则表: list) -> int | None:
    for 关键词列表, 类型 in 规则表:
        for kw in 关键词列表:
            if kw in 标题:
                return 类型
    return None


def 分类章节(标题: str) -> int:
    if 是寻访赠送板块(标题) or "登录活动" in 标题:
        return 2
    t = _匹配关键词(标题, 章节类型规则)
    return t if t is not None else 1


# ---------- 时间 ----------

def _择年(月: int, 日: int, 基准: datetime) -> int:
    """只有"X月X日"没有年份时，选**离基准时间最近**的那一年。

    基准必须是**这条子活动所属活动的时间窗**（`API转活动列表` 手里的 ask 时间），
    不能是"今天"——公告页保留多年，用今天当基准会把 2025 年的老公告算成今年，
    生成一批"未来活动"（2026-09-14 实测：`揭幕者们2025` 被算成 2026-11-25，长期留在库里）。
    """
    候选 = [基准.year - 1, 基准.year, 基准.year + 1]

    def 距离(年: int) -> float:
        try:
            return abs((datetime(年, 月, 日) - 基准).total_seconds())
        except ValueError:          # 2月29日之类
            return float("inf")

    return min(候选, key=距离)


def 解析时间(文本: str, 参考: datetime | None = None) -> tuple[str, str] | None:
    """`X月X日 H:MM - X月X日 H:MM`（年份可写可不写）→ (开始, 结束)

    年份规则：
    - 文本里写了年份（跨年公告常见，如 `2026年01月02日`）→ 用它；
    - 没写 → 取离 `参考` 最近的那一年，`参考` 传**父活动的时间窗**；
    - 结束早于开始时（12 月 → 次年 1 月）→ 结束年 +1。
    """
    短窗 = re.search(r'(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})\s*[-～~]\s*(\d{1,2}):(\d{2})(?!\d)', 文本)
    if 短窗:
        年, 月, 日, 时, 分, 止时, 止分 = 短窗.groups()
        基准 = 参考 or datetime.now()
        开始年 = int(年) if 年 else _择年(int(月), int(日), 基准)
        开始 = datetime(开始年, int(月), int(日), int(时), int(分))
        if int(止时) == 24 and int(止分) == 0:
            结束 = 开始.replace(hour=0, minute=0) + timedelta(days=1)
        else:
            结束 = 开始.replace(hour=int(止时), minute=int(止分))
        if 结束 <= 开始:
            return None
        return 开始.strftime('%Y-%m-%d %H:%M:%S'), 结束.strftime('%Y-%m-%d %H:%M:%S')
    m = 关卡时间正则.search(文本) or 时间正则.search(文本)
    if not m:
        return None
    起年文本, 起月, 起日, 起时, 起分 = m.group(1, 2, 3, 4, 5)
    止年文本, 止月, 止日, 止时, 止分 = m.group(6, 7, 8, 9, 10)
    基准 = 参考 or datetime.now()
    开始年 = int(起年文本) if 起年文本 else _择年(int(起月), int(起日), 基准)
    开始 = datetime(开始年, int(起月), int(起日), int(起时), int(起分))
    结束年 = int(止年文本) if 止年文本 else _择年(int(止月), int(止日), 开始)
    结束 = datetime(结束年, int(止月), int(止日), int(止时), int(止分))
    if 结束 < 开始 and not 止年文本:
        结束 = 结束.replace(year=结束.year + 1)
    return (
        开始.strftime("%Y-%m-%d %H:%M:%S"),
        结束.strftime("%Y-%m-%d %H:%M:%S"),
    )


# ---------- 名称处理 ----------


def 解析开始时刻(文本: str, 参考: datetime | None = None) -> str | None:
    """`X月X日 H:MM`（单点、后面不是区间）→ 开始时间；区间或没写时刻返回 None。

    长期玩法（剿灭/卫戍协议等）公告常只写"活动开启时间：11月08日 16:00（补注）"，
    没有结束——这不是"解析失败"，而是"只有开始"。括号补注允许跟在时刻后面。
    """
    m = re.search(
        r'(?:(\d{4})\s*年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})(?!\d)(?!\s*[-～~])', 文本)
    if not m:
        return None
    年, 月, 日, 时, 分 = m.groups()
    基准 = 参考 or datetime.now()
    开始年 = int(年) if 年 else _择年(int(月), int(日), 基准)
    try:
        return datetime(开始年, int(月), int(日), int(时), int(分)).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def _是独立活动(标题: str, 父名: str) -> bool:
    if 父名 in 标题:
        return False
    子关键词 = ["活动关卡", "SideStory", "组合包", "礼包", "寻访", "签到", "采购"]
    return not any(kw in 标题 for kw in 子关键词)


_名称括号 = {"「": "」", "【": "】", "“": "”", '"': '"', "『": "』"}


def _标题结构(标题: str) -> tuple[list[str], list[int]]:
    """返回外层成对括号内容与括号外逗号位置；嵌套名称保持完整。"""
    栈: list[str] = []
    起 = 0
    名们 = []
    逗号们 = []
    for i, 字 in enumerate(标题):
        if 栈 and 字 == 栈[-1]:
            栈.pop()
            if not 栈:
                名们.append(标题[起 + 1:i].strip())
        elif 字 in _名称括号:
            if not 栈:
                起 = i
            栈.append(_名称括号[字])
        elif not 栈 and 字 in "，,":
            逗号们.append(i)
    return [名 for 名 in 名们 if 名], 逗号们


def _标题后段(标题: str) -> str:
    _, 逗号们 = _标题结构(标题)
    return 标题[逗号们[-1] + 1:].strip() if 逗号们 else ""


def _资源全天名(标题: str) -> str | None:
    if "资源收集" in 标题 and "全天开放" in 标题:
        return "资源收集全天开放"
    return None


def SideStory本名(标题: str) -> str | None:
    """仅识别明确 SideStory + 成对名称；不取前面的系列名，也不猜裸标题。"""
    标识 = re.search(r"(?<![A-Za-z])SideStory\s*", 标题)
    if not 标识:
        return None
    后文 = 标题[标识.end():]
    if not 后文 or 后文[0] not in _名称括号:
        return None
    名们, _ = _标题结构(后文)
    return f"SideStory「{名们[0]}」" if 名们 else None


def _独立活动名(标题: str) -> str:
    if 名 := _资源全天名(标题):
        return 名
    名们, _ = _标题结构(标题)
    for 名 in 名们:
        if "锦标" in 名 or "活动" in 名:
            return 名
    return 名们[0] if 名们 else 标题.strip()


def _长期命名(标题: str) -> tuple[str, str] | None:
    """长期板块 → (显示名, 活动本名)。

    显示名 = 官方名 + 「对象名」（官方写法）。对象名两种来源：
    - 标题里用【】包的（剿灭：`剿灭作战关卡【默祷圣祠】追加`）；
    - 官方赛季写法用「」包的（卫戍协议：`「卫戍协议·规程·序列I」活动开启`）——
      取「」里以官方名开头的那一段，去掉前缀与分隔符，保留原文序列号（罗马数字）。

    活动本名 = 官方名·去掉序列号后的主题（`卫戍协议·规程`），供显示层把
    同一主题的多个序列按时间截断。
    """
    前缀 = 长期活动.前缀名(标题)
    if not 前缀:
        return None
    if m := re.search(r"【([^】]+)】", 标题):
        对象 = m.group(1)
    else:
        对象 = next((w[len(前缀):].lstrip("·:：- 　")
                     for w in re.findall(r"「([^」]+)」", 标题)
                     if w.startswith(前缀)), "")
        if not 对象:
            return None
    基 = re.sub(r"[·・]\s*序列\s*(?:[IVX]+|\d+)$", "", 对象).strip() or 对象
    return f"{前缀}「{对象}」", f"{前缀}·{基}"


def _长期任务名(标题: str) -> str | None:
    """兼容旧调用：只取显示名。"""
    命名 = _长期命名(标题)
    return 命名[0] if 命名 else None


# 保全轮换不在任何公开来源（活动公告/SMW/保全派驻页均无日期），列为待办项：
# 解析链路保持就位，将来官方一旦公告，这里会以 warning 提醒
def 提醒保全(条目们: list[dict]) -> None:
    for e in 条目们:
        if e["名称"].startswith("保全派驻「"):
            logger.warning(
                "🔔 检测到保全派驻轮换公告：%s（%s ~ %s）——保全此前无公开来源，首次解析到",
                e["名称"], e["开始时间"], e["结束时间"],
            )


# ---------- 活动页本体：{{活动信息}} 模板 ----------

def 解析活动信息(wikitext: str) -> dict[str, str]:
    """活动页 wikitext → `{{活动信息}}` 模板的字段表（要的是 `公告=` 指认）。无模板 → {}"""
    m = re.search(r"\{\{活动信息(.*?)\}\}", wikitext, re.S)
    if not m:
        return {}
    return {
        km.group(1).strip(): km.group(2).strip()
        for 行 in m.group(1).splitlines()
        if (km := re.match(r"\|\s*([^=|]+?)\s*=\s*(.*)", 行))
    }


def 公告定位(公告值: str) -> tuple[str, str]:
    """`公告=` 的值 → (公告页名, 锚点)。锚点可能是具体板块或 Part.1 大节；
    只有与板块标题唯一对应时才能直接认领，大节不能冒充活动身份。"""
    页名, _, 锚点 = 公告值.partition("#")
    return 页名.strip(), 锚点.strip()


def 引用公告定位(wikitext: str) -> tuple[str, str] | None:
    """活动页没有 `公告=` 时，从唯一的 #lsth/#section-h 公告引用取定位。

    只认字面量 `X/活动公告|标题`，不求值嵌套模板、不猜多个不同引用。
    注释和 nowiki 中的示例不参与定位；重复的同一引用不算歧义。
    """
    文本 = re.sub(r"<!--.*?-->|<nowiki\b[^>]*>.*?</nowiki\s*>", "", wikitext,
                  flags=re.S | re.I)
    候选 = {
        (m.group(1).strip(), m.group(2).strip())
        for m in re.finditer(
            r"\{\{\s*#(?:lsth|section-h)\s*:\s*([^{}|]+)\|([^{}|]+)\}\}",
            文本, re.I)
        if m.group(1).strip().endswith("/活动公告") and m.group(2).strip()
    }
    if len(候选) == 1:
        return next(iter(候选))
    if len(候选) > 1:
        logger.warning("活动页有多个不同公告板块引用，不猜测定位：%s", sorted(候选))
    return None


def 页父名(页名: str) -> str:
    """公告页名 → 所属活动名（`X/活动公告` → `X`；其他写法原样返回）"""
    return 页名[: -len("/活动公告")] if 页名.endswith("/活动公告") else 页名


# ---------- 公告解析：板块表 ----------

@dataclass(frozen=True)
class 时间段:
    标签: str
    角色: str                         # 总窗口 / 关卡阶段 / 阶段 / 兑换期 / 子窗口
    原文: str
    窗口: tuple[str, str] | None


@dataclass
class 板块:
    """公告里的一个分区。命名与认领策略不在这一层（见 解析_API活动）。"""

    标题: str
    窗口: tuple[str, str] | None          # 明示总窗口，或完整关卡阶段推导；不完整时为空
    关卡各段: list[tuple[str, str]]       # 兼容字段，仅完整关卡组；招募等阶段不在此处
    类型: int
    是主体: bool                          # 主活动板块（SideStory/活动关卡）：◆ 段要另出一条 关卡
    干员们: list[str] = field(default_factory=list)
    """寻访池板块的六星名单（`寻访名单正则`）。抽不出来时为空——板块条目 据此不生成（宁缺毋重）。"""
    时间段们: list[时间段] = field(default_factory=list)
    解析问题: list[str] = field(default_factory=list)
    窗口来源: str = ""                  # 明示 / 完整关卡阶段；不是 ask 补时
    局部识别: 局部识别结果 | None = field(default=None, repr=False, compare=False)
    """原文局部记录和诊断；主体/流程生成读取此字段，旧窗口仍兼容保留。

    None表示手工构造的兼容板块尚未执行识别，不等于公告没有时间。
    """
    静默: bool = False
    """页面所属活动已结束：解析诊断只写 debug（初始化回溯半年时避免刷屏，
    消息端的“部分活动未更新”也按同一口径过滤）。"""


def _清理行(行: str) -> str:
    """剥掉加粗/斜体和 HTML 标签；模板含日期时剥语法留内容，否则整块删除"""
    行 = re.sub(r"'+", "", 行)
    行 = re.sub(r"<[^>]+>", "", 行)
    行 = unescape(行)

    def _处理模板(m: re.Match) -> str:
        模板 = m.group(0)
        if "月" not in 模板:
            return ""
        return re.sub(r"\{\{[^|{}]*\|?", "", 模板).replace("}}", "")

    return re.sub(r"\{\{[^{}]*\}\}", _处理模板, 行).strip()


def _板块时间(正文: str, 是主体: bool, 参考: datetime | None) -> tuple[
        tuple[str, str] | None, list[时间段], list[str], str]:
    段们: list[时间段] = []
    问题: list[str] = []
    待阶段: str | None = None
    对象 = ""

    def 收(标签: str, 角色: str, 原文: str) -> None:
        try:
            窗 = 解析时间(原文, 参考)
        except (ValueError, OverflowError):
            窗 = None
        段们.append(时间段(标签, 角色, 原文, 窗))
        if 窗 is None:
            问题.append(f"{标签}时间未精确解析：{原文}")

    def 缺阶段() -> None:
        nonlocal 待阶段
        if 待阶段 is not None:
            收(待阶段, "关卡阶段" if 是主体 else "阶段", "")
            待阶段 = None

    for 原行 in 正文.splitlines():
        行 = _清理行(原行)
        if not 行:
            continue
        # ◆标签：日期同一行，或下一行用开放时间写出。
        标 = re.match(r"^◆\s*(.+?)[：:]\s*(.*)$", 行)
        段标题 = re.fullmatch(r"◆\s*[<〈]?\s*(第[一二三四五六七八九十\d]+段|预选期|招募期)\s*[>〉]?", 行)
        if 标 and ((re.search(r"\d{1,2}月\d{1,2}日", 标.group(2))
                     and re.search(r"[～~\-]", 标.group(2)))
                    or "关卡" in 标.group(1) or 标.group(1) in ("预选期", "招募期")):
            缺阶段()
            对象 = ""
            标签, 文本 = 标.group(1).strip(), 标.group(2).strip()
            if 文本:
                收(标签, "关卡阶段" if 是主体 else "阶段", 行)
            else:
                待阶段 = 标签
            continue
        if 段标题:
            缺阶段()
            待阶段 = 段标题.group(1)
            对象 = ""
            continue
        # 正文内的奖励台/兑换台标题是子对象边界，不沿用上一阶段标签。
        if re.fullmatch(r"【[^】]+】", 行):
            缺阶段()
            对象 = 行[1:-1]
            continue
        时间行 = re.search(r"(活动时间|关卡开放时间|开放时间|开启时间|售卖时间|兑换时间)[：:]", 行)
        if not 时间行:
            continue
        标签 = 时间行.group(1)
        if 行.startswith("【") and (对象标 := re.match(r"【([^】]+)】", 行)):
            缺阶段()
            对象 = 对象标.group(1)
        if 待阶段 is not None and 标签 in ("开放时间", "关卡开放时间"):
            收(待阶段, "关卡阶段" if 是主体 else "阶段", 行)
            待阶段 = None
            continue
        缺阶段()
        if 对象 or 标签 == "兑换时间" or re.search(r'(?:交换所|兑换处|兑换所).*?(?:开启|开放)时间[：:]', 行):
            # 兑换说明可能在下一行；结束遍历后再确认该对象是否为兑换台。
            交换所 = re.search(r'([^：:]*?(?:交换所|兑换处|兑换所)).*?(?:开启|开放)时间[：:]', 行)
            对象名 = 对象 or (交换所.group(1).strip() if 交换所 else '兑换')
            收(对象名, "兑换期" if 标签 == "兑换时间" or 交换所 else "子窗口", 行)
        else:
            收(标签, "总窗口", 行)

    缺阶段()
    # 同一子对象后的兑换说明明确了角色；不根据具体活动名称建词表。
    清理正文 = "\n".join(_清理行(行) for 行 in 正文.splitlines())
    for i, 段 in enumerate(段们):
        if 段.角色 == "子窗口":
            块 = re.search(rf"【{re.escape(段.标签)}】\s*\n(.*?)(?=\n【|\n◆|\Z)", 清理正文, re.S)
            if 块 and "兑换说明" in 块.group(1):
                段们[i] = 时间段(段.标签, "兑换期", 段.原文, 段.窗口)

    总们 = [段 for 段 in 段们 if 段.角色 == "总窗口"]
    if 总们:
        窗们 = {段.窗口 for 段 in 总们}
        if len(窗们) == 1 and None not in 窗们:
            return 总们[0].窗口, 段们, 问题, "明示"
        if len(窗们) > 1:
            问题.append("多个总窗口不同或不完整，不猜测活动范围")
        return None, 段们, 问题, ""
    阶段们 = [段 for 段 in 段们 if 段.角色 == "关卡阶段"]
    序号 = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
            "七": 7, "八": 8, "九": 9, "十": 10}
    编号们 = []
    for 段 in 阶段们:
        if 标 := re.fullmatch(r"第([一二三四五六七八九十]|\d+)段", 段.标签):
            值 = 标.group(1)
            编号们.append(int(值) if 值.isdigit() else 序号[值])
    连续 = not 编号们 or sorted(编号们) == list(range(1, len(编号们) + 1))
    if not 连续:
        问题.append("关卡阶段序号不完整，不推导总窗口")
    if 是主体 and 阶段们 and 连续 and all(段.窗口 for 段 in 阶段们):
        窗 = (min(段.窗口[0] for 段 in 阶段们), max(段.窗口[1] for 段 in 阶段们))
        return 窗, 段们, 问题, "完整关卡阶段"
    return None, 段们, 问题, ""


def 抽板块(wikitext: str, 参考: datetime | None = None, *, 静默: bool = False) -> list[板块]:
    """公告 wikitext → 板块列表。

    跳过 时装/家具/干员登场/凭证 等板块（条目另有来源，见 跳过关键词）；
    **寻访池板块例外**：不跳过、改抽六星名单（`是寻访池板块`），交给 `板块条目`
    生成与 卡池一览 同键的池条目（登记前的预告源）。
    `参考` = 父活动时间窗，用于给"只写 X月X日"的日期定年份（见 `解析时间`）。
    `静默` = 页面所属活动已结束：诊断降为 debug，避免初始化回溯时刷屏。
    """
    匹配们 = list(标题正则.finditer(wikitext))
    if not 匹配们:
        return []

    结果 = []
    for i, m in enumerate(匹配们):
        标题 = m.group(2).strip()
        if not 标题 or 标题 == "目录":
            continue

        寻访池 = 是寻访池板块(标题)
        if not 寻访池 and any(kw in 标题 for kw in 跳过关键词):
            continue

        正文终点 = 匹配们[i + 1].start() if i + 1 < len(匹配们) else len(wikitext)
        正文 = wikitext[m.end():正文终点]
        是主体 = "活动关卡" in 标题 or "SideStory" in 标题
        活动时间, 时间段们, 问题, 来源 = _板块时间(正文, 是主体, 参考)
        if 分类章节(标题) == -1:
            售卖段 = [段 for 段 in 时间段们 if 段.标签 == "售卖时间"]
            if 售卖段 and all(段.窗口 for 段 in 售卖段):
                活动时间 = (min(段.窗口[0] for 段 in 售卖段), max(段.窗口[1] for 段 in 售卖段))
                来源 = "完整售卖期合并"
                问题 = [描述 for 描述 in 问题 if 描述 != "多个总窗口不同或不完整，不猜测活动范围"]
        关卡阶段 = [段 for 段 in 时间段们 if 段.角色 == "关卡阶段"]
        # 不完整关卡组不能被兼容接口缩成后半段的范围。
        关卡各段 = ([段.窗口 for 段 in 关卡阶段]
                    if all(段.窗口 for 段 in 关卡阶段)
                    and "关卡阶段序号不完整，不推导总窗口" not in 问题 else [])
        干员们 = []
        if 寻访池 and (名单 := 寻访名单正则.search(正文)):
            干员们 = _抽干员名单(名单.group(1))
        if not 时间段们:
            continue
        # 对照识别保留深层子章节；旧正文切法仍保持不变，避免改变条目输出。
        # 单独读取真实层级：旧标题正则最高四级，不能用于新局部范围的层级判断。
        局部标题们 = re.finditer(r"^(={1,6})([^=\n].*?)\1[ \t]*$", wikitext[m.end():], re.M)
        当前层级 = len(re.match(r"=+", wikitext[m.start():]).group())
        局部终点 = next((m.end() + 后.start() for 后 in 局部标题们
                         if len(后.group(1)) <= 当前层级), len(wikitext))
        局部正文 = wikitext[m.end():局部终点]
        局部结果 = 识别局部记录(
            局部正文, 参考.year if 参考 is not None else None,
            起始行=wikitext.count("\n", 0, m.end()) + 1,
        )
        区块类型 = 0 if 寻访池 else 分类章节(标题)
        if 区块类型 == 长期活动.类型值 and 活动时间 is None:
            # 长期玩法常只写开启时刻（赛季化常驻没有结束）：这不是解析失败，
            # 而是"只有开始"。结束留空，由认领层用 API 窗口占位（2026-10-31 卫戍协议）。
            开始 = 解析开始时刻(正文, 参考)
            if 开始:
                活动时间 = (开始, "")
                来源 = "仅明示开始"
                问题 = [描述 for 描述 in 问题 if not 描述.startswith("开启时间时间未精确解析")]
        输出 = logger.debug if 静默 else logger.warning
        for 描述 in 问题:
            输出("公告板块「%s」：%s", 标题, 描述)
        结果.append(板块(
            标题=标题, 窗口=活动时间, 关卡各段=关卡各段,
            类型=区块类型, 是主体=是主体,
            干员们=干员们, 时间段们=时间段们, 解析问题=问题, 窗口来源=来源,
            局部识别=局部结果, 静默=静默,
        ))
    return 结果


def 关卡条目(b: 板块, 父名: str) -> dict | None:
    """主体板块的 ◆ 关卡段 → 一条 `父名 关卡` 条目（跨段取最早开始/最晚结束）"""
    if not (b.关卡各段 and b.是主体) or b.窗口来源 == "完整关卡阶段":
        return None
    return {
        "名称": f"{父名} 关卡",
        "开始时间": min(段[0] for 段 in b.关卡各段),
        "结束时间": max(段[1] for 段 in b.关卡各段),
        "类型": 1,
        "_parent": 父名,
    }


def 签到名(标题: str) -> str:
    """签到板块的具体名：标题 `…，前瞻签到活动开启` 取逗号后段、去掉"活动开启"尾巴。

    庆典系列一份公告有**三个**签到板块（前瞻/限时/补给，感谢庆典 2024-2026 三届
    同款），此前统一叫 `父名 签到`——三条同名在落盘时按身份键互相覆盖、只剩最后
    一条（2026-10-29 实测：前瞻/限时丢失、补给顶着泛名）。无逗号的单签到标题
    （锦枫映月签到活动开启）维持"签到"，周年系列（「七周年庆典」，签到活动开启）
    抽出"签到"也与现状一致。
    """
    段 = _标题后段(标题)
    if not 段:
        return "签到"
    for 尾 in ("活动开启", "开启"):
        if 段.endswith(尾):
            段 = 段[: -len(尾)]
            break
    return 段 if "签到" in 段 else "签到"


def 具体段名(标题: str, 父名: str) -> str:
    """共享公告标题 `状语，+ 宾语 + 动词` 的具体段名（类型 1 独立板块的取名）。

    感谢庆典/周年/夏活这类共享公告里，登录奖励、许愿墙、主题复刻等板块的
    标题都是 `2026「感谢庆典」，特别登录活动开启` 形态——第一个「」是父系列名，
    全部撞成一条"感谢庆典"互相覆盖（2026-10-29 实测：特别登录/特别招募/许愿墙
    三条真实福利被主题场景复刻顶着系列名顶掉）。
    有括号抽括号内容（【塞梦珂城许愿墙】活动开启 → 塞梦珂城许愿墙）；
    无括号只剥"开启"尾巴、保留"XX活动"整体（特别活动开启 → 特别活动——
    剥到"活动"会把"特别活动"切残，不做词法切割）；再剥段首重复的系列词
    （父名去年份：感谢庆典特别招募活动 → 特别招募活动）。
    无逗号的标题不属于共享公告形态，返回空串、调用方走 `_独立活动名` 老路。
    """
    段 = _标题后段(标题)
    if not 段:
        return ""
    括号们, _ = _标题结构(段)
    if 资源名 := _资源全天名(段):
        名 = 资源名
    elif 括号们:
        名 = 括号们[-1]
    else:
        名 = 段[: -len("开启")].strip() if 段.endswith("开启") else 段
    系列 = 父名.rstrip("0123456789")
    if 系列 and 名.startswith(系列):
        名 = 名[len(系列):]
    return 名.strip()


def _池名(标题: str) -> str | None:
    """寻访池板块标题 → 池名（不带期号）。

    公告标题是"状语，+ 宾语（池名）+ 开启"的句式（2026-10-29 考察全年
    31 个池板块定下）：池名总是**最后一个括号段**，在前面的
    `2026「感谢庆典」，`/`【限定寻访·庆典】系列，` 是父系列名；
    池型词（中坚甄选/定向甄选/联合行动）不带括号——状语也可能不带括号
    （`辞旧迎新，中坚甄选开启`），只能查表、优先于括号段。
    认不出返回 None（宁缺毋重，`板块条目` 不生成）。"""
    m = re.search(r"(中坚甄选|定向甄选|联合行动)", 标题)
    if m:
        return m.group(1)
    段们, _ = _标题结构(标题)
    return 段们[-1] if 段们 else None


def 局部时间条目(b: 板块, 父名: str, 显示名: str | None = None,
             类型: int | None = None) -> list[dict] | None:
    """新识别的统一生成路径；None仅表示普通/兼容板块未切换。

    []表示此板块已适用但时间不可靠，调用者不得回退旧窗口。
    名称/类型来自事件认领或既有命名，时间选择不负责持久身份。
    """
    if b.局部识别 is None:
        return None
    选用 = 选用公告时间(b.局部识别, b.是主体)
    if not 选用.适用:
        return None
    for 原因 in 选用.原因:
        输出日志 = (logger.debug if b.静默 or 选用.选项 and "不完整" not in 原因
                    else logger.warning)
        输出日志("公告板块「%s」时间选用：%s", b.标题, 原因)
    if 显示名 is not None:
        名称 = 显示名
    elif b.是主体:
        名称 = SideStory本名(b.标题) or 父名
    elif 段名 := 具体段名(b.标题, 父名):
        名称 = f"{父名} {段名}"
    elif _是独立活动(b.标题, 父名):
        名称 = _独立活动名(b.标题)
    else:
        名称 = f"{父名} {_独立活动名(b.标题)}"
    选项 = list(选用.选项)
    if SideStory本名(b.标题) and 选项:
        from .公告时间选用 import 时间选项
        商店们 = [r for r in b.局部识别.局部记录 if r.角色 == '兑换开放']
        if 商店们 and all(r.窗口 and r.时间精度 == '精确' and r.角色状态 == '已确认' and r.对象 for r in 商店们):
            # 同一对象重复声明同窗可合并；多个不同商店不合成一个虚构窗口。
            唯一 = {(r.对象, r.窗口): r for r in 商店们}
            if len(唯一) == 1:
                r = next(iter(唯一.values()))
                选项.append(时间选项('·商店', r.窗口, '公告明示商店兑换窗口', r.证据, '兑换开放', r.对象, r.标签))
    return [{"名称": 名称 + 项.后缀, "开始时间": 项.窗口[0],
             "结束时间": 项.窗口[1], "类型": b.类型 if 类型 is None else 类型,
             "_parent": 父名, "_局部身份依据": 局部身份依据(项.角色, 项.对象, 项.原标签),
             "_原角色": 项.角色, "_原对象": 项.对象, "_原标签": 项.原标签,
             "_活动本名": 名称,
             "_阶段序号": sum(x.角色 == '关卡开放' for x in 选用.选项[:i + 1]) if 项.角色 == '关卡开放' else 0}
            for i, 项 in enumerate(选项)]


def 招募阶段条目(b: 板块, 父名: str, 显示名: str | None = None) -> list[dict] | None:
    """只拆明示预选/招募的特别招募；不推广到所有◆阶段。

    已识别但不完整时返回空列表，阻止总览冒充可领取窗口；未识别返回None。
    """
    if "特别招募" not in b.标题:
        return None
    阶段 = [段 for 段 in b.时间段们 if 段.角色 == "阶段"]
    if not 阶段:
        return None
    if len(阶段) != 2 or {段.标签 for 段 in 阶段} != {"预选期", "招募期"} or not all(段.窗口 for 段 in 阶段):
        (logger.debug if b.静默 else logger.warning)(
            "特别招募阶段不完整，不生成误导性总览：%s", b.标题)
        return []
    名称 = 显示名 or f"{父名} {具体段名(b.标题, 父名) or _独立活动名(b.标题)}"
    return [{"名称": f"{名称}·{'预选' if 段.标签 == '预选期' else '招募'}",
             "开始时间": 段.窗口[0], "结束时间": 段.窗口[1], "类型": b.类型,
             "_parent": 父名} for 段 in 阶段]


def 板块条目(b: 板块, 父名: str) -> list[dict]:
    """新主体/流程优先按局部记录生成，普通与兼容板块沿既有命名路径。"""
    新条目 = 局部时间条目(b, 父名)
    if 新条目 is not None:
        return 新条目
    结果 = []
    if 阶段条 := 招募阶段条目(b, 父名):
        return 阶段条
    if 阶段条 == []:
        return []

    if b.类型 == 0:
        # 寻访池板块 → 卡池条目：名字与 卡池一览 同构（`【寻访】/【中坚池】` + 池名 + 干员名单），
        # 但**不带期号**——合并认的键是"· "后的干员名单（`汇总_活动._身份键` 排序归一），
        # 期号在不在都能与将来卡池一览登记的同一条**无缝换岗**（同键覆盖，不会两条并存）。
        # 名单或池名抽不出来就不生成：宁缺一条，不要公告版与卡池版对不齐的双份。
        if b.窗口 and b.干员们 and (池名 := _池名(b.标题)):
            前缀 = "【中坚池】" if "中坚" in 池名 else "【寻访】"
            结果.append({
                "名称": f"{前缀}{池名} · {' / '.join(b.干员们)}",
                "开始时间": b.窗口[0],
                "结束时间": b.窗口[1],
                "类型": 0,
                "子类型": "甄选" if "甄选" in 池名 else "限时",
                "_parent": 父名,
            })
        else:
            logger.debug("寻访池板块「%s」缺名单/窗口/池名，不生成（宁缺毋重）", b.标题)
        return 结果

    if b.类型 == 2:
        if b.窗口:
            if "签到" in b.标题:
                段 = 签到名(b.标题)
            else:
                段 = 具体段名(b.标题, 父名) or _独立活动名(b.标题)
            return [{"名称": f"{父名} {段}", "开始时间": b.窗口[0],
                     "结束时间": b.窗口[1], "类型": 2, "_parent": 父名}]
        return 结果

    if _是独立活动(b.标题, 父名):
        if b.窗口:
            条目 = {"名称": None, "开始时间": b.窗口[0], "结束时间": b.窗口[1],
                    "类型": b.类型, "_parent": 父名}
            if b.类型 == 长期活动.类型值:
                命名 = _长期命名(b.标题)
                if not 命名:
                    logger.debug("长期板块「%s」抽不出对象名，不生成（宁缺毋重）", b.标题)
                    return 结果
                条目["名称"], 本名 = 命名
                if not b.窗口[1]:
                    # 只有开启时刻（赛季常驻玩法）：结束空着，认领层用 API 窗口占位；
                    # 时间角色标记成"长期开放"，提醒/绘制都不会把它当可信结束。
                    条目["时间角色"] = "长期开放"
                    条目["活动本名"] = 本名
            elif 段 := 具体段名(b.标题, 父名):
                条目["名称"] = f"{父名} {段}"
            else:
                条目["名称"] = _独立活动名(b.标题)
            结果.append(条目)
        return 结果

    if b.窗口:
        if b.是主体:
            名称 = 父名
        elif b.类型 == -1:
            名称 = f"{父名} {'礼包' if '礼包' in b.标题 else '组合包'}"
        else:
            名称 = f"{父名} {b.标题}"
            for suffix in ("限时开放", "限时售卖", "限时上架", "限时开启"):
                if 名称.endswith(suffix):
                    名称 = 名称[:-len(suffix)]
                    break

        结果.append({
            "名称": 名称,
            "开始时间": b.窗口[0],
            "结束时间": b.窗口[1],
            "类型": b.类型,
            "_parent": 父名,
        })

    if 关卡 := 关卡条目(b, 父名):
        结果.append(关卡)
    return 结果
