import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / 'skills/fmg-research/scripts'


def module():
    spec = importlib.util.spec_from_file_location('completion', SCRIPTS / 'completion.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def record(platform='twitch', value=123):
    return {'creator': {'platform': platform}, 'metrics': {'followers': {
        'status': 'found', 'value': value, 'metric': 'followers',
        'source': 'evidence/followers.json', 'checked_at': '2026-09-22T01:00:00Z',
    }}}


def test_unqueried_unknown_is_not_complete():
    assert module().followers_errors({'presentation': {'followers': 'Unknown — 未查询'}})


def test_zero_is_valid_but_missing_negative_boolean_are_not():
    check = module().followers_errors
    assert check(record(value=0)) == []
    for value in (None, -1, True, '100', 1.5):
        assert check(record(value=value))


def test_platform_metric_and_evidence_required():
    check = module().followers_errors
    item = record('youtube')
    assert check(item)
    item['metrics']['followers']['metric'] = 'subscribers'
    assert check(item) == []
    del item['metrics']['followers']['source']
    assert check(item)


def test_queried_unavailable_is_distinct_from_failed():
    check = module().followers_errors
    item = record(value=None)
    item['metrics']['followers'].update(status='unavailable', reason='hidden_by_platform')
    assert check(item) == []
    for state in ('pending', 'blocked', 'failed', 'not_requested'):
        item['metrics']['followers']['status'] = state
        assert check(item)


def test_unknown_requires_reason_and_timestamp():
    item = record(value=None)
    item['metrics']['followers']['status'] = 'unavailable'
    assert module().followers_errors(item)
    item['metrics']['followers']['reason'] = 'not_exposed'
    item['metrics']['followers']['checked_at'] = 'yesterday'
    assert module().followers_errors(item)
