"""阶段元数据局部更新与重复序号不得造成错误共同结束。"""
from datetime import datetime
import csv
import pytest


def row(key='a', sequence=1):
    return dict(名称=f'阶段{sequence}', 开始时间='2026-11-01 12:00:00',
                结束时间='2026-11-22 03:59:00', 类型=1, _运行时身份=key,
                _活动关联='same-block', _活动本名='SideStory「测试」',
                _原角色='关卡开放', _阶段序号=sequence)


def test_合法阶段序号局部更新继承其它业务字段(tmp_path, 内核模块):
    store=内核模块('身份CSV存储')
    path=tmp_path/'x.csv'
    store.保存身份CSV([row()],path,'2026-11-01 12:00:00')
    patch=row(); patch.pop('_原角色'); patch.pop('_活动关联'); patch.pop('_活动本名')
    patch['_阶段序号']=2
    store.保存身份CSV([patch],path,'2026-11-01 12:00:00')
    with path.open(encoding='utf-8-sig',newline='') as f:
        after=list(csv.DictReader(f))[0]
    assert after['阶段序号']=='2' and after['时间角色']=='关卡开放'
    assert after['活动关联']=='same-block'


def test_同关联重复序号拒绝且原件未变(tmp_path, 内核模块):
    store=内核模块('身份CSV存储')
    path=tmp_path/'x.csv'
    store.保存身份CSV([row()],path,'2026-11-01 12:00:00')
    before=path.read_bytes()
    with pytest.raises(store.身份存储冲突,match='阶段序号重复'):
        store.保存身份CSV([row('b')],path,'2026-11-01 12:00:00')
    assert path.read_bytes()==before


def test_提醒重复序号不假装多个阶段共同结束(内核模块):
    model=内核模块('活动').活动
    reminders=内核模块('生成_提醒')
    a=model('阶段甲',datetime(2026,11,1),datetime(2026,11,22,3,59),1,
            活动关联='same-block',活动本名='测试',时间角色='关卡开放',阶段序号=1)
    b=model('阶段乙',datetime(2026,11,8),datetime(2026,11,22,3,59),1,
            活动关联='same-block',活动本名='测试',时间角色='关卡开放',阶段序号=1)
    text=reminders.生成提醒([a,b],datetime(2026,11,19))
    assert '共同结束' not in text and '阶段甲' in text and '阶段乙' in text
