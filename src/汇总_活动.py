"""汇总层 — 合并商店、去重排序、活动数据 CSV 增量存储"""

from __future__ import annotations

import csv
import io
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import 长期活动
from .数据保护 import 校验写回
from .日志 import logger
from .公告身份 import 公告条目批次
from .隔离来源 import 复制批次元数据, 来源被隔离

# store 里过期超过这个天数的条目自动清理
过期保留天数 = 7


@dataclass(frozen=True)
class 合并差异:
    """这次合并相对 CSV 里**原有内容**的变化（都放显示名，给用户看）。

    为什么由合并来回答：**合并动作本身就天然知道**哪些键是新来的、哪些被覆盖改了、
    哪些因为过了清理线被删掉——不需要事后再拿两份数据对比（用户 2026-09-14 指出的）。

    ⚠️ 刻意没有"不再列出"：抓取可能受网络、可见API组与局部隔离影响，
    "这次没抓到"不证明来源撤回。不自动删除缺失条目；普通记录按来源结束
    过期清理，隔离来源记录保留，不把隔离误报为撤回。
    """

    新增: tuple[str, ...] = field(default_factory=tuple)
    改动: tuple[str, ...] = field(default_factory=tuple)
    过期清理: int = 0
    原有条数: int = 0

    @property
    def 有变化(self) -> bool:
        return bool(self.新增 or self.改动 or self.过期清理)

    @property
    def 首次(self) -> bool:
        """CSV 原本不存在 → 这不是"变化"，是"初次建立"（别报成几千条新增）"""
        return self.原有条数 == 0


# ---------- 商店合并 ----------

def 合并商店(活动列表: list[dict]) -> list[dict]:
    """合并同一父活动下的多条礼包为一条"""
    groups: dict[str, list[dict]] = {}
    for it in 活动列表:
        key = it.get("_parent", "")
        groups.setdefault(key, []).append(it)

    结果 = []
    for 父名, 组 in groups.items():
        礼包 = [i for i in 组 if i["类型"] == -1]
        其他 = [i for i in 组 if i["类型"] != -1]

        if len(礼包) >= 2 and not any(i.get('_运行时身份') for i in 礼包):
            最早 = min(礼包, key=lambda x: x["开始时间"])
            最晚 = max(礼包, key=lambda x: x["结束时间"])
            结果.append({
                "名称": f"{父名} 礼包" if 父名 else "礼包",
                "开始时间": 最早["开始时间"],
                "结束时间": 最晚["结束时间"],
                "类型": -1,
                "_parent": 父名,
                "_来源板块们": tuple(dict.fromkeys(i['_来源板块'] for i in 礼包 if i.get('_来源板块'))),
            })
            if any('待确认' in i.get('_身份状态', '') for i in 礼包):
                结果[-1]['_身份状态'] = '合并来源身份待确认'
            if any(i.get('_身份问题') for i in 礼包):
                结果[-1]['_身份问题'] = '礼包聚合含来源身份问题'
        else:
            结果.extend(礼包)
        结果.extend(其他)
    return 复制批次元数据(活动列表, 结果)


# ---------- 去重排序 ----------

def _提取干员(名称: str) -> str:
    """从卡池名称中提取 · 后面的干员名，用于卡池去重"""
    if " · " in 名称:
        return 名称.split(" · ", 1)[1]
    return ""


