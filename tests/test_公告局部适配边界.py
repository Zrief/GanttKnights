"""正式接入后新增情况的保守边界，不依赖实验目录。"""

def test_待阶段不把维护说明日期强定开放(内核模块):
    module = 内核模块('公告局部识别')
    text = '活动关卡开放时间：\n◆第一段\n维护安排：11月01日 12:00 - 11月22日 03:59\n开放关卡：【甲】'
    result = module.识别局部记录(text, 2026)
    row, = result.局部记录
    assert row.窗口 is not None and row.时间精度 == '精确'
    assert row.角色状态 == '待确认' and row.角色 == '角色未确定'
    assert row.对象 == ('甲',)
    assert any(i['类型'] == '未确认阶段时间依据' for i in result.诊断)
    assert result.关卡覆盖范围 is None and not result.阶段记录


def test_待流程不把其他参与字段日期强定招募(内核模块):
    module = 内核模块('公告局部识别')
    text = '活动分为预选期与招募期：\n◆预选期\n报名安排：11月01日 12:00 - 11月03日 03:59\n◆招募期：11月04日 12:00 - 11月08日 03:59'
    result = module.识别局部记录(text, 2026)
    assert result.局部记录[0].角色状态 == '待确认'
    assert result.阶段分组[0]['状态'] == '待核对'
    assert result.阶段分组[0]['缺失标签'] == ['预选期']


def test_待阶段纯日期下一行可关联(内核模块):
    module = 内核模块('公告局部识别')
    result = module.识别局部记录('活动关卡开放时间：\n◆第一段\n11月01日 12:00 - 11月22日 03:59\n开放关卡：【甲】', 2026)
    row, = result.阶段记录
    assert row.时间精度 == '精确' and row.角色状态 == '已确认'
    assert not result.诊断


def test_四级板块保留五级子节(内核模块):
    from datetime import datetime
    module = 内核模块('解析_公告')
    text = ('==总说明==\n'
            '====四级活动====\n活动时间：11月01日 12:00 - 11月29日 03:59\n'
            '=====商店甲=====\n开放时间：11月01日 12:00 - 11月29日 03:59\n'
            '兑换说明：消耗代币兑换\n'
            '====下一活动====\n活动时间：12月01日 12:00 - 12月10日 03:59')
    b = next(b for b in module.抽板块(text, datetime(2026, 11, 1)) if b.标题 == '四级活动')
    assert any(r.对象 == ('商店甲',) for r in b.局部识别.局部记录)
    assert not any('12月01日' in e.文本 for r in b.局部识别.局部记录 for e in r.证据)
    for r in b.局部识别.局部记录:
        for e in r.证据:
            assert text.splitlines()[e.行 - 1] == e.文本


def test_多组流程不跨组补齐阶段或套用总窗(内核模块):
    module = 内核模块('公告局部识别')
    text = ('活动时间：11月01日 12:00 - 11月29日 03:59\n'
            '活动分为预选期与招募期：\n'
            '◆预选期：11月01日 12:00 - 11月03日 03:59\n'
            '活动分为预选期与招募期：\n'
            '◆招募期：11月04日 12:00 - 11月08日 03:59')
    result = module.识别局部记录(text, 2026)
    assert result.阶段分组[0]['缺失标签'] == ['招募期']
    assert result.阶段分组[1]['缺失标签'] == ['预选期']
    assert all(g['状态'] == '待核对' for g in result.阶段分组)
    assert any(i['类型'] == '多组流程窗口口径未确定' for i in result.诊断)
    assert result.窗口一致性['状态'] == '部分无法检查'
    assert not any(i.get('类型') == '阶段范围检查' and i.get('阶段') for i in result.窗口一致性['检查项'])


def test_子对象未知标签精确但角色待确认(内核模块):
    module = 内核模块('公告局部识别')
    result = module.识别局部记录('【商店甲】\n挑战时间：11月01日 12:00 - 11月29日 03:59', 2026)
    row, = result.局部记录
    assert row.时间精度 == '精确' and row.窗口 is not None
    assert row.角色状态 == '待确认'
    assert any(i['类型'] == '未知时间标签' for i in result.诊断)


def test_只有结束端点年份不倒推起年(内核模块):
    module = 内核模块('公告局部识别')
    result = module.识别局部记录('活动时间：12月28日 12:00 - 2027年01月03日 03:59', None)
    row, = result.局部记录
    assert row.窗口 is None and row.时间精度 == '未精确解析'
    assert row.角色状态 == '已确认'
    assert any('缺少年份依据' in i['说明'] for i in result.诊断)
