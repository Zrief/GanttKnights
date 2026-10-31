from datetime import datetime
from pathlib import Path
import csv


def test_真实SS三战斗加商店保存提醒独立(tmp_path, 内核模块):
    text = (Path(__file__).parent / 'fixtures/局部识别/感谢庆典2026.wikitext').read_text(encoding='utf-8')
    parser = 内核模块('解析_公告')
    blocks = parser.抽板块(text, datetime(2026, 11, 1))
    ss = next(b for b in blocks if 'SideStory' in b.标题)
    batch = 内核模块('解析_API活动').认领与生成([], {'感谢庆典2026/活动公告': [ss]})
    assert len(batch) == 4
    shop = next(r for r in batch if r['名称'].endswith('·商店'))
    assert '炮火所掩埋的' not in shop['名称']
    assert shop['开始时间'] == '2026-11-01 12:00:00' and shop['结束时间'] == '2026-11-29 03:59:00'
    assert shop['_原角色'] == '兑换开放' and shop['_阶段序号'] == 0
    assert '炮火所掩埋的' in shop['_运行时身份']
    path = tmp_path / '活动.csv'
    内核模块('汇总_活动').合并保存CSV(batch, path, '2026-11-01 12:00:00')
    rows, bad = 内核模块('筛选_活动')._读CSV(path)
    assert len(rows) == 4 and bad == 0
    remind = 内核模块('生成_提醒').生成提醒
    battle = remind(rows, datetime(2026, 11, 21))
    assert '商店' not in battle
    shop_reminder = remind(rows, datetime(2026, 11, 28))
    assert '商店' in shop_reminder and '阶段' not in shop_reminder


def test_SS没有兑换窗口不凭战斗时间补商店(内核模块):
    parser = 内核模块('解析_公告')
    text = ('==SideStory「测试」活动关卡开启==\n活动时间：11月01日 12:00 - 11月22日 03:59\n'
            '【商店名称】\n兑换说明：消耗活动道具兑换奖励\n')
    batch = 内核模块('解析_API活动').认领与生成([], {'页': parser.抽板块(text, datetime(2026, 11, 1))})
    assert batch and not any(r['名称'].endswith('·商店') for r in batch)


def test_主动排除只匹配独立标题不丢奖励主体(tmp_path, 内核模块):
    parser = 内核模块('解析_公告')
    text = ('==「庆典」，主题场景复刻==\n活动时间：11月01日 12:00 - 11月29日 03:59\n'
            '==「全息作战矩阵」重构批次#2开放==\n开放时间：11月01日 12:00\n'
            '==「正常活动」活动开启==\n活动时间：11月01日 12:00 - 11月29日 03:59\n主要奖励：主题场景【奖励】\n')
    batch = 内核模块('解析_API活动').认领与生成([], {'公告/活动公告': parser.抽板块(text, datetime(2026, 11, 1))})
    assert [r['名称'] for r in batch] == ['正常活动'] and not batch.更新问题
    path = tmp_path / '旧.csv'
    path.write_text('名称,开始时间,结束时间,类型\n主题场景复刻,2026-11-01 12:00:00,2026-11-29 03:59:00,1\n', encoding='utf-8')
    assert not 内核模块('筛选_活动').preprocess_data(str(path), now=datetime(2026, 11, 2))
