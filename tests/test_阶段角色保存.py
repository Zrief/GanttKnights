"""真实阶段生成→正式保存→业务模型→节点提醒端到端。"""
from datetime import datetime
from pathlib import Path
import csv


def test_19行快照添明确角色不改身份窗口(tmp_path, 内核模块):
    api = 内核模块('解析_API活动')
    store = 内核模块('汇总_活动')
    parse = 内核模块('筛选_活动')
    root = Path(__file__).parents[1]
    path = tmp_path/'role.csv'
    path.write_bytes((root/'tests'/'fixtures'/'身份快照_19行.csv').read_bytes())
    text = (root/'tests'/'fixtures'/'局部识别'/'感谢庆典2026.wikitext').read_text(encoding='utf-8')
    rows = api.认领与生成([], {'感谢庆典2026/活动公告':api.抽板块(text,datetime(2026,11,1))})
    generated = [r for r in rows if r.get('_运行时身份') and r.get('_原角色')]
    with path.open(encoding='utf-8-sig',newline='') as f:
        baseline=list(csv.DictReader(f))
    assert len(baseline)==19 and not any(r['名称'].endswith('·商店') for r in baseline)
    before={r['身份']:(r['开始时间'],r['结束时间']) for r in baseline if r['身份']}
    store.合并保存CSV(generated,path,'2026-11-01 12:00:00')
    with path.open(encoding='utf-8-sig',newline='') as f:
        current=list(csv.DictReader(f))
    assert len(current)==20
    current_windows={r['身份']:(r['开始时间'],r['结束时间']) for r in current if r['身份']}
    assert {identity:current_windows[identity] for identity in before}==before
    shops=[r for r in current if r['名称'].endswith('·商店')]
    assert len(shops)==1
    shop=shops[0]
    assert shop['名称']=='SideStory「时间啊，向前！」·商店'
    assert set(current_windows)-set(before)=={shop['身份']}
    assert '炮火所掩埋的' in shop['身份']
    assert (shop['开始时间'],shop['结束时间'])==('2026-11-01 12:00:00','2026-11-29 03:59:00')
    assert shop['时间角色']=='兑换开放' and shop['阶段序号']=='0'
    assert {r['名称'] for r in current}=={r['名称'] for r in baseline}|{shop['名称']}
    assert {r['名称']:(r['开始时间'],r['结束时间']) for r in current if r['名称']!=shop['名称']}=={
        r['名称']:(r['开始时间'],r['结束时间']) for r in baseline}
    models,bad=parse._读CSV(path)
    assert len(models)==20 and bad==0
    shop_models=[r for r in models if r.时间角色=='兑换开放']
    assert len(shop_models)==1 and shop_models[0].阶段序号==0
    stages=[r for r in models if r.时间角色=='关卡开放']
    assert len(stages)==3 and len({r.活动关联 for r in stages})==1
    assert {r.活动本名 for r in stages}=={'SideStory「时间啊，向前！」'}
    assert sorted(r.阶段序号 for r in stages)==[1,2,3]
    first = next(r for r in current if r['阶段序号']=='1')
    store.合并保存CSV([dict(名称=first['名称'],开始时间=first['开始时间'],结束时间=first['结束时间'],
                          类型=1,_parent=first['来源'],_运行时身份=first['身份'])],path,'2026-11-01 12:00:00')
    refreshed,bad=parse._读CSV(path)
    assert bad==0 and len(refreshed)==20 and sum(r.时间角色=='关卡开放' for r in refreshed)==3
    assert sum(r.时间角色=='兑换开放' for r in refreshed)==1
    original = path.read_bytes()
    import pytest
    with pytest.raises(store.身份冲突):
        store.合并保存CSV([dict(名称=first['名称'],开始时间=first['开始时间'],结束时间=first['结束时间'],
                              类型=1,_parent=first['来源'],_运行时身份=first['身份'],_活动本名='')],
                        path,'2026-11-01 12:00:00')
    assert path.read_bytes()==original
