"""按正文上下文识别公告局部时间；不生成或改动旧条目。

入口只收已切板块正文，无活动名称特例，不依赖日志、网络、旧解析器
或当前时间。阶段/对象/诊断等小型 dict 是内部对照，非数据库存储
设计。记录与证据为 dataclass，时间精度与角色确认相互独立。

适配入口：日期格式改 _解析窗口/DATE_HINT，名称格式改 _提取名称/QUOTES；
阶段声明与对象边界在正文状态机中处理，时间标签由 check_stage_role 统一核对。
规则优先级为章节/声明/对象边界、备注、阶段、时间候选；改优先级需同时验证
真实原文和相邻反例。先留失败测试与原文证据，不以活动名特例或窗口相同猜归属。
窗口一致性在独立模块处理，后续条目生成不应反向改变这里的原文事实。
"""
from __future__ import annotations
import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from .公告窗口检查 import 检查窗口一致性


@dataclass(frozen=True)
class 原文证据:
    行: int
    文本: str


@dataclass(frozen=True)
class 局部记录:
    标签: str
    对象: tuple[str, ...]
    角色: str
    窗口: tuple[str, str] | None
    时间精度: Literal['精确', '未精确解析']
    角色状态: Literal['已确认', '待确认']
    证据: tuple[原文证据, ...]
    说明: tuple[原文证据, ...] = ()


@dataclass(frozen=True)
class 局部识别结果:
    局部记录: tuple[局部记录, ...]
    无独立日期的内容: tuple[dict, ...]
    阶段分组: tuple[dict, ...]
    诊断: tuple[dict, ...]
    备注: tuple[dict, ...]
    关卡覆盖范围: dict | None
    窗口一致性: dict
    完整性口径: str = '只检查本份板块文本，不声称未来不会追加或其他引用页无遗漏'

    @property
    def 阶段记录(self) -> tuple[局部记录, ...]:
        """已确认关卡/流程阶段的派生视图，不重复存储。"""
        return tuple(r for r in self.局部记录
                     if r.角色 in {'关卡开放', '流程阶段'} and r.角色状态 == '已确认')


def _转记录(record: dict) -> 局部记录:
    return 局部记录(
        标签=record['标签'], 对象=tuple(record['对象']), 角色=record['角色'],
        窗口=record['窗口'], 时间精度=record['时间精度'], 角色状态=record['角色状态'],
        证据=tuple(原文证据(**e) for e in record['证据']),
        说明=tuple(原文证据(**e) for e in record.get('说明', ())),
    )


