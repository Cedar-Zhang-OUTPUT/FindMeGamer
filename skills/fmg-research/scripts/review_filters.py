"""Local research-filter contract; no provider calls. Python 3.10+."""
from copy import deepcopy

PLATFORMS = ['youtube', 'x', 'twitch']
LANGUAGES = dict(zip(
    ['en','ja','ko','zh-Hans','zh-Hant','es','pt','fr','de','it','ru','ar','id','th','vi'],
    ['英语','日语','韩语','简体中文','繁体中文','西班牙语','葡萄牙语','法语','德语','意大利语','俄语','阿拉伯语','印尼语','泰语','越南语']))
REGIONS = dict(zip(
    'US CA GB AU NZ JP KR DE FR IT ES PT NL SE NO DK FI PL BR MX IN ID TH VN MY SG PH TR SA AE'.split(),
    '美国 加拿大 英国 澳大利亚 新西兰 日本 韩国 德国 法国 意大利 西班牙 葡萄牙 荷兰 瑞典 挪威 丹麦 芬兰 波兰 巴西 墨西哥 印度 印度尼西亚 泰国 越南 马来西亚 新加坡 菲律宾 土耳其 沙特阿拉伯 阿联酋'.split()))
EN_REGIONS = 'United States|Canada|United Kingdom|Australia|New Zealand|Japan|South Korea|Germany|France|Italy|Spain|Portugal|Netherlands|Sweden|Norway|Denmark|Finland|Poland|Brazil|Mexico|India|Indonesia|Thailand|Vietnam|Malaysia|Singapore|Philippines|Turkey|Saudi Arabia|United Arab Emirates'.split('|')
ALIASES = {name.casefold(): code for code,name in REGIONS.items()}
ALIASES.update({name.casefold(): code for code,name in zip(REGIONS,EN_REGIONS)})
ALIASES.update({code.casefold():code for code in REGIONS})
ALIASES.update({'uk':'GB','usa':'US','uae':'AE'})
PRESETS = {'under1k':[0,999], '1k10k':[1000,9999], '10k50k':[10000,49999],
           '50k100k':[50000,99999], '100k500k':[100000,499999],
           '500k1m':[500000,999999], '1mplus':[1000000,None]}


def defaults():
    return {'platforms':PLATFORMS.copy(), 'languages':[], 'language_other':[],
            'regions':{'mode':'any','codes':[],'pending':[],'include_unknown':True},
            'followers':{'mode':'any','presets':[],'min':None,'max':None,'include_unknown':True},
            'keywords':[], 'contact':'any', 'target_per_platform':10, 'target_total':None}


def strings(value):
    if not isinstance(value,list) or len(value)>100 or any(not isinstance(v,str) or len(v)>300 for v in value):
        raise ValueError('Invalid text list')
    return list(dict.fromkeys(v.strip() for v in value if v.strip()))


def integer(value):
    if value is not None and (type(value) is not int or value<0 or value>9007199254740991):
        raise ValueError('Counts must be non-negative integers')
    return value


def validate(value):
    if not isinstance(value,dict): raise ValueError('Invalid filters')
    v=defaults(); v.update(deepcopy(value))
    v['platforms']=strings(v['platforms'])
    if not v['platforms'] or set(v['platforms'])-set(PLATFORMS): raise ValueError('Select supported platforms')
    v['languages']=strings(v['languages'])
    if set(v['languages'])-set(LANGUAGES): raise ValueError('Use additional-language text for other languages')
    for key in ('language_other','keywords'): v[key]=strings(v[key])
    if v['contact'] not in ('any','has_email'): raise ValueError('Invalid email filter')
    for key in ('target_per_platform','target_total'):
        integer(v[key])
        if v[key] is not None and v[key]<1: raise ValueError('Target must be positive')
    if v['target_total'] is None and v['target_per_platform'] is None: raise ValueError('Missing target')
    r=v['regions']
    if not isinstance(r,dict) or r.get('mode') not in ('any','specific'): raise ValueError('Invalid region mode')
    if type(r.get('include_unknown',False)) is not bool: raise ValueError('Invalid unknown-region flag')
    codes=strings(r.get('codes',[]))
    if set(codes)-set(REGIONS): raise ValueError('Unknown region code')
    pending=[]
    for label in strings(r.get('pending',[])):
        code=ALIASES.get(label.casefold())
        if code:
            if code not in codes: codes.append(code)
        elif label.casefold() not in [s.casefold() for s in pending]: pending.append(label)
    if r['mode']=='any': codes=[]; pending=[]
    elif not codes and not pending: raise ValueError('Select a region or use any')
    v['regions']={'mode':r['mode'],'codes':codes,'pending':pending,'include_unknown':True if r['mode']=='any' else r.get('include_unknown',False)}
    f=v['followers']
    if not isinstance(f,dict) or f.get('mode') not in ('any','presets','custom'): raise ValueError('Invalid follower mode')
    if type(f.get('include_unknown',False)) is not bool: raise ValueError('Invalid unknown-count flag')
    presets=strings(f.get('presets',[])); low=integer(f.get('min')); high=integer(f.get('max'))
    if f['mode']=='presets' and (not presets or set(presets)-set(PRESETS)): raise ValueError('Select follower ranges')
    if f['mode']=='custom' and (low is None and high is None or low is not None and high is not None and low>high):
        raise ValueError('Provide a valid inclusive range')
    v['followers']={'mode':f['mode'],'presets':presets if f['mode']=='presets' else [],
                    'min':low if f['mode']=='custom' else None,'max':high if f['mode']=='custom' else None,
                    'include_unknown':True if f['mode']=='any' else f.get('include_unknown',False)}
    return v


def matches_count(count, rule):
    if rule['mode']=='any': return True
    if count is None: return rule['include_unknown']
    integer(count)
    ranges=[PRESETS[k] for k in rule['presets']] if rule['mode']=='presets' else [[rule['min'] or 0,rule['max']]]
    return any(count>=low and (high is None or count<=high) for low,high in ranges)
