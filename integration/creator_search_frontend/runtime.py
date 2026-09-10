"""Isolated UI fixture: real API/DB/orchestrator, synthetic providers, no SMTP.

This deliberately is not evidence of a live provider or broker deployment.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from uuid import UUID

private = json.loads(Path('/private/client.json').read_text())
from app.core.security import hash_workspace_key
os.environ['WORKSPACE_ACCESS_KEY_HASH'] = hash_workspace_key(private['workspace_key'])

from app.core.database import session_scope
from app.core.idempotency import utc_now
from app.db.models.creator_search import CreatorSearchUnit
from app.db.models.profiles import CreatorProfile, CreatorContact, GameProfile
from app.schemas.discovery import DiscoveryPage, DiscoveredAccount, DiscoveredContent
from app.schemas.discovery_plan_output import SearchPlanOutput
from app.workers.creator_search_tasks import run_creator_search
from tests.integration.test_discovery_evaluation import fixture_executor
from tests.integration.test_analyze_vertical_slice import AllowAllRateLimiter


class Provider:
    def discover(self, request):
        time.sleep(.3)
        accounts, works = [], []
        for index in range(1, 4):
            aid = f'UCsearchFixture{index:03}' if request.platform == 'youtube' else str(990000 + index)
            url = (f'https://www.youtube.com/channel/{aid}' if request.platform == 'youtube'
                   else f'https://x.com/i/user/{aid}')
            accounts.append(DiscoveredAccount(platform=request.platform, account_id=aid,
                profile_url=url, display_name=f'Synthetic {request.platform} Creator {index}',
                description='Synthetic cozy game reviewer; local UI fixture only.',
                follower_count=10000*index, collected_at=utc_now()))
            works.append(DiscoveredContent(platform=request.platform, content_id=f'fixture{index}',
                account_id=aid, source_url=url, title='Synthetic cozy game review',
                text='Synthetic cooperative gardening review.', language='en', collected_at=utc_now()))
        return DiscoveryPage(platform=request.platform, accounts=accounts, contents=works,
            status='complete', requests_used=1, provider_items_received=3,
            coverage='search_index' if request.platform == 'youtube' else 'recent_7_days')


@contextmanager
def providers(platform):
    yield Provider()


def plan(snapshot, conditions, model):
    time.sleep(.3)
    return SearchPlanOutput.model_validate({
        'summary':'Synthetic local search; no live model request.',
        'rationale':'Exercise the complete client workflow.',
        'queries':[{'platform':p, 'terms':['cozy games']} for p in conditions['platforms']],
    })


def enrich_profile(uid):
    time.sleep(.5)
    with session_scope() as session:
        unit = session.get(CreatorSearchUnit, uid)
        profile = session.get(CreatorProfile, unit.creator_id)
        if profile.last_analyzed_at and profile.analysis:
            return 'reused'
        profile.analysis = {'summary':'Synthetic analysis of cozy cooperative games.'}
        profile.brief = {'summary':'Synthetic creator focused on cozy games.'}
        profile.last_analyzed_at = utc_now()
        profile.source_status = {**profile.source_status, 'fixture':'synthetic'}
    return 'ready'


def enrich_email(uid):
    time.sleep(.3)
    with session_scope() as session:
        unit = session.get(CreatorSearchUnit, uid)
        profile = session.get(CreatorProfile, unit.creator_id)
        if unit.account_id.endswith('3'):
            return 'missing'
        if not profile.contacts:
            session.add(CreatorContact(creator_id=profile.id, identity_revision=profile.identity_revision,
                email=f'synthetic-{unit.platform}-{unit.account_id}@example.org',
                purpose='Synthetic business contact; do not send', source_type='manual',
                is_manual=True, validation_state='unverified'))
    return 'available'


def main():
    from alembic import command
    from alembic.config import Config
    import uvicorn
    from app.main import create_app
    command.upgrade(Config('/app/alembic.ini'), 'head')
    with session_scope() as session:
        identity = UUID('10000000-0000-4000-8000-000000000022')
        if not session.get(GameProfile, identity):
            session.add(GameProfile(id=identity, sort_name='Synthetic Star Garden',
                canonical_url='https://store.steampowered.com/app/999999991',
                steam_app_id='999999991',
                current_facts={'name':'Synthetic Star Garden', 'short_description':'A synthetic cozy cooperative gardening game.'},
                analysis={'summary':'Synthetic local UI fixture.'}, brief={'summary':'Grow a garden together.'}))
    pool = ThreadPoolExecutor(max_workers=2)
    app = create_app(rate_limiter=AllowAllRateLimiter())
    app.state.creator_search_dispatch = lambda uid: pool.submit(
        run_creator_search, uid, plan_generator=plan, gateway_factory=providers,
        profile_runner=enrich_profile, email_runner=enrich_email,
        execute_model=fixture_executor([]),
    )
    uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
