import importlib.util
import json
from pathlib import Path
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'skills/fmg-research/scripts'
sys.path.insert(0, str(SCRIPTS))


def module():
    import review_filters
    return review_filters


def test_default_scope_and_independent_unknowns():
    m = module()
    v = m.validate(m.defaults())
    assert v['platforms'] == ['youtube', 'x', 'twitch']
    assert v['target_per_platform'] == 10 and v['target_total'] is None
    assert v['followers']['include_unknown'] and v['regions']['include_unknown']
    assert v['contact'] == 'any'
    v['languages'] = ['ja']
    assert m.validate(v)['regions']['codes'] == []


def test_presets_union_and_custom_boundaries():
    m = module(); v = m.defaults()
    v['followers'] = {'mode':'presets','presets':['under1k','10k50k'],'min':None,'max':None,'include_unknown':False}
    f = m.validate(v)['followers']
    assert m.matches_count(999,f) and not m.matches_count(1000,f)
    assert m.matches_count(10000,f) and m.matches_count(49999,f)
    assert not m.matches_count(50000,f) and not m.matches_count(None,f)
    v['followers'] = {'mode':'custom','presets':[],'min':0,'max':0,'include_unknown':True}
    f = m.validate(v)['followers']
    assert m.matches_count(0,f) and m.matches_count(None,f) and not m.matches_count(1,f)


@pytest.mark.parametrize('change', [
    {'platforms':[]}, {'platforms':['instagram']}, {'contact':'needs_email'},
    {'followers':{'mode':'custom','min':None,'max':None}},
    {'followers':{'mode':'custom','min':4,'max':3}},
    {'followers':{'mode':'custom','min':1.5,'max':3}},
    {'followers':{'mode':'custom','min':True,'max':3}},
    {'followers':{'mode':'custom','min':-1,'max':3}},
])
def test_invalid_filters_rejected(change):
    m=module(); v=m.defaults(); v.update(change)
    with pytest.raises(ValueError): m.validate(v)


def test_region_aliases_and_unconfirmed_tags():
    m=module(); v=m.defaults()
    v['regions']={'mode':'specific','codes':['US'],'pending':['加拿大','CA','Atlantis',' '],'include_unknown':False}
    r=m.validate(v)['regions']
    assert r['codes']==['US','CA'] and r['pending']==['Atlantis']
