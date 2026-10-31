from datetime import datetime
import pytest


def make(内核模块, name, start, end='2027-12-01 04:00:00', kind=99):
    return 内核模块('活动').活动(name, datetime.fromisoformat(start), datetime.fromisoformat(end), kind)


@pytest.mark.parametrize('类别', ['剿灭作战', '保全派驻', '生息演算', '集成战略'])
def test_四类轮换顺序无关原始记录不变(内核模块, 类别):
    old = make(内核模块, 类别 + '「旧主题」', '2026-01-01 04:00:00')
    new = make(内核模块, 类别 + '「新主题」', '2026-11-01 16:00:00')
    fn = 内核模块('长期活动').排列轮换
    for rows in ([old, new], [new, old]):
        result = {r.名称: r for r in fn(rows)}
        assert result[old.名称].结束 == new.开始
        assert result[old.名称].时间角色 == '长期轮换'
        assert result[new.名称] == new
    assert old.结束 == datetime(2027, 12, 1, 4)


def test_不跨类不延长同期开启并列卫戍不动(内核模块):
    items = [make(内核模块, '保全派驻「甲」', '2026-01-01 04:00:00'),
             make(内核模块, '保全派驻「乙」', '2026-01-01 04:00:00'),
             make(内核模块, '保全派驻「丙」', '2026-11-01 16:00:00'),
             make(内核模块, '集成战略「某主题」', '2026-02-01 04:00:00', '2026-02-10 04:00:00'),
             make(内核模块, '集成战略「后主题」', '2026-03-01 04:00:00'),
             make(内核模块, '卫戍协议「规程」', '2026-01-01 04:00:00'),
             make(内核模块, '卫戍协议「后序列」', '2026-02-01 04:00:00')]
    result = 内核模块('长期活动').排列轮换(items)
    assert result[0].结束 == result[1].结束 == items[2].开始
    assert result[3:] == items[3:]


def test_赛季序列按下一序列开始截断(内核模块):
    """卫戍协议式赛季：同活动本名的多个序列，旧序列展示到新序列开始（不改来源数据）。"""
    活动 = 内核模块('活动').活动
    旧 = 活动('卫戍协议「规程·序列I」', datetime(2026, 11, 8, 16), datetime(2027, 11, 7, 3, 59),
             99, 活动本名='卫戍协议·规程', 时间角色='长期开放')
    新 = 活动('卫戍协议「规程·序列II」', datetime(2027, 2, 20, 16), datetime(2028, 2, 20, 3, 59),
             99, 活动本名='卫戍协议·规程', 时间角色='长期开放')
    result = 内核模块('长期活动').排列序列([旧, 新])
    assert result[0].结束 == 新.开始 and result[0].名称 == 旧.名称
    assert result[1] == 新
    assert [旧.结束, 新.结束] == [datetime(2027, 11, 7, 3, 59), datetime(2028, 2, 20, 3, 59)]


def test_筛选前计算轮换未来主题图外也截止且CSV不变(tmp_path, 内核模块):
    path = tmp_path / '活动.csv'
    text = '名称,开始时间,结束时间,类型\n集成战略「旧」,2026-01-01 04:00:00,2027-01-01 04:00:00,99\n集成战略「新」,2026-11-10 16:00:00,2027-11-10 04:00:00,99\n'
    path.write_text(text, encoding='utf-8')
    rows = 内核模块('筛选_活动').preprocess_data(str(path), now=datetime(2026, 11, 1), right_border=datetime(2026, 11, 5))
    assert len(rows) == 1 and rows[0].结束 == datetime(2026, 11, 10, 16)
    assert path.read_text(encoding='utf-8') == text
    # 长期活动的结束只是轮换/占位，不再发结束提醒（2026-10-31 定）
    reminder = 内核模块('生成_提醒').生成提醒(rows, datetime(2026, 11, 9))
    assert reminder == ''
    after = 内核模块('筛选_活动').preprocess_data(str(path), now=datetime(2026, 11, 11), right_border=datetime(2026, 11, 20))
    assert [r.名称 for r in after] == ['集成战略「新」']


def test_长期结束不提醒但开始提醒保留(内核模块):
    """开始提醒（新轮换/新序列开启）仍然有效，只砍结束提醒。"""
    旧 = make(内核模块, '集成战略「旧主题」', '2026-01-01 04:00:00', '2027-01-01 04:00:00')
    新 = make(内核模块, '集成战略「新主题」', '2026-11-11 16:00:00', '2027-11-11 04:00:00')
    提醒 = 内核模块('生成_提醒').生成提醒([旧, 新], datetime(2026, 11, 11))
    assert '新主题' in 提醒 and '今天开启' in 提醒
    结束日 = 内核模块('生成_提醒').生成提醒([旧], datetime(2026, 12, 29))
    assert 结束日 == ''