def _身份键(名称: str, 类型: int) -> str:
    """合并与去重共用的**身份**键：卡池用干员名，长期剥掉开头的玩法前缀，其余用原始名。

    长期条目的前缀（玩法名）在数据源里换过写法——公告简写、官方名、还有裸名无前缀
    （`长期活动.py` 的"两副面孔"）——拿原始名当键，改名前后的两行就互相覆盖不到，
    会在 CSV 里**永久并存**、越抓越多（2026-09-24 实测：`默祷圣祠`×2、`重启锚点`×2，
    bootstrap 也清不掉——它们 2027 年才结束，永远不过期）。前缀语义归 `长期活动`
    唯一定义管，这里只认"类型 99 的开头玩法段"，不另起一张表。
    `官方名「对象」`是现行写法（2026-10-29 定）；`【官方名】对象`、`「官方名」对象`
    是旧 CSV 的写法（前者是历史数据，后者是 10-29 当天的中间态）——三种都剥出
    裸对象名，新旧行同键、无缝换岗（全量重抓过一次后旧分支可以删）。

    卡池的干员名单**排序后再当键**：公告里的名单顺序与 卡池一览 不总一致
    （中坚甄选14 公告倒序紧凑分隔、一览正序空格分隔，2026-09-27 实测），
    逐字比较会把同一个池认成两条。排序只影响键，展示仍用原文。
    """
    if 类型 == 0:
        干员 = _提取干员(名称)
        if 干员:
            干员们 = [x.strip() for x in 干员.split(" / ")]
            return " / ".join(sorted(干员们))
    if 类型 == 长期活动.类型值:
        m = re.fullmatch(r"[^「」【】]+「([^「」]+)」", 名称)   # 官方名「对象」→ 对象
        if m:
            return m.group(1)
        for 开, 闭 in (("「", "」"), ("【", "】")):            # 「官方名」对象 / 【官方名】对象 → 对象
            if 名称.startswith(开) and 闭 in 名称:
                return 名称.split(闭, 1)[1]
    return 名称


class 身份冲突(ValueError):
    """身份或旧CSV键有歧义；必须在写盘前失败。"""


def 检查身份写回(活动列表: list[dict]) -> None:
    if getattr(活动列表, '身份问题', ()):
        raise 身份冲突('本次公告认领存在争议：' + '；'.join(活动列表.身份问题))
    by_runtime: dict[str, list[dict]] = {}
    by_legacy: dict[str, list[dict]] = {}
    for a in 活动列表:
        if '待确认' in a.get('_身份状态', '') or (
                '_局部身份依据' in a and not a.get('_运行时身份')):
            raise 身份冲突(f"{a['名称']} 的来源/阶段身份待确认，拒绝写回")
        key = a.get('_运行时身份')
        if key:
            by_runtime.setdefault(key, []).append(a)
        by_legacy.setdefault(_身份键(a['名称'], a['类型']), []).append(a)
    for items in by_runtime.values():
        if len(items) > 1:
            raise 身份冲突(f"{items[0]['名称']} 的来源身份重复，不能按日期或序号消除")
    for items in by_legacy.values():
        keys = {a.get('_运行时身份') for a in items}
        if len(keys) > 1 and any(keys):
            raise 身份冲突(f"{items[0]['名称']} 的多个来源落入同一旧CSV键，拒绝覆盖")


def 去重排序(活动列表: list[dict]) -> list[dict]:
    """按身份键+时间去重，按开始时间排序"""
    seen = set()
    去重后 = []
    for a in 活动列表:
        # 登录/签到同样按身份与时间去重；窗口相同不足以证明是同一福利。
        if a.get('_身份状态') or a.get('_来源板块') or '_局部身份依据' in a:
            # 本次生成先保留：同来源重复也不能由去重掩盖身份碰撞。
            去重后.append(a)
            continue
        key = (_身份键(a["名称"], a["类型"]), a["开始时间"], a["结束时间"], a["类型"])
        if key not in seen:
            seen.add(key)
            去重后.append(a)
    去重后.sort(key=lambda e: e["开始时间"])
    return 复制批次元数据(活动列表, 去重后)


# ---------- 增量存储 ----------


