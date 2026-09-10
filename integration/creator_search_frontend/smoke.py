"""Exercise only the isolated localhost creator-search UI fixture."""
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from integration.match_frontend.manage import request


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    if urlsplit(config['base_url']).hostname != '127.0.0.1':
        raise ValueError('This smoke is restricted to an isolated localhost fixture')
    session = request(config, 'GET', '/api/v1/session')
    assert not any(session['service_connections'].values())
    activity = request(config, 'POST', '/api/v2/activities', {
        'game_id':'10000000-0000-4000-8000-000000000022', 'name':'Synthetic one-click smoke',
    })
    receipt = request(config, 'POST', f"/api/v2/activities/{activity['id']}/creator-searches", {
        'platforms':['youtube','x'], 'mode':'discover',
    })
    route = '/api/v2/creator-searches/' + receipt['search_id']
    for attempt in range(100):
        result = request(config, 'GET', route)
        if result['status'] not in {'queued','running','stopping'}:
            break
        time.sleep(.2)
    assert result['status'] == 'completed', result
    assert result['counts']['matched'] == 6, result
    assert result['counts']['email_available'] == 4, result
    assert result['counts']['email_missing'] == 2, result
    units = request(config, 'GET', route+'/creators?limit=100')
    assert units['total'] == 6
    results = request(config, 'GET', f"/api/v2/discovery/evaluations/{result['evaluation_id']}/results?limit=100")
    assert results['total'] == 6
    print('PASS: isolated HTTP create→discover→profiles→emails→match; 6 matches, 4 email available, 2 missing; no live providers or SMTP.')


if __name__ == '__main__':
    main()