HEADER = re.compile(r"^(={1,6})(.+?)\1\s*$")
QUOTES = re.compile(r"「([^」]+)」|【([^】]+)】|“([^”]+)”|『([^』]+)』|\"([^\"]+)\"")
RANGE = re.compile(r"(?P<a>(?:\d{4}\s*年)?\d{1,2}\s*月\d{1,2}\s*日.*?)\s*(?:[～~—–-]|至)\s*(?P<b>(?:\d{4}\s*年)?\d{1,2}\s*月\d{1,2}\s*日.*)$")
POINT = re.compile(r"(?:(\d{4})\s*年)?(\d{1,2})\s*月(\d{1,2})\s*日\s*(\d{1,2})\s*[:：]\s*(\d{2})")
DATE_HINT = re.compile(r"\d{1,2}\s*月\d{1,2}\s*日|\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
TIME_LABEL = re.compile(r"([^：:]*时间)\s*[：:]")


def _清理行(raw: str) -> str:
    line = re.sub(r"<!--.*?-->", "", raw)
    line = re.sub(r"</?(?:b|strong|span|small|div|p|br|noinclude)\b[^>]*>", "", line, flags=re.I)
    return html.unescape(re.sub(r"'+", "", line)).strip()


def _提取名称(text: str) -> list[str]:
    return [next(x for x in m.groups() if x) for m in QUOTES.finditer(text)]


def _解析窗口(line: str, year: int | None) -> tuple[tuple[str, str] | None, str]:
    interval = RANGE.search(line)
    if not interval:
        return None, "未找到完整日期范围"
    start = POINT.fullmatch(interval["a"].strip())
    end = POINT.fullmatch(interval["b"].strip())
    if not start or not end:
        return None, "端点含模糊时间或额外文字，未给出精确窗口"
    try:
        sy = int(start[1]) if start[1] else year
        if sy is None:
            return None, "缺少年份依据；开始端点未明示年份，不猜当前年份"
        ey = int(end[1]) if end[1] else sy
        a = datetime(sy, *map(int, start.groups()[1:]))
        b = datetime(ey, *map(int, end.groups()[1:]))
        if b < a:
            if not end[1] and a.month == 12 and b.month == 1:
                b = b.replace(year=sy + 1)
            else:
                return None, "结束早于开始，拒绝自动滚到次年"
    except ValueError as exc:
        return None, "非法日期：" + str(exc)
    return (a.strftime("%Y-%m-%d %H:%M:%S"), b.strftime("%Y-%m-%d %H:%M:%S")), ""


def 识别局部记录(正文: str, 年份: int | None, 起始行: int = 1) -> 局部识别结果:
    """只接收已切板块正文；起始行是正文第一行真实行号（空行也计数）。

    None 年仅接受开始端点明示年份的中文日期范围，结束年可沿用该年；
    12月→1月允许跨年。无日期内容不套总窗，关卡覆盖仅为窗口包络。
    """
    if not isinstance(正文, str):
        raise TypeError("正文必须为 str")
    if isinstance(起始行, bool) or not isinstance(起始行, int) or 起始行 < 1:
        raise ValueError("起始行必须为正整数")
    if 年份 is not None and (isinstance(年份, bool) or not isinstance(年份, int) or not 1 <= 年份 <= 9999):
        raise ValueError("年份必须为 1..9999 的整数或 None")
    year = 年份
    lines = list(enumerate(正文.splitlines(), 起始行))
    records, objects, issues, notices = [], [], [], []
    groups = []
    group_members = {}  # 构建期组内关联，不存储
    active_group = None
    last_stage = None
    covered = set()
    mode = "板块"
    current_object = None
    object_members = {}  # 同名子对象不跨边界回写角色
    pending = None

    def diagnostic(kind, number, raw, detail):
        issues.append({"类型": kind, "行": number, "原文": raw, "说明": detail})

    def flush():
        nonlocal pending
        if pending:
            diagnostic("缺时间", pending["line"], pending["raw"], "阶段标签后没有关联到时间")
            pending = None

    def record(label, targets, role, number, raw, line, prefix=None):
        window, reason = _解析窗口(line, year)
        raw_lines = ([prefix] if prefix else []) + [{"行": number, "文本": raw}]
        result = {"标签": label, "对象": targets, "角色": role,
                  "窗口": window, "时间精度": "精确" if window else "未精确解析",
                  "角色状态": "待确认" if role == "角色未确定" else "已确认", "证据": raw_lines}
        records.append(result)
        covered.add(number)
        if reason:
            diagnostic("时间未确定", number, raw, reason)
        return result

    def check_stage_role(result, line, number, raw):
        match = TIME_LABEL.search(line)
        label = match[1].strip() if match else ""
        date = DATE_HINT.search(line)
        if not match and date:
            prefix = line[:date.start()].strip()
            # 无时间标签可接受纯日期行，或◆阶段标签同行；其他正文前缀不是开放依据。
            if prefix and not prefix.startswith("◆"):
                result["角色"] = "角色未确定"
                result["角色状态"] = "待确认"
                diagnostic("未确认阶段时间依据", number, raw,
                           "日期前有其他正文/字段，不能仅凭待阶段上下文确认开放角色")
                return
        if "兑换时间" in label or "售卖时间" in label:
            result["角色"] = "角色未确定"
            result["角色状态"] = "待确认"
            diagnostic("时间角色冲突", number, raw, "阶段上下文与兑换/售卖标签冲突，不认定为阶段开放")
        elif label and not any(label.endswith(s) for s in ("开放时间", "开启时间", "活动时间")):
            result["角色"] = "角色未确定"
            result["角色状态"] = "待确认"
            if not any(i["行"] == number and i["类型"] == "未知时间标签" for i in issues):
                diagnostic("未知时间标签", number, raw, "阶段时间标签未确认，保留候选但不强定角色")

    for number, raw in lines:
        line = _清理行(raw)
        if not line:
            continue
        if line.startswith("[[文件:") or line.startswith("[[File:"):
            continue
        heading = HEADER.fullmatch(line)
        if heading:
            flush()
            mode = "子对象"
            label = heading[2].strip()
            current_object = {"名称": label, "角色": "未确定", "证据": [{"行": number, "文本": raw}]}
            object_members[id(current_object)] = []
            objects.append(current_object)
            continue
        declaration = re.search(r"活动分为([^：:。]+)[：:。]?", line)
        if declaration:
            flush()
            labels = [s.strip() for s in re.split(r"与|、|及|和", declaration[1]) if s.strip()]
            if len(labels) >= 2 and all(re.fullmatch(r"[^，,；;]{1,16}期", s) for s in labels):
                active_group = {"类型": "流程阶段", "声明标签": labels,
                                "证据": [{"行": number, "文本": raw}]}
                group_members[id(active_group)] = []
                groups.append(active_group)
                mode = "流程阶段"
                current_object = None
                last_stage = None
            else:
                diagnostic("阶段声明未识别", number, raw, "保留原文，不能确认声明的阶段列表")
                mode = "未确定分组"
                active_group = None
                last_stage = None
                current_object = None
            continue
        # 范围标题只建立上下文，不把这一行伪造为缺失日期。
        if "活动关卡" in line and not DATE_HINT.search(line) and re.search(r"开启|开放", line) and line.endswith(("：", ":")):
            flush()
            mode = "关卡"
            current_object = None
            continue
        object_match = QUOTES.fullmatch(line)
        if object_match:
            flush()
            mode = "子对象"
            current_object = {"名称": _提取名称(line)[0], "角色": "未确定", "证据": [{"行": number, "文本": raw}]}
            object_members[id(current_object)] = []
            objects.append(current_object)
            continue
        if current_object and "兑换说明" in line:
            current_object["角色"] = "兑换"
            current_object["证据"].append({"行": number, "文本": raw})
            for r in object_members[id(current_object)]:
                if r["角色"] == "子对象开放":
                    r["角色"] = "兑换开放"
                    r["证据"].append({"行": number, "文本": raw})
            continue
        # 引号内的内容是名称，不用其关键词判断备注；备注需有说明句依据。
        prose = QUOTES.sub("", line)
        notice_sentence = bool(re.search(r"本次|详情|可能|将于|将.*(?:常驻|收录)|过期时间(?:为)?", prose))
        if line.startswith("◆") and notice_sentence and ("提前" in prose or "延迟" in prose):
            notices.append({"行": number, "原文": raw, "类型": "排期可能调整"})
            if DATE_HINT.search(line):
                covered.add(number)
            continue
        if line.startswith("◆") and notice_sentence and re.search(r"过期|常驻|收录", prose):
            notices.append({"行": number, "原文": raw, "类型": "说明或时间节点"})
            if DATE_HINT.search(line):
                covered.add(number)
            continue
        if line.startswith("◆") and not DATE_HINT.search(line) and (
                prose.startswith("◆本次") or re.search(r"[请可]关注", prose) or
                ("商店内物品" in prose and "将" in prose)):
            notices.append({"行": number, "原文": raw, "类型": "正文说明"})
            continue
        if mode == "流程阶段":
            if line.startswith("◆"):
                flush()
                body = line[1:].strip()
                stage_match = re.match(r"^(.+?)[：:]\s*(.*)$", body)
                label = (stage_match[1] if stage_match else body).strip()
                # 日期不是阶段名；队列名单、单点过期等不因◆就变为阶段。
                if label in active_group["声明标签"] or (stage_match and RANGE.search(stage_match[2])):
                    if stage_match and stage_match[2]:
                        last_stage = record(label, [], "流程阶段", number, raw, line,
                                            active_group["证据"][0])
                        group_members[id(active_group)].append(last_stage)
                        check_stage_role(last_stage, line, number, raw)
                    else:
                        pending = {"label": label, "targets": [], "line": number, "raw": raw,
                                   "role": "流程阶段"}
                        last_stage = None
                    if label not in active_group["声明标签"]:
                        diagnostic("未声明阶段", number, raw, "出现声明列表之外的阶段，保留但完整性需核对")
                    continue
                diagnostic("阶段组边界未确定", number, raw, "◆内容不是可确认的阶段，不自动加入")
                last_stage = None
                mode = "未确定分组"
            elif last_stage and not DATE_HINT.search(line) and not TIME_LABEL.search(line):
                # 声明之后每段日期后的正文说明；遇到加粗字段即终止，避免吞队列名单。
                if re.match(r"[^：:]+[：:]", line):
                    last_stage = None
                    mode = "阶段组结束"
                else:
                    last_stage.setdefault("说明", []).append({"行": number, "文本": raw})
                continue
        if mode == "关卡" and line.startswith("◆"):
            flush()
            body = line[1:].strip()
            date = DATE_HINT.search(body)
            prefix_text = body[:date.start()].rstrip("：: ") if date else body.rstrip("：: ")
            label = re.sub(r"(?:开启|开放)?时间$", "", prefix_text).strip()
            label = label.strip("<〉>〈 ")
            targets = _提取名称(label)
            if date:
                r = record(label, targets, "关卡开放", number, raw, line)
                check_stage_role(r, line, number, raw)
            elif re.fullmatch(r"第[一二三四五六七八九十\d]+段", label) or targets or len(label) <= 16:
                pending = {"label": label, "targets": targets, "line": number, "raw": raw}
            else:
                diagnostic("未知关卡段内容", number, raw, "未能确定这是否为阶段标题")
            continue
        if mode == "板块" and line.startswith("◆"):
            # 标签明确含“关卡”且同行完整日期，是直接的关卡开放依据。
            direct = re.match(r"^◆\s*([^：:]+)[：:]", line)
            if direct and "关卡" in direct[1] and RANGE.search(line):
                r = record(direct[1].strip(), _提取名称(direct[1]), "关卡开放", number, raw, line)
                check_stage_role(r, line, number, raw)
                continue
        if mode in {"板块", "子对象", "阶段组结束", "未确定分组"} and line.startswith("◆"):
            # 即使没有认出关卡范围标题，也不能把其后局部开放时间提升为板块总窗。
            body = line[1:].strip().strip("<〉>〈 ")
            mode = "未确定分组"
            current_object = None
            diagnostic("未知分组标题", number, raw, "缺少可确认的关卡上下文，保留后续时间候选")
            if DATE_HINT.search(line):
                covered.add(number)
            continue
        if line.startswith("开放关卡"):
            targets = _提取名称(line)
            if records and records[-1]["角色"] in {"关卡开放", "角色未确定"} and mode == "关卡":
                records[-1]["对象"] = targets
                records[-1]["证据"].append({"行": number, "文本": raw})
            else:
                diagnostic("未关联关卡内容", number, raw, "没有对应的关卡开放记录")
            continue
        has_date = DATE_HINT.search(line)
        label_match = TIME_LABEL.search(line)
        if has_date or label_match:
            known_labels = {"活动时间", "关卡开放时间", "活动关卡开放时间", "活动关卡开启时间", "开放时间", "开启时间", "兑换时间"}
            label = label_match[1].strip() if label_match else ""
            is_range = bool(RANGE.search(line))
            if pending and (has_date or label in known_labels):
                r = record(pending["label"], pending["targets"], pending.get("role", "关卡开放"), number, raw, line,
                           {"行": pending["line"], "文本": pending["raw"]})
                if pending.get("role") == "流程阶段":
                    r["证据"].extend(active_group["证据"])
                    last_stage = r
                    group_members[id(active_group)].append(r)
                if label and label not in known_labels:
                    diagnostic("未知时间标签", number, raw, "时间标签与阶段上下文尚不能确认一致")
                    r["角色状态"] = "待确认"
                check_stage_role(r, line, number, raw)
                pending = None
            elif current_object and (label in known_labels or is_range):
                role = "兑换开放" if current_object["角色"] == "兑换" or label == "兑换时间" else "子对象开放"
                r = record(label, [current_object["名称"]], role, number, raw, line,
                           current_object["证据"][0])
                object_members[id(current_object)].append(r)
                if current_object["角色"] == "兑换":
                    r["证据"].extend(current_object["证据"][1:])
                if label not in known_labels:
                    r["角色状态"] = "待确认"
                    diagnostic("未知时间标签", number, raw, "保留子对象时间候选，角色需核对")
            elif mode == "板块" and label in known_labels:
                role = "明示关卡窗口" if "关卡" in label else "公告明示活动窗口" if label == "活动时间" else "角色未确定"
                record(label, [], role, number, raw, line)
                if role == "角色未确定":
                    diagnostic("时间角色未确定", number, raw, "不能仅凭开放时间认定整体活动窗口")
            else:
                covered.add(number)
                diagnostic("未关联时间候选", number, raw, "保留候选，不提升为整体活动窗口")
    flush()
    for number, raw in lines:
        if DATE_HINT.search(_清理行(raw)) and number not in covered:
            diagnostic("未处理日期", number, raw, "相关日期未被记录或诊断覆盖")
    stages = [r for r in records if r["角色"] == "关卡开放"]
    precise = stages and all(r["窗口"] and r["时间精度"] == "精确" and r["角色状态"] == "已确认" for r in stages)
    uncertain_combat = any(i["类型"] in {"未确认阶段时间依据", "时间角色冲突", "未知分组标题", "缺时间", "未知关卡段内容", "未关联关卡内容", "未知时间标签", "未关联时间候选", "未处理日期"} for i in issues)
    derived = None
    if precise and not uncertain_combat:
        derived = {"窗口": [min(r["窗口"][0] for r in stages), max(r["窗口"][1] for r in stages)],
                   "依据": "本份文本已识别关卡窗口的包络；不是明示整体活动窗口，也不保证没有空档"}
    for group in groups:
        members = group_members[id(group)]
        actual = [r["标签"] for r in members if r["角色"] == "流程阶段" and r["角色状态"] == "已确认"]
        missing = [label for label in group["声明标签"] if label not in actual]
        repeated = [label for label in dict.fromkeys(actual) if actual.count(label) > 1]
        group["缺失标签"] = missing
        group["重复标签"] = repeated
        group["状态"] = "本份声明已对应" if not missing and not repeated and set(actual) == set(group["声明标签"]) and all(r["窗口"] and r["时间精度"] == "精确" and r["角色状态"] == "已确认" for r in members) else "待核对"
        if missing or repeated:
            diagnostic("阶段声明未对应", group["证据"][0]["行"], group["证据"][0]["文本"],
                       f"缺失={missing}，重复={repeated}")
    structured_records = tuple(_转记录(r) for r in records)
    if len(groups) > 1:
        # 每组声明独立核对；多个组的总窗作用域原型没有覆盖，不跨组比较。
        first = groups[1]["证据"][0]
        diagnostic("多组流程窗口口径未确定", first["行"], first["文本"],
                   "各组阶段声明分别核对；总窗口作用域未确认，不跨组检查流程窗口")
        comparison_records = tuple(r for r in structured_records if r.角色 != "流程阶段")
        consistency, window_issues = 检查窗口一致性(comparison_records)
        consistency["检查项"].append({"类型": "多组流程范围检查", "状态": "无法检查",
                                      "说明": "未确认每组明示窗口的作用域，不跨组套用"})
        if not window_issues:
            consistency["状态"] = "部分无法检查"
        derived = None
    else:
        consistency, window_issues = 检查窗口一致性(structured_records)
    issues.extend(window_issues)
    if window_issues:
        derived = None
    return 局部识别结果(
        局部记录=structured_records, 阶段分组=tuple(groups),
        无独立日期的内容=tuple(o for o in objects if not object_members[id(o)]),
        关卡覆盖范围=derived, 诊断=tuple(issues), 备注=tuple(notices), 窗口一致性=consistency,
    )


__all__ = ['原文证据', '局部记录', '局部识别结果', '识别局部记录']