def 合并保存CSV(
    新活动列表: list[dict],
    输出路径: str | Path,
    现在时间: str,
    允许大幅清理: bool = False,
    *,
    重建: bool = False,
) -> 合并差异:
    """增量保存：读已有数据 + 新数据覆盖 + 清理过期条目 + 写回；返回本次的**合并差异**

    `重建=True`（初始化 / `cli.py --bootstrap`）：**不读旧文件**，本次输入就是全部内容，
    旧行与旧六列格式一并被新格式覆盖——这就是"重新开始"的语义。
    日常刷新保持默认 `False`（增量合并、未抓到的不删除）。

    store 带"来源"列（条目出自哪个活动公告；卡池和 API 兜底条目为空）。
    来源非空说明该公告解析成功过，主流程据此知道"这组的公告读出过内容"。

    注意 现在时间 不只用于记录，它还推导清理线（`现在时间 - 过期保留天数`），
    因此传错时间会静默丢数据。写回前由 `数据保护.校验写回` 兜一道：
    若本次会把已有数据清空、或清理比例过高，则抛 `数据保护拦截` 且**不写盘**。
    确实需要大清理时显式传 `允许大幅清理=True`。
    """
    from .CSV事务 import CSV写事务
    from .身份存储错误 import 身份存储冲突
    路径 = Path(输出路径).resolve()
    try:
        with CSV写事务(路径) as 原始内容:
            return _按格式保存CSV(新活动列表, 路径, 现在时间, 允许大幅清理, 原始内容,
                              重建=重建)
    except 身份存储冲突 as exc:
        raise 身份冲突(str(exc)) from exc


def _按格式保存CSV(新活动列表, 路径, 现在时间, 允许大幅清理, 原始内容, *, 重建=False):
    有身份输入 = any(a.get('_运行时身份') for a in 新活动列表)
    if 重建:
        # 重建就是要换成新格式：不探测旧表头，旧文件内容一律不参与（由存储层忽略旧行）。
        有身份格式 = True
    elif 路径.exists():
        try:
            with 路径.open(newline='', encoding='utf-8-sig') as f:
                列名 = csv.DictReader(f).fieldnames or []
        except (UnicodeError, csv.Error) as exc:
            raise 身份冲突('CSV编码或解析失败') from exc
        有身份格式 = '身份' in 列名 or '身份状态' in 列名
    else:
        有身份格式 = 有身份输入
    if 有身份格式:
        from .身份CSV存储 import _保存身份CSV, 身份存储冲突 as 身份CSV冲突
        try:
            差异 = _保存身份CSV(新活动列表, 路径, 现在时间,
                            允许大幅清理=允许大幅清理, legacy_key=_身份键, _原始字节=原始内容,
                            重建=重建)
        except 身份CSV冲突 as exc:
            raise 身份冲突(str(exc)) from exc
        return 合并差异(新增=差异.新增, 改动=差异.改动,
                      过期清理=差异.过期清理, 原有条数=差异.原有条数)
    if 有身份输入:
        raise 身份冲突('现有CSV为旧格式：日常刷新不会按名字自动迁移；请管理员发「/方舟日程 初始化」'
                    '（或 cli.py --bootstrap --force）按本次全量扫描结果覆盖重建为新格式')
    return _合并旧CSV内容(新活动列表, 路径, 现在时间, 允许大幅清理, 原始内容)


_旧CSV字段 = ["名称", "开始时间", "结束时间", "类型", "子类型", "来源"]
_日期格式 = "%Y-%m-%d %H:%M:%S"


