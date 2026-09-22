import json
import sys
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'skills/fmg-research/scripts'
sys.path.insert(0, str(SCRIPTS))


def test_review_preserves_confirmation_and_rejects_stale_profile(tmp_path):
    import game_review as review
    run = tmp_path / 'runs/test'
    run.mkdir(parents=True)
    (tmp_path / 'game-profile.md').write_text('# Test game\nSource facts and interpretations')
    (run / 'search-intent.json').write_text('{}')
    proposal = review.proposal(tmp_path, 'test')
    assert review.confirmation(tmp_path, 'test') is None
    saved = review.save(tmp_path, 'test', {'revision': proposal['revision'],
        'filters': proposal['filters'], 'corrections': 'Focus on co-op'})
    assert saved['status'] == 'approved'
    assert saved['corrections'] == 'Focus on co-op'
    assert review.confirmation(tmp_path, 'test') == saved
    with pytest.raises(ValueError):
        review.save(tmp_path, 'test', {'revision': 'stale', 'filters': proposal['filters']})
    (tmp_path / 'game-profile.md').write_text('# Different game')
    assert review.confirmation(tmp_path, 'test') is None
    assert json.loads((run / 'game-confirmation.json').read_text()) == saved


def test_pending_regions_and_outside_workspace_rejected(tmp_path):
    import game_review as review
    run = tmp_path / 'runs/test'
    run.mkdir(parents=True)
    (tmp_path / 'game-profile.md').write_text('# Game')
    (run / 'search-intent.json').write_text('{}')
    p = review.proposal(tmp_path, 'test')
    p['filters']['regions'].update(mode='specific', pending=['Atlantis'])
    with pytest.raises(ValueError, match='region'):
        review.save(tmp_path, 'test', {'revision': p['revision'], 'filters': p['filters']})
    with pytest.raises(ValueError):
        review.proposal(tmp_path, '../outside')
