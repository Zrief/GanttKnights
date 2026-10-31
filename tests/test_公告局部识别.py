"""正式公告局部识别的离线回归：移植原型58项验收，不导入tmp代码。

样本为人工验收使用的原文快照，测试独立切正文且保持证据原始行号。
adapter只转换容器并兼容旧状态断言；两个新状态轴始终独立验证。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
import re
import unittest

import pytest

ROOT = Path(__file__).resolve().parent / "fixtures" / "局部识别"


def split_block(text, title_contains):
    """仅测试负责挑板块，正式入口只接收正文。"""
    lines = text.splitlines()
    header = re.compile(r"^(={1,6})(.+?)\1\s*$")
    for i, raw in enumerate(lines):
        match = header.fullmatch(raw.strip())
        if match and title_contains in match[2]:
            end = len(lines)
            for j in range(i + 1, len(lines)):
                following = header.fullmatch(lines[j].strip())
                if following and len(following[1]) <= len(match[1]):
                    end = j
                    break
            return match[2].strip(), [(j + 1, lines[j]) for j in range(i + 1, end)]
    raise ValueError("没有找到指定板块：" + title_contains)


def plain(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def adapt(result):
    assert is_dataclass(result)
    for row in result.局部记录:
        assert is_dataclass(row)
        assert isinstance(row.对象, tuple)
        assert row.时间精度 in ("精确", "未精确解析")
        assert row.角色状态 in ("已确认", "待确认")
        assert (row.窗口 is not None) == (row.时间精度 == "精确")
        if row.窗口 is not None:
            assert isinstance(row.窗口, tuple) and len(row.窗口) == 2
        assert isinstance(row.证据, tuple)
        assert isinstance(row.说明, tuple)
        for evidence in row.证据 + row.说明:
            assert is_dataclass(evidence)
            assert isinstance(evidence.行, int)
            assert isinstance(evidence.文本, str)
    converted = plain(result)
    converted["阶段记录"] = plain(result.阶段记录)
    for row in converted["局部记录"] + converted["阶段记录"]:
        # 原型用一轴状态；正式字段仍完整保留，不替换/推导两轴。
        row["状态"] = "角色待确认" if row["角色状态"] == "待确认" else row["时间精度"]
    return converted


@pytest.fixture(autouse=True)
def 正式入口(内核模块, monkeypatch):
    module = 内核模块("公告局部识别")
    windows = 内核模块("公告窗口检查")

    def extract(text, year, page=None, title_contains="SideStory"):
        _, lines = split_block(text, title_contains)
        start = lines[0][0] if lines else 1
        return adapt(module.识别局部记录("\n".join(raw for _, raw in lines), year, 起始行=start))

    def check_windows(rows):
        records = tuple(module.局部记录(
            标签=row["标签"], 对象=(), 角色=row["角色"],
            窗口=tuple(row["窗口"]) if row["窗口"] else None,
            时间精度=row["时间精度"], 角色状态=row["角色状态"],
            证据=tuple(module.原文证据(**e) for e in row["证据"]), 说明=(),
        ) for row in rows)
        before = deepcopy(records)
        result = windows.检查窗口一致性(records)
        assert records == before
        return plain(result)

    monkeypatch.setitem(globals(), "extract", extract)
    monkeypatch.setitem(globals(), "check_windows", check_windows)
    return module, windows


def recruit(text=None, title="感谢庆典特别招募活动开启"):
    return extract(RAW if text is None else text, 2026, "离线招募", title)


def safety_run(text, year=2026):
    return extract(text, year, "构造变体")


RAW = (ROOT / "感谢庆典2026.wikitext").read_text(encoding="utf-8")
BASE = RAW
RERUN = (ROOT / "孤星2024.wikitext").read_text(encoding="utf-8")
TITLE, LINES = split_block(RAW, "感谢庆典特别招募活动开启")
TEXT = "==" + TITLE + "==\n" + "\n".join(raw for _, raw in LINES)
A = ["2026-10-24 21:30:00", "2026-11-01 06:59:00"]
B = ["2026-11-01 12:00:00", "2026-12-02 03:59:00"]
TOTAL = [A[0], B[1]]

EXPECTED = {
    "感谢庆典2026": (2026, [(["残照终尽"], "11-01 12:00", "11-22 03:59"), (["长冬初青"], "11-08 16:00", "11-22 03:59"), (["世纪之春"], "11-15 16:00", "11-22 03:59")], "炮火所掩埋的", "11-01 12:00", "11-29 03:59", 0),
    "感谢庆典2025": (2025, [(["圣巡之旅"], None, None), (["变革之路"], "11-08 16:00", "11-22 03:59"), (["喀兰之心"], "11-15 16:00", "11-22 03:59")], "观测站后勤处", None, None, 0),
    "生路": (2024, [(["信标投放"], "06-05 16:00", "06-19 03:59"), (["防线巩固"], "06-12 16:00", "06-19 03:59")], "物质塑形操作终端", "06-05 16:00", "06-26 03:59", 1),
    "生路2025": (2025, [(["信标投放", "防线巩固"], "06-19 16:00", "06-29 03:59")], "物质塑形操作终端", "06-19 16:00", "07-03 03:59", 1),
    "孤星2024": (2024, [(["未来将至"], "05-24 16:00", "06-03 03:59"), (["过往未尽"], "05-24 16:00", "06-03 03:59"), (["紧握当下"], "05-24 16:00", "06-03 03:59")], "专案联络处", "05-24 16:00", "06-07 03:59", 1),
    "孤星": (2023, [(["未来将至"], "05-01 16:00", "05-22 03:59"), (["过往未尽"], "05-08 16:00", "05-22 03:59"), (["紧握当下"], "05-15 16:00", "05-22 03:59")], "专案联络处", "05-01 16:00", "05-29 03:59", 0),
}


def window(year, a, b):
    return [f"{year}-{a}:00", f"{year}-{b}:00"] if a else None


def fixture(name="感谢庆典2026"):
    return (ROOT / (name + ".wikitext")).read_text(encoding="utf-8")


def check_real(test, name):
    year, stages, shop, shop_a, shop_b, explicit = EXPECTED[name]
    result = extract(fixture(name), year, name)
    combat = [r for r in result["局部记录"] if r["角色"] == "关卡开放"]
    test.assertEqual([(r["对象"], r["窗口"]) for r in combat], [(targets, window(year, a, b)) for targets, a, b in stages])
    exchange = [r for r in result["局部记录"] if r["角色"] == "兑换开放"]
    test.assertEqual([(r["对象"], r["窗口"]) for r in exchange], [([shop], window(year, shop_a, shop_b))])
    overview = [r for r in result["局部记录"] if r["角色"] == "公告明示活动窗口"]
    test.assertEqual(len(overview), explicit)
    test.assertEqual(len(result["局部记录"]), len(stages) + 1 + explicit)
    test.assertFalse(any(i["类型"] == "未处理日期" for i in result["诊断"]))
    if name == "感谢庆典2025":
        test.assertIsNone(result["关卡覆盖范围"])
        test.assertEqual(len(result["诊断"]), 2)
        test.assertTrue(all(i["类型"] == "时间未确定" for i in result["诊断"]))
        test.assertTrue(any("版本更新后" in e["文本"] for e in combat[0]["证据"]))
    else:
        test.assertEqual(result["诊断"], [])
        test.assertEqual(result["关卡覆盖范围"]["窗口"], [min(window(year, a, b)[0] for _, a, b in stages), max(window(year, a, b)[1] for _, a, b in stages)])
    for r in result["局部记录"]:
        for evidence in r["证据"]:
            test.assertEqual(fixture(name).splitlines()[evidence["行"] - 1], evidence["文本"])


class RealSamples(unittest.TestCase):
    pass


for name in EXPECTED:
    setattr(RealSamples, "test_" + name, lambda self, name=name: check_real(self, name))


class Variants(unittest.TestCase):
    def run_text(self, text):
        return extract(text, 2026, "构造变体，不是现网原文")

    def test_新阶段标签不升级总窗(self):
        result = self.run_text(fixture().replace("第一段", "序章"))
        self.assertEqual([r["标签"] for r in result["局部记录"] if r["角色"] == "关卡开放"], ["序章", "第二段", "第三段"])
        self.assertFalse(any(r["角色"] == "公告明示活动窗口" for r in result["局部记录"]))
        self.assertEqual(result["诊断"], [])

    def test_至及全角时分分隔(self):
        result = self.run_text(fixture().replace(" - ", " 至 ").replace("12:00", "12：00"))
        self.assertTrue(all(r["窗口"] for r in result["局部记录"]))
        self.assertEqual(result["诊断"], [])

    def test_标题换括号仍关联(self):
        result = self.run_text(fixture().replace("&lt;第一段&gt;", "【第一段】"))
        self.assertEqual(result["局部记录"][0]["窗口"], window(2026, "11-01 12:00", "11-22 03:59"))

    def test_缺首段日期保留(self):
        result = self.run_text(fixture().replace("'''开放时间：'''11月01日 12:00 - 11月22日 03:59", "", 1))
        self.assertTrue(any(i["类型"] == "缺时间" for i in result["诊断"]))
        self.assertIsNone(result["关卡覆盖范围"])
        self.assertFalse(any(r["角色"] == "公告明示活动窗口" for r in result["局部记录"]))

    def test_未知时间标签有诊断(self):
        result = self.run_text(fixture().replace("开放时间", "挑战时间", 1))
        self.assertEqual(result["局部记录"][0]["状态"], "角色待确认")
        self.assertTrue(any(i["类型"] == "未知时间标签" for i in result["诊断"]))
        self.assertIsNone(result["关卡覆盖范围"])

    def test_失去关卡上下文不猜总窗(self):
        result = self.run_text(fixture().replace("活动关卡将进行分段式开启：", "这里列出相关内容："))
        self.assertTrue(any(i["类型"] == "未关联时间候选" for i in result["诊断"]))
        self.assertFalse(any(r["角色"] == "公告明示活动窗口" for r in result["局部记录"]))

    def test_明确逆序拒绝(self):
        text = fixture().replace("11月01日 12:00 - 11月22日 03:59", "2026年11月22日 12:00 - 2026年11月01日 03:59", 1)
        result = self.run_text(text)
        self.assertIsNone(result["局部记录"][0]["窗口"])
        self.assertTrue(any("结束早于开始" in i["说明"] for i in result["诊断"]))
        self.assertIsNone(result["关卡覆盖范围"])

    def test_无年逆序不滚一年(self):
        result = self.run_text(fixture().replace("11月01日 12:00 - 11月22日 03:59", "11月22日 12:00 - 11月01日 03:59", 1))
        self.assertIsNone(result["局部记录"][0]["窗口"])

    def test_正常跨年(self):
        result = self.run_text(fixture().replace("11月01日 12:00 - 11月22日 03:59", "12月28日 12:00 - 01月03日 03:59", 1))
        self.assertEqual(result["局部记录"][0]["窗口"], ["2026-12-28 12:00:00", "2027-01-03 03:59:00"])

    def test_未知日期范围保留诊断(self):
        text = fixture().replace("'''【战时新闻委员会】'''", "额外参与期：11月02日 12:00 - 11月04日 03:59\n'''【战时新闻委员会】'''")
        result = self.run_text(text)
        self.assertTrue(any(i["类型"] == "未关联时间候选" and "额外参与期" in i["原文"] for i in result["诊断"]))
        self.assertFalse(any(i["类型"] == "未处理日期" for i in result["诊断"]))

    def test_更深章节范围不混后续卡池(self):
        text = fixture().replace("'''【战时新闻委员会】'''", "===战时新闻委员会===")
        result = self.run_text(text)
        self.assertEqual(len(result["局部记录"]), 4)
        self.assertEqual(result["局部记录"][-1]["对象"], ["炮火所掩埋的"])

    def test_无日期任务不套窗口(self):
        result = self.run_text(fixture())
        self.assertEqual({o["名称"] for o in result["无独立日期的内容"]}, {"战时新闻委员会", "晨曦所见证的"})
        self.assertTrue(all("窗口" not in o for o in result["无独立日期的内容"]))

    def test_兑换说明在日期之前(self):
        text = "==SideStory「构造样本」==\n【商店甲】\n兑换说明：消耗代币兑换\n开放时间：11月01日 12:00 - 11月29日 03:59"
        result = self.run_text(text)
        self.assertEqual(result["局部记录"][0]["角色"], "兑换开放")

    def test_阶段日期单独下一行(self):
        text = fixture().replace("'''开放时间：'''11月01日 12:00", "'''开放时间：'''\n11月01日 12:00", 1)
        result = self.run_text(text)
        # 当前最小原型尚不支持标签+日期再分成两行；必须显式失败，不能输出伪总窗。
        self.assertIsNone(result["局部记录"][0]["窗口"])
        self.assertTrue(result["诊断"])
        self.assertIsNone(result["关卡覆盖范围"])



class Recruitment(unittest.TestCase):
    def test_真实招募正文(self):
        result = recruit()
        self.assertEqual([(r["标签"], r["窗口"]) for r in result["阶段记录"]], [("预选期", A), ("招募期", B)])
        total = [r for r in result["局部记录"] if r["角色"] == "公告明示活动窗口"]
        self.assertEqual([r["窗口"] for r in total], [TOTAL])
        self.assertEqual(len(result["局部记录"]), 3)
        self.assertEqual(result["诊断"], [])
        self.assertIsNone(result["关卡覆盖范围"])
        self.assertEqual(result["阶段分组"][0]["状态"], "本份声明已对应")
        self.assertIn("预选特别招募队列", result["阶段记录"][0]["说明"][0]["文本"])
        self.assertIn("招募干员", result["阶段记录"][1]["说明"][0]["文本"])
        for r in result["局部记录"]:
            for evidence in r["证据"] + r.get("说明", []):
                self.assertEqual(RAW.splitlines()[evidence["行"] - 1], evidence["文本"])

    def test_空档不填平(self):
        result = recruit()
        self.assertEqual(result["阶段记录"][0]["窗口"][1], "2026-11-01 06:59:00")
        self.assertEqual(result["阶段记录"][1]["窗口"][0], "2026-11-01 12:00:00")

    def test_改活动名仍由正文识别(self):
        result = recruit(TEXT.replace(TITLE, "全新流程活动"), "全新流程活动")
        self.assertEqual([(r["标签"], r["窗口"]) for r in result["阶段记录"]], [("预选期", A), ("招募期", B)])

    def test_第三阶段声明扩展(self):
        text = TEXT.replace("活动分为预选期与招募期：", "活动分为预选期、招募期与补领期：")
        text = text.replace("'''特别招募队列·Ⅰ包含干员：'''", "◆补领期：12月02日 12:00 - 12月05日 03:59\n'''特别招募队列·Ⅰ包含干员：'''", 1)
        result = recruit(text)
        self.assertEqual([r["标签"] for r in result["阶段记录"]], ["预选期", "招募期", "补领期"])
        self.assertTrue(any(i["类型"] == "阶段超出明示窗口" for i in result["诊断"]))
        self.assertEqual(result["窗口一致性"]["状态"], "存在冲突")

    def test_未声明第三阶段需诊断(self):
        result = recruit(TEXT.replace("'''特别招募队列·Ⅰ包含干员：'''", "◆补领期：12月02日 12:00 - 12月05日 03:59\n'''特别招募队列·Ⅰ包含干员：'''", 1))
        self.assertEqual(len(result["阶段记录"]), 3)
        self.assertTrue(any(i["类型"] == "未声明阶段" for i in result["诊断"]))
        self.assertEqual(result["阶段分组"][0]["状态"], "待核对")

    def test_缺招募期不由总窗补齐(self):
        result = recruit(TEXT.replace("◆招募期：11月01日 12:00 - 12月02日 03:59", ""))
        self.assertEqual([r["标签"] for r in result["阶段记录"]], ["预选期"])
        self.assertIn("招募期", result["阶段分组"][0]["缺失标签"])
        self.assertTrue(result["诊断"])

    def test_模糊阶段时间保留(self):
        result = recruit(TEXT.replace("◆招募期：11月01日 12:00", "◆招募期：11月01日版本更新后"))
        self.assertIsNone(result["阶段记录"][1]["窗口"])
        self.assertEqual(result["阶段分组"][0]["状态"], "待核对")

    def test_阶段标题日期分行(self):
        result = recruit(TEXT.replace("◆预选期：10月24日", "◆预选期\n开放时间：10月24日").replace("◆招募期：11月01日", "◆招募期\n开放时间：11月01日"))
        self.assertEqual([r["窗口"] for r in result["阶段记录"]], [A, B])
        self.assertEqual(result["诊断"], [])

    def test_队列名单不成为阶段说明(self):
        result = recruit()
        self.assertFalse(any("包含干员" in e["文本"] for r in result["阶段记录"] for e in r.get("说明", [])))
        self.assertEqual(len(result["阶段记录"]), 2)

    def test_缺分组声明不猜阶段(self):
        result = recruit(TEXT.replace("活动分为预选期与招募期：", "下面列出操作说明："))
        self.assertEqual(result["阶段记录"], [])
        self.assertTrue(result["诊断"])

    def test_重复阶段诊断(self):
        result = recruit(TEXT.replace("◆预选期：10月24日 21:30 - 11月01日 06:59", "◆预选期：10月24日 21:30 - 11月01日 06:59\n◆预选期：10月24日 21:30 - 11月01日 06:59"))
        self.assertEqual(result["阶段分组"][0]["重复标签"], ["预选期"])
        self.assertEqual(result["阶段分组"][0]["状态"], "待核对")

    def test_分行阶段冲突时间标签(self):
        result = recruit(TEXT.replace("◆预选期：10月24日", "◆预选期\n兑换时间：10月24日"))
        conflict = next(r for r in result["局部记录"] if r["标签"] == "预选期")
        self.assertEqual(conflict["状态"], "角色待确认")
        self.assertEqual(conflict["角色"], "角色未确定")
        self.assertNotIn(conflict, result["阶段记录"])
        self.assertEqual(result["阶段分组"][0]["状态"], "待核对")
        self.assertTrue(result["诊断"])



class SafetyVariants(unittest.TestCase):
    def test_商店五种成对标题正确归属(self):
        for opening, closing in [('「','」'), ('“','”'), ('『','』'), ('"','"'), ('【','】')]:
            with self.subTest(opening=opening):
                result = safety_run(BASE.replace("'''【炮火所掩埋的】'''", f"'''{opening}炮火所掩埋的{closing}'''"))
                exchange = [r for r in result['局部记录'] if r['角色'] == '兑换开放']
                self.assertEqual([r['对象'] for r in exchange], [['炮火所掩埋的']])
                self.assertEqual(result['诊断'], [])

    def test_备注关键词在关卡名中不吞阶段(self):
        for name in ['常驻试炼', '过期之城', '收录之庭', '提前启航', '延迟终局']:
            with self.subTest(name=name):
                result = safety_run(RERUN.replace('未来将至', name), 2024)
                stages = result['阶段记录']
                self.assertEqual(len(stages), 3)
                self.assertEqual(stages[0]['对象'], [name])
                self.assertEqual(result['诊断'], [])

    def test_商店后未知分组不能沿用旧对象(self):
        result = safety_run('==SideStory「样本」==\n【商店甲】\n兑换说明：消耗代币兑换\n开放时间：11月01日 12:00 - 11月29日 03:59\n◆未知分组\n活动时间：11月02日 12:00 - 11月04日 03:59')
        self.assertEqual(len(result['局部记录']), 1)
        self.assertTrue(any(i['类型'] == '未知分组标题' for i in result['诊断']))
        self.assertTrue(any('11月02日' in i['原文'] for i in result['诊断']))

    def test_同行流程阶段冲突也降级(self):
        # 招募正文及入口由本文件的离线装置提供
        result = recruit(TEXT.replace('◆预选期：10月24日', '◆预选期兑换时间：10月24日'))
        conflict = result['局部记录'][1]
        self.assertEqual(conflict['角色'], '角色未确定')
        self.assertEqual(conflict['状态'], '角色待确认')
        self.assertTrue(any(i['类型'] == '时间角色冲突' for i in result['诊断']))

    def test_同行未知关卡时间标签不强定(self):
        result = safety_run(RERUN.replace('【未来将至】开启时间', '【未来将至】挑战时间', 1), 2024)
        candidate = next(r for r in result['局部记录'] if r['对象'] == ['未来将至'])
        self.assertEqual(candidate['角色'], '角色未确定')
        self.assertEqual(candidate['状态'], '角色待确认')
        self.assertIsNone(result['关卡覆盖范围'])

    def test_分行兑换标签冲突不强定关卡(self):
        result = safety_run(BASE.replace('开放时间', '兑换时间', 1))
        first = result['局部记录'][0]
        self.assertEqual(first['角色'], '角色未确定')
        self.assertEqual(first['状态'], '角色待确认')
        self.assertTrue(any(i['类型'] == '时间角色冲突' for i in result['诊断']))
        self.assertIsNone(result['关卡覆盖范围'])
        self.assertNotIn(first, result['阶段记录'])

    def test_同行兑换标签冲突同样降级(self):
        result = safety_run(RERUN.replace('【未来将至】开启时间', '【未来将至】兑换时间', 1), 2024)
        record = next(r for r in result['局部记录'] if '未来将至' in r['对象'])
        self.assertEqual(record['角色'], '角色未确定')
        self.assertTrue(any(i['类型'] == '时间角色冲突' for i in result['诊断']))
        self.assertIsNone(result['关卡覆盖范围'])

    def test_未知分组名称不提升总窗(self):
        for label in ['序章', '很长的未知分组标题也不能被忽略', '第1段']:
            with self.subTest(label=label):
                result = safety_run(f'==SideStory「任意名」==\n这里列出相关内容：\n◆{label}\n活动时间：11月01日 12:00 - 11月22日 03:59\n开放关卡：【甲】')
                self.assertFalse(any(r['角色'] == '公告明示活动窗口' for r in result['局部记录']))
                self.assertTrue(any(i['类型'] == '未知分组标题' for i in result['诊断']))
                self.assertIsNone(result['关卡覆盖范围'])

    def test_未知ISO日期必须诊断(self):
        result = safety_run(BASE.replace("'''【战时新闻委员会】'''", "额外参与期：2026-11-02 12:00 - 2026-11-04 03:59\n'''【战时新闻委员会】'''"))
        self.assertTrue(any('2026-11-02' in i['原文'] for i in result['诊断']))
        self.assertFalse(any(i['类型'] == '未处理日期' for i in result['诊断']))
        self.assertIsNone(result['关卡覆盖范围'])

    def test_已关联ISO日期不冒充精确支持(self):
        result = safety_run(BASE.replace('11月01日 12:00 - 11月22日 03:59', '2026-11-01 12:00 - 2026-11-22 03:59', 1))
        self.assertIsNone(result['局部记录'][0]['窗口'])
        self.assertTrue(result['诊断'])
        self.assertIsNone(result['关卡覆盖范围'])

    def test_日期备注不导致后续局部窗升级(self):
        result = safety_run('==SideStory「样本」==\n◆活动关卡将于2026年11月30日04:00常驻\n开放时间：11月01日 12:00 - 11月22日 03:59')
        self.assertTrue(result['备注'])
        self.assertFalse(any(r['角色'] == '公告明示活动窗口' for r in result['局部记录']))

    def test_备注中的区域名不构成阶段(self):
        result = safety_run(RERUN.replace("'''活动关卡开放时间：'''", "'''活动关卡开放时间：'''\n◆本次活动结束后，【未来将至】将收录至【插曲】并常驻"), 2024)
        self.assertEqual(len(result['阶段记录']), 3)
        self.assertTrue(result['备注'])
        self.assertEqual(result['诊断'], [])



def record(role, a='2026-11-01 12:00:00', b='2026-11-22 03:59:00', label='第一段', line=1):
    return {'角色': role, '标签': label, '窗口': [a, b], '时间精度': '精确', '角色状态': '已确认', '证据': [{'行': line, '文本': label + '原文'}]}


class WindowConsistency(unittest.TestCase):
    def test_真实招募空档合法(self):
        result = recruit()
        self.assertEqual(result['窗口一致性']['状态'], '已检查关系未见冲突')
        self.assertEqual([c['状态'] for c in result['窗口一致性']['检查项']], ['包含', '包含'])

    def test_真实SideStory重叠合法(self):
        result = extract(fixture('生路'), 2024, '生路')
        self.assertEqual(result['诊断'], [])
        self.assertEqual(result['窗口一致性']['状态'], '已检查关系未见冲突')

    def test_无明示窗口不假定整体(self):
        result = extract(fixture(), 2026, '感谢庆典2026')
        self.assertEqual(result['窗口一致性']['状态'], '无明示窗口可比较')
        self.assertTrue(result['关卡覆盖范围'])

    def test_第三阶段越界保留而诊断(self):
        text = TEXT.replace('活动分为预选期与招募期：', '活动分为预选期、招募期与补领期：').replace("'''特别招募队列·Ⅰ包含干员：'''", "◆补领期：12月02日 12:00 - 12月05日 03:59\n'''特别招募队列·Ⅰ包含干员：'''", 1)
        result = recruit(text)
        self.assertEqual(result['阶段记录'][-1]['窗口'][1], '2026-12-05 03:59:00')
        self.assertEqual(result['局部记录'][0]['窗口'], TOTAL)
        self.assertEqual(result['窗口一致性']['状态'], '存在冲突')
        self.assertTrue(any(i['类型'] == '阶段超出明示窗口' for i in result['诊断']))

    def test_阶段提前开始(self):
        result = recruit(TEXT.replace('◆预选期：10月24日', '◆预选期：10月23日'))
        self.assertEqual(result['窗口一致性']['状态'], '存在冲突')
        self.assertEqual(result['阶段记录'][0]['窗口'][0], '2026-10-23 21:30:00')

    def test_全提取多总窗保留双方(self):
        text = TEXT.replace("'''活动时间：'''10月24日 21:30 - 12月02日 03:59", "'''活动时间：'''10月24日 21:30 - 12月02日 03:59\n活动时间：10月24日 21:30 - 12月05日 03:59", 1)
        result = recruit(text)
        self.assertEqual(len([r for r in result['局部记录'] if r['角色'] == '公告明示活动窗口']), 2)
        self.assertEqual(result['窗口一致性']['状态'], '存在冲突')
        self.assertEqual([r['窗口'] for r in result['阶段记录']], [['2026-10-24 21:30:00', '2026-11-01 06:59:00'], ['2026-11-01 12:00:00', '2026-12-02 03:59:00']])

    def test_关卡越界不再生成覆盖概览(self):
        text = fixture('生路').replace("'''活动时间：'''06月05日 16:00 - 06月26日 03:59", "'''活动时间：'''06月05日 16:00 - 06月10日 03:59", 1)
        result = extract(text, 2024, '生路')
        self.assertEqual(len(result['阶段记录']), 2)
        self.assertEqual(result['窗口一致性']['状态'], '存在冲突')
        self.assertIsNone(result['关卡覆盖范围'])

    def test_不同总窗不选一个(self):
        rows = [record('公告明示活动窗口'), record('公告明示活动窗口', b='2026-11-29 03:59:00', line=2), record('关卡开放', line=3)]
        before = deepcopy(rows)
        result, issues = check_windows(rows)
        self.assertEqual(result['状态'], '存在冲突')
        self.assertEqual(issues[0]['类型'], '明示窗口冲突')
        self.assertEqual(rows, before)
        self.assertEqual(len(issues[0]['证据']), 2)

    def test_相同总窗可重复(self):
        result, issues = check_windows([record('公告明示活动窗口'), record('公告明示活动窗口'), record('关卡开放')])
        self.assertEqual(issues, [])
        self.assertEqual(result['状态'], '已检查关系未见冲突')

    def test_模糊总窗不借其他行替代(self):
        rows = [record('公告明示活动窗口'), record('公告明示活动窗口'), record('关卡开放')]
        rows[1]['窗口'] = None
        rows[1]['时间精度'] = '未精确解析'
        result, issues = check_windows(rows)
        self.assertEqual(result['状态'], '部分无法检查')
        self.assertEqual(result['检查项'][0]['状态'], '无法检查')
        self.assertEqual(issues, [])

    def test_模糊阶段不声称全部一致(self):
        result = recruit(TEXT.replace('◆招募期：11月01日 12:00', '◆招募期：11月01日版本更新后'))
        self.assertEqual(result['窗口一致性']['状态'], '部分无法检查')

    def test_兑换可晚于关卡(self):
        rows = [record('明示关卡窗口'), record('关卡开放'), record('兑换开放', b='2026-11-29 03:59:00')]
        result, issues = check_windows(rows)
        self.assertEqual(issues, [])
        self.assertEqual(len(result['检查项']), 1)

    def test_关卡总窗不约束流程阶段(self):
        result, issues = check_windows([record('明示关卡窗口'), record('关卡开放'), record('流程阶段', b='2026-12-02 03:59:00')])
        self.assertEqual(issues, [])

    def test_阶段覆盖不须等于总窗(self):
        result, issues = check_windows([record('公告明示活动窗口', b='2026-11-29 03:59:00'), record('关卡开放')])
        self.assertEqual(issues, [])
        self.assertEqual(result['状态'], '已检查关系未见冲突')



def test_缺年份不猜且角色仍已确认(正式入口):
    module, _ = 正式入口
    _, lines = split_block(RAW, 'SideStory')
    result = module.识别局部记录('\n'.join(raw for _, raw in lines), None, 起始行=lines[0][0])
    adapt(result)
    assert result.局部记录
    assert all(row.窗口 is None and row.时间精度 == '未精确解析' for row in result.局部记录)
    assert all(row.角色状态 == '已确认' for row in result.局部记录)
    assert result.关卡覆盖范围 is None
    assert any('年份' in issue['说明'] for issue in result.诊断)


def test_显式年份不需参考年份(正式入口):
    module, _ = 正式入口
    result = module.识别局部记录('活动时间：2024年12月28日 12:00 - 2025年01月03日 03:59', None)
    adapt(result)
    row, = result.局部记录
    assert row.窗口 == ('2024-12-28 12:00:00', '2025-01-03 03:59:00')
    assert row.时间精度 == '精确' and row.角色状态 == '已确认'
    assert not result.诊断


def test_角色待确认与精确时间独立(正式入口):
    module, _ = 正式入口
    text = '活动关卡将进行分段式开启：\n◆第一段\n挑战时间：11月01日 12:00 - 11月22日 03:59\n开放关卡：【甲】'
    result = module.识别局部记录(text, 2026)
    adapt(result)
    row, = result.局部记录
    assert row.角色 == '角色未确定' and row.角色状态 == '待确认'
    assert row.时间精度 == '精确'
    assert row.窗口 == ('2026-11-01 12:00:00', '2026-11-22 03:59:00')
    assert not result.阶段记录 and result.关卡覆盖范围 is None


def test_同名对象同窗不同出现不合并(正式入口):
    module, _ = 正式入口
    text = '活动关卡开放时间：\n◆【同名区域】开启时间：11月01日 12:00 - 11月22日 03:59\n◆【同名区域】开启时间：11月01日 12:00 - 11月22日 03:59'
    result = module.识别局部记录(text, 2026, 起始行=20)
    adapt(result)
    assert len(result.阶段记录) == 2
    a, b = result.阶段记录
    assert a.对象 == b.对象 == ('同名区域',) and a.窗口 == b.窗口
    assert a.证据[-1].行 == 21 and b.证据[-1].行 == 22


def test_同名商店说明不回填早先出现(正式入口):
    module, _ = 正式入口
    text = '【同名对象】\n开放时间：11月01日 12:00 - 11月22日 03:59\n【同名对象】\n开放时间：11月01日 12:00 - 11月22日 03:59\n兑换说明：消耗代币兑换'
    result = module.识别局部记录(text, 2026)
    adapt(result)
    assert len(result.局部记录) == 2
    first, second = result.局部记录
    assert first.角色 == '子对象开放' and second.角色 == '兑换开放'
    assert all('兑换说明' not in e.文本 for e in first.证据)


def test_原始正文空行及偏移证据(正式入口):
    module, _ = 正式入口
    text = '\n\n活动时间：2026年11月01日 12:00 - 11月22日 03:59\n'
    result = module.识别局部记录(text, None, 起始行=101)
    adapt(result)
    row, = result.局部记录
    assert row.证据[-1].行 == 103 and row.证据[-1].文本 == text.splitlines()[2]


def test_待确认角色不参与精确窗口比较():
    rows = [record('公告明示活动窗口'), record('关卡开放', b='2026-12-02 03:59:00')]
    rows[1]['角色状态'] = '待确认'
    result, issues = check_windows(rows)
    assert result['状态'] == '部分无法检查' and not issues
    assert not any(item['状态'] == '超出' for item in result['检查项'])


@pytest.mark.parametrize('name', tuple(EXPECTED))
def test_旧抽板块附带局部识别及真实证据(内核模块, name):
    from datetime import datetime
    module = 内核模块('解析_公告')
    raw = fixture(name)
    blocks = module.抽板块(raw, datetime(EXPECTED[name][0], 6, 1))
    block = next(block for block in blocks if 'SideStory' in block.标题)
    assert block.局部识别 is not None and block.局部识别.局部记录
    adapt(block.局部识别)
    for row in block.局部识别.局部记录:
        for evidence in row.证据 + row.说明:
            assert raw.splitlines()[evidence.行 - 1] == evidence.文本
    assert plain(block.局部识别.局部记录) == [
        {key: value for key, value in row.items() if key != '状态'}
        for row in extract(raw, EXPECTED[name][0])['局部记录']
    ]


def test_旧入口未支持板块不新增输出(内核模块):
    module = 内核模块('解析_公告')
    unsupported = '==全新说明栏目==\n这里没有日期，也没有旧入口可识别的时间段。'
    assert module.抽板块(unsupported) == []