def _旧日期(值: object, 上下文: str) -> datetime:
    if not isinstance(值, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", 值):
        raise 身份冲突(f"{上下文} 日期格式无效")
    try:
        return datetime.strptime(值, _日期格式)
    except ValueError as exc:
        raise 身份冲突(f"{上下文} 日期无效") from exc


def _校验旧行(row: dict, 上下文: str, *, 来自CSV: bool) -> dict:
    名称 = row.get("名称")
    if not isinstance(名称, str) or not 名称.strip():
        raise 身份冲突(f"{上下文} 名称为空或无效")
    开始 = _旧日期(row.get("开始时间"), 上下文 + "开始时间")
    结束 = _旧日期(row.get("结束时间"), 上下文 + "结束时间")
    if 结束 < 开始:
        raise 身份冲突(f"{上下文} 结束时间早于开始时间")
    类型 = row.get("类型")
    if 来自CSV:
        if not isinstance(类型, str) or not re.fullmatch(r"-?[0-9]+", 类型):
            raise 身份冲突(f"{上下文} 类型无效")
        try:
            类型 = int(类型)
        except ValueError as exc:
            raise 身份冲突(f"{上下文} 类型无效") from exc
    elif type(类型) is not int:
        raise 身份冲突(f"{上下文} 类型必须是整数（不能是bool）")
    子类型 = row.get("子类型", "")
    来源 = row.get("来源", "") if 来自CSV else row.get("_parent", "")
    if not isinstance(子类型, str) or not isinstance(来源, str):
        raise 身份冲突(f"{上下文} 子类型或来源必须是文本")
    return {"名称": 名称, "开始时间": row["开始时间"], "结束时间": row["结束时间"],
            "类型": 类型, "子类型": 子类型.strip() if 来自CSV else 子类型, "来源": 来源}


def _读旧CSV(原始内容: bytes | None) -> tuple[dict[str, dict], int]:
    已有: dict[str, dict] = {}
    if 原始内容 is None:
        return 已有, 0
    try:
        reader = csv.reader(io.StringIO(原始内容.decode("utf-8-sig"), newline=""), strict=True)
        字段 = next(reader, None)
        if (not 字段 or len(set(字段)) != len(字段)
                or not set(_旧CSV字段[:4]).issubset(字段)
                or not set(字段).issubset(_旧CSV字段)):
            raise 身份冲突("旧CSV表头缺必需列、含未知列或重复列")
        物理条数 = 0
        for values in reader:
            物理条数 += 1  # 每个实际CSV记录必须通过校验，不先过滤/去重。
            if len(values) != len(字段):
                raise 身份冲突(f"旧CSV第{reader.line_num}行列数不符")
            row = _校验旧行(dict(zip(字段, values)), f"旧CSV第{reader.line_num}行", 来自CSV=True)
            键 = _身份键(row["名称"], row["类型"])
            if 键 in 已有:
                raise 身份冲突(f"旧CSV身份冲突：{row['名称']} 的旧CSV键有多行，拒绝覆盖")
            已有[键] = row
        return 已有, 物理条数
    except (UnicodeError, csv.Error) as exc:
        raise 身份冲突(f"旧CSV编码或语法无效：{exc}") from exc


def _原子写旧CSV(路径: Path, 内容: bytes, 原始内容: bytes | None) -> None:
    临时路径 = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=路径.parent,
                                         prefix=f".{路径.name}-", suffix=".tmp", delete=False) as f:
            临时路径 = Path(f.name)
            f.write(内容)
            f.flush()
            os.fsync(f.fileno())
        try:
            当前内容 = 路径.read_bytes()
        except FileNotFoundError:
            当前内容 = None
        if 当前内容 != 原始内容:
            raise 身份冲突("旧CSV在合并期间被其他写入修改，拒绝覆盖")
        os.replace(临时路径, 路径)
    finally:
        if 临时路径 is not None:
            临时路径.unlink(missing_ok=True)


def _合并旧CSV(新活动列表: list[dict], 路径: Path, 现在时间: str,
              允许大幅清理: bool = False) -> 合并差异:
    from .CSV事务 import CSV写事务
    from .身份存储错误 import 身份存储冲突
    路径 = 路径.resolve()
    try:
        with CSV写事务(路径) as 原始内容:
            return _合并旧CSV内容(新活动列表, 路径, 现在时间, 允许大幅清理, 原始内容)
    except 身份存储冲突 as exc:
        raise 身份冲突(str(exc)) from exc


