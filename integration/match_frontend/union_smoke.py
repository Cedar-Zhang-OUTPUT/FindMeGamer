"""Real API/worker/DB union flow with only synthetic upstream responses."""
import json
from pathlib import Path
import sys

from manage import load_owned, private_write, request
from smoke import event_counts, new_plan, ready_plan, settled_query, poll, require
from fixture import DEFAULT_CONTROL, write_control

PIN = '28595d84805137dabbdadd31f26f9fa5b51d988b'


def run(directory):
    config = load_owned(directory)
    require(config['backend_revision'] == PIN, 'Wrong owned fixture revision')
    before = event_counts(directory)
    saved = []
    for platform, account, url in [
        ('youtube', 'UCmatchA001', 'https://www.youtube.com/channel/UCmatchA001'),
        ('twitch', '987654321', 'https://www.twitch.tv/syntheticgarden'),
        ('instagram', None, 'https://www.instagram.com/syntheticgarden'),
    ]:
        saved.append(request(config, 'POST', '/api/v2/library/creators', {
            'platform': platform, 'account_id': account, 'profile_url': url,
            'name': 'Synthetic saved garden creator', 'description': 'Saved cooperative garden content.',
        }))
    activity = request(config, 'POST', '/api/v2/activities', {
        'game_id': config['game_id'], 'name': 'Library plus live union acceptance',
        'reference_work_ids': config['reference_work_ids'],
    })
    accepted = new_plan(config, activity['id'], target=100,
                        platforms=['youtube', 'x', 'twitch', 'instagram'])
    plan = ready_plan(config, accepted['plan_id'])
    require(plan['status'] == 'ready', 'Four-platform planning failed')
    query = settled_query(config, plan['query_id'])
    require(query['status'] == 'completed' and query['result_count'] == 8, 'Union result count incorrect')
    rows = request(config, 'GET', f"/api/v2/discovery/queries/{query['id']}/results")['items']
    require(len({(r['platform'], r['account_id']) for r in rows}) == 8, 'Duplicate account')
    overlap = next(r for r in rows if r['account_id'] == 'UCmatchA001')
    require(overlap['filter_notes']['discovery_sources'] == ['library', 'realtime'], 'Missing union provenance')
    for platform in ('twitch', 'instagram'):
        source = query['sources'][platform]
        require(source['status'] == 'not_supported' and source['library']['status'] == 'complete', 'Live and Library state conflated')
        require(set(source['library']) == {'status', 'scanned_count', 'added_count'}, 'Private cursor exposed')
    require(all(not r['identity_changed'] for r in rows), 'URL-only saved creator lost identity')
    require({r['creator_id'] for r in rows}.issuperset({s['id'] for s in saved}), 'Saved records missing')
    stable = {r['id'] for r in rows}
    request(config, 'POST', f"/api/v2/discovery/queries/{query['id']}/continue", {})
    settled_query(config, query['id'])
    again = request(config, 'GET', f"/api/v2/discovery/queries/{query['id']}/results")['items']
    require({r['id'] for r in again} == stable, 'Explicit append repeated candidates')
    accepted_eval = request(config, 'POST', f"/api/v2/discovery/queries/{query['id']}/evaluations", {})
    path = f"/api/v2/discovery/evaluations/{accepted_eval['evaluation_id']}"
    evaluated = poll(config, path, lambda value: value['status'] not in {'queued', 'running'})
    require(evaluated['status'] == 'completed' and evaluated['matched_count'] == 8, 'Unified evaluation failed')
    results = request(config, 'GET', path + '/results')['items']
    require(all(not r['sender_watched'] and r['match_brief']['confidence'] == 'limited' for r in results), 'Metadata fabricated viewing evidence')
    delta = dict(event_counts(directory) - before)
    require(delta == {'planning': 1, 'youtube': 2, 'youtube_channels': 2, 'x': 2, 'screening': 1, 'deep': 8, 'ranking': 1}, 'Unexpected upstream requests')
    report = {'backend_revision': PIN, 'activity_id': activity['id'], 'plan_id': plan['id'],
              'query_id': query['id'], 'evaluation_id': evaluated['id'], 'result_count': 8,
              'synthetic_upstream_calls': delta, 'checks': ['four_platform_union', 'library_live_dedup',
              'url_only_library_identity', 'source_state_separation', 'explicit_append_no_duplicates',
              'unified_evaluation_no_viewing_claim', 'no_smtp']}
    private_write(directory / 'union-report.json', json.dumps(report, indent=2) + '\n')
    return report


def source_checks(directory):
    config = load_owned(directory)
    require(config['backend_revision'] == PIN, 'Wrong owned fixture revision')
    report = json.loads((directory / 'union-report.json').read_text())
    original = request(config, 'GET', '/api/v1/settings/collection')
    youtube_enabled = next(row['enabled'] for row in original['items'] if row['platform'] == 'youtube')
    try:
        request(config, 'PUT', '/api/v1/settings/collection/youtube', {'enabled': False})
        before = event_counts(directory)
        accepted = new_plan(config, report['activity_id'], target=100, platforms=['youtube'])
        plan = ready_plan(config, accepted['plan_id'])
        require(plan['status'] == 'ready', 'Disabled-platform planning failed')
        query = settled_query(config, plan['query_id'])
        require(query['result_count'] == 3 and query['status'] == 'paused', 'Disabled collection lost Library candidates')
        require(query['sources']['youtube']['blocked_reason'] == 'collection_disabled', 'Disabled state missing')
        require(dict(event_counts(directory) - before) == {'planning': 1}, 'Disabled provider made upstream requests')
        report['disabled_query_id'] = query['id']
    finally:
        request(config, 'PUT', '/api/v1/settings/collection/youtube', {'enabled': youtube_enabled})
    try:
        write_control(directory / 'state', DEFAULT_CONTROL | {'source_fail': 'youtube'})
        accepted = new_plan(config, report['activity_id'], target=100, platforms=['youtube', 'x'])
        plan = ready_plan(config, accepted['plan_id'])
        require(plan['status'] == 'ready', 'Source-failure planning failed')
        query = settled_query(config, plan['query_id'])
        require(query['result_count'] == 6 and query['status'] == 'paused', 'Source failure erased Library or hid failure')
        require(query['sources']['youtube']['status'] == 'failed' and query['sources']['x']['status'] == 'exhausted', 'One failed source stopped the other')
        report['failed_source_query_id'] = query['id']
    finally:
        write_control(directory / 'state', DEFAULT_CONTROL)
    report['checks'] += ['disabled_live_keeps_library_no_provider_calls', 'failed_live_keeps_library_and_other_source']
    private_write(directory / 'union-report.json', json.dumps(report, indent=2) + '\n', replace=True)
    return report


if __name__ == '__main__':
    operation = source_checks if sys.argv[2:] == ['sources'] else run
    print(json.dumps(operation(Path(sys.argv[1]).absolute()), indent=2))