def _合并旧CSV内容(新活动列表: list[dict], 路径: Path, 现在时间: str,
                允许大幅清理: bool, 原始内容: bytes | None) -> 合并差异:
    已有, 原有条数 = _读旧CSV(原始内容)
    清理线 = (_旧日期(现在时间, "现在时间") - timedelta(days=过期保留天数)).strftime(_日期格式)
    保护键 = {k for k, row in 已有.items() if 来源被隔离(row, 新活动列表)}
    新行: dict[str, dict] = {}
    接受输入 = []
    for i, a in enumerate(新活动列表, 1):
        row = _校验旧行(a, f"新活动第{i}行", 来自CSV=False)
        键 = _身份键(row["名称"], row["类型"])
        if 来源被隔离(a, 新活动列表) or 来源被隔离(row, 新活动列表) or 键 in 保护键:
            # 严格字段验证已完成；隔离来源无权覆盖原记录。
            continue
        接受输入.append(a)
        if 键 in 新行 and 新行[键] != row:
            raise 身份冲突(f"新活动身份冲突：{row['名称']} 的旧CSV键有不同内容，拒绝覆盖")
        新行[键] = row  # 完全相等可去重，任何保存字段差异都拒绝。
    检查身份写回(复制批次元数据(新活动列表, 接受输入))
    原有快照 = {k: (r["名称"], r["开始时间"], r["结束时间"], r["类型"]) for k, r in 已有.items()}
    本次 = {k: (r["名称"], r["开始时间"], r["结束时间"], r["类型"]) for k, r in 新行.items()}
    已有.update(新行)

    所有 = [r for k, r in 已有.items() if r["结束时间"] >= 清理线 or k in 保护键]
    删了 = len(已有) - len(所有)
    if 删了:
        logger.debug("  清理过期条目 %d 条（结束时间早于 %s）", 删了, 清理线)

    # —— 差异：这次抓取相对原有内容改了什么 ——
    # 只算**能留下来**的行：抓取源里总会带回一堆早已结束的条目（卡池一览尤其多），
    # 它们进来就被清理线删掉，不该每天在日差里刷一遍（实测未过滤时每天 54 条"新增"）。
    存活键 = {k for k, r in 已有.items() if r["结束时间"] >= 清理线 or k in 保护键}
    新增 = tuple(v[0] for k, v in 本次.items() if k in 存活键 and k not in 原有快照)
    改动 = tuple(v[0] for k, v in 本次.items()
                if k in 存活键 and k in 原有快照 and v != 原有快照[k])
    # `过期清理` = **原本就在 store 里、这次没留下来**的条数（含"新时间已经过期"那种）。
    # 不数那些抓取源每天都会带回、进来就被清理线删掉的条目（卡池一览尤其多）——
    # 它们从没进过 store，每天报一次"清理了 53 条"纯属噪音。
    清理了原有的 = sum(1 for k in 原有快照 if k not in 存活键)
    if 原有条数 == 0:
        # 首次建立没有"原有内容"可比：不该报成"新增了 300 条活动"（`首次` 标记已经说明一切）
        新增 = 改动 = ()

    if not 允许大幅清理:
        校验写回(原有条数, len(所有))
    elif 原有条数 and len(所有) * 2 < 原有条数:
        logger.warning(
            "  大幅清理已放行：%d 条 → %d 条（调用方显式传了 允许大幅清理=True）",
            原有条数, len(所有),
        )

    所有.sort(key=lambda e: e["开始时间"])
    缓冲 = io.StringIO(newline="")
    writer = csv.DictWriter(缓冲, fieldnames=_旧CSV字段)
    writer.writeheader()
    writer.writerows(所有)
    _原子写旧CSV(路径, 缓冲.getvalue().encode("utf-8-sig"), 原始内容)

    差异 = 合并差异(新增=新增, 改动=改动, 过期清理=清理了原有的, 原有条数=原有条数)
    if 差异.有变化:
        logger.debug("  本次合并：新增 %d / 改动 %d / 过期清理 %d",
                    len(新增), len(改动), 清理了原有的)
    return 差异
