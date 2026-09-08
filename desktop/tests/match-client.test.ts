import { describe, expect, it, vi } from 'vitest';
import { MatchClient } from '../src/main/match-client';
import { ACTIVITY_ID as A, BATCH_ID as B, CANDIDATE_ID as C, EVALUATION_ID as E, GAME_ID as G, PLAN_ID as P, QUERY_ID as Q, STEP_ID as S, activityDetailFixture, activityFixture, candidateFixture, evaluationFixture, evaluationResultFixture, matchPage, planCreateFixture, planFixture, queryFixture } from './match-fixtures';
const key = 'match-operation-123';
const activities = '/api/v2/activities', discovery = '/api/v2/discovery';

describe('Match client v2 boundary', () => {
  it('routes every read with the correct ownership and bounded pagination', async () => {
    const cases = [
      [(c: MatchClient) => c.activities({}), activityFixture(), { method: 'GET', path: activities, query: { offset: '0', limit: '50' } }, true],
      [(c: MatchClient) => c.activity(A), activityDetailFixture(), { method: 'GET', path: `${activities}/${A}` }, false],
      [(c: MatchClient) => c.plans({ activityId: A, limit: 200 }), planFixture(), { method: 'GET', path: `${activities}/${A}/discovery-plans`, query: { offset: '0', limit: '200' } }, true],
      [(c: MatchClient) => c.plan(P), planFixture(), { method: 'GET', path: `${discovery}/plans/${P}` }, false],
      [(c: MatchClient) => c.query(Q), queryFixture(), { method: 'GET', path: `${discovery}/queries/${Q}` }, false],
      [(c: MatchClient) => c.candidates({ queryId: Q }), candidateFixture(), { method: 'GET', path: `${discovery}/queries/${Q}/results`, query: { offset: '0', limit: '50' } }, true],
      [(c: MatchClient) => c.evaluations({ queryId: Q }), evaluationFixture(), { method: 'GET', path: `${discovery}/queries/${Q}/evaluations`, query: { offset: '0', limit: '50' } }, true],
      [(c: MatchClient) => c.evaluation(E), evaluationFixture(), { method: 'GET', path: `${discovery}/evaluations/${E}` }, false],
      [(c: MatchClient) => c.evaluationResults({ id: E }), evaluationResultFixture(), { method: 'GET', path: `${discovery}/evaluations/${E}/results`, query: { offset: '0', limit: '50' } }, true],
    ] as const;
    for (const [call, item, route, paged] of cases) {
      const response = paged ? matchPage(item, 'query' in route ? Number(route.query.limit) : 50) : item;
      const request = vi.fn().mockResolvedValue(response);
      expect(await call(new MatchClient(request))).toEqual(response);
      expect(request).toHaveBeenCalledExactlyOnceWith(route);
    }
  });
  it('preserves exact POST bodies, repeated keys and bodyless retry/stop', async () => {
    const data = Object.freeze({ mode: 'discover' as const, platforms: ['youtube' as const], filters: { include_unknown_country: false } });
    const cases = [
      [(c: MatchClient) => c.createActivity({ data: { game_id: G, name: '  Named activity  ' }, idempotencyKey: key }), activityFixture(), `${activities}`, { game_id: G, name: '  Named activity  ' }],
      [(c: MatchClient) => c.createPlan({ activityId: A, data, idempotencyKey: key }), { plan_id: P, status: 'queued' }, `${activities}/${A}/discovery-plans`, data],
      [(c: MatchClient) => c.retryPlan({ id: P, idempotencyKey: key }), { plan_id: P, status: 'queued' }, `${discovery}/plans/${P}/retry`, undefined],
      [(c: MatchClient) => c.stop({ queryId: Q, idempotencyKey: key }), { query_id: Q, status: 'stopped', stop_requested: true }, `${discovery}/queries/${Q}/stop`, undefined],
      [(c: MatchClient) => c.continueDiscovery({ queryId: Q, data: { acknowledge_unknown: true }, idempotencyKey: key }), { query_id: Q, batch_id: B, status: 'queued' }, `${discovery}/queries/${Q}/continue`, { acknowledge_unknown: true }],
      [(c: MatchClient) => c.evaluate({ queryId: Q, data: { candidate_ids: null }, idempotencyKey: key }), { evaluation_id: E, status: 'queued' }, `${discovery}/queries/${Q}/evaluations`, { candidate_ids: null }],
      [(c: MatchClient) => c.retryEvaluation({ id: E, data: {}, idempotencyKey: key }), { evaluation_id: E, status: 'queued' }, `${discovery}/evaluations/${E}/retry`, {}],
    ] as const;
    for (const [call, response, path, body] of cases) {
      const request = vi.fn().mockResolvedValue(response), client = new MatchClient(request);
      expect(await call(client)).toEqual(response); await call(client);
      expect(request.mock.calls).toEqual([[{ method: 'POST', path, ...(body === undefined ? {} : { body }), idempotencyKey: key }], [{ method: 'POST', path, ...(body === undefined ? {} : { body }), idempotencyKey: key }]]);
    }
  });
  it.each([
    { mode: 'discover', platforms: [] }, { mode: 'discover', platforms: ['youtube', 'youtube'] }, { mode: 'discover', platforms: ['twitch'] },
    { mode: 'discover', platforms: ['x'], batch_target: 101 }, { mode: 'discover', platforms: ['x'], result_limit: 601 },
    { mode: 'discover', platforms: ['x'], batch_request_budget: 41 }, { mode: 'discover', platforms: ['x'], total_request_budget: 241 },
    { mode: 'discover', platforms: ['x'], batch_scan_budget: 2001 }, { mode: 'discover', platforms: ['x'], total_scan_budget: 12001 },
    { mode: 'preview', platforms: ['youtube'], keywords: [' '] }, { mode: 'preview', platforms: ['youtube'], keywords: ['a\nb'] },
    { mode: 'preview', platforms: ['youtube'], filters: { countries: ['usa'] } },
    { mode: 'preview', platforms: ['youtube'], filters: { follower_ranges: [{}] } },
    { mode: 'preview', platforms: ['youtube'], filters: { follower_ranges: [{ minimum: 5, maximum: 4 }] } },
    { mode: 'preview', platforms: ['youtube'], filters: { include_unknown_country: 'true' } },
    { mode: 'discover', platforms: ['x'], providers: [{ query: 'user raw query' }] },
  ])('rejects invalid plan before dispatch: %j', async data => {
    const request = vi.fn();
    await expect(new MatchClient(request).createPlan({ activityId: A, data: data as never, idempotencyKey: key })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it('enforces route IDs, page caps, create and subset boundaries before dispatch', async () => {
    const request = vi.fn(), c = new MatchClient(request);
    const calls = [() => c.activity('../settings'), () => c.activities({ limit: 101 }), () => c.plans({ activityId: A, limit: 201 }),
      () => c.candidates({ queryId: Q, offset: -1 }), () => c.evaluationResults({ id: E, limit: 0 }),
      () => c.createActivity({ data: { game_id: G, name: '' }, idempotencyKey: key }),
      () => c.createActivity({ data: { game_id: G, name: 'Name', reference_work_ids: Array(101).fill(S) }, idempotencyKey: key }),
      () => c.evaluate({ queryId: Q, data: { candidate_ids: [] }, idempotencyKey: key }),
      () => c.evaluate({ queryId: Q, data: { candidate_ids: [C, C] }, idempotencyKey: key }),
      () => c.retryEvaluation({ id: E, data: { step_ids: Array(1001).fill(S) }, idempotencyKey: key }),
      () => c.stop({ queryId: Q, idempotencyKey: 'bad' }), () => c.stop({ queryId: Q, idempotencyKey: key, data: {} } as never)];
    for (const call of calls) await expect(call()).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it('validates all nested plan/filter boundaries while retaining zero, null and omissions', async () => {
    const request = vi.fn().mockResolvedValue({ plan_id: P, status: 'queued' }), c = new MatchClient(request);
    const data = planCreateFixture(); data.filters!.follower_ranges = [{ minimum: 0, maximum: 0 }, { maximum: 1000 }];
    await c.createPlan({ activityId: A, data, idempotencyKey: key });
    expect(request.mock.calls[0][0].body).toEqual(data);
    for (const field of ['batch_target', 'result_limit', 'batch_request_budget', 'batch_scan_budget', 'total_request_budget', 'total_scan_budget']) {
      await expect(c.createPlan({ activityId: A, data: { ...data, [field]: 0 }, idempotencyKey: key })).rejects.toMatchObject({ code: 'request_invalid' });
      await expect(c.createPlan({ activityId: A, data: { ...data, [field]: 1.5 }, idempotencyKey: key })).rejects.toMatchObject({ code: 'request_invalid' });
    }
  });
  it('rejects mismatched parent identities and malformed successful POST replies as unknown', async () => {
    const request = vi.fn().mockResolvedValue({ ...planFixture(), id: A }), c = new MatchClient(request);
    await expect(c.plan(P)).rejects.toMatchObject({ code: 'invalid_response' });
    request.mockResolvedValue(matchPage({ ...planFixture(), activity_id: G }));
    await expect(c.plans({ activityId: A })).rejects.toMatchObject({ code: 'invalid_response' });
    request.mockResolvedValue({ plan_id: A, status: 'queued' });
    await expect(c.retryPlan({ id: P, idempotencyKey: key })).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    request.mockResolvedValue({ query_id: A, status: 'stopped', stop_requested: true });
    await expect(c.stop({ queryId: Q, idempotencyKey: key })).rejects.toMatchObject({ code: 'save_outcome_unknown' });
  });
  it('preserves unknown facts and frozen identities without mutating the acquired response', async () => {
    const fixture = candidateFixture(); fixture.identity_changed = true; fixture.creator!.source_identity.revision = 2;
    fixture.creator!.contacts = []; fixture.creator!.source_identity.account_id = 'new-account';
    const request = vi.fn().mockResolvedValue(matchPage(fixture));
    const result = await new MatchClient(request).candidates({ queryId: Q });
    expect(result.items[0]).toEqual(fixture); expect(result.items[0].account.follower_count).toBeNull();
    result.items[0].account.display_name = 'Changed locally'; expect(fixture.account.display_name).toBe('Acquired name');
  });
  it.each([
    (r: any) => { r.items[0].creator.follower_count = NaN; }, (r: any) => { r.items[0].creator.id = A; },
    (r: any) => { r.items[0].selected = true; }, (r: any) => { r.items[0].account.bad = Infinity; },
    (r: any) => { r.items[0].added_at = '2026-02-30T00:00:00Z'; }, (r: any) => { r.items.push(r.items[0]); r.total = 2; },
    (r: any) => { r.items[0].score = 99; }, (r: any) => { r.limit = 101; },
  ])('rejects unsafe nested candidate responses', async mutate => {
    const response = matchPage(candidateFixture()); mutate(response);
    await expect(new MatchClient(vi.fn().mockResolvedValue(response)).candidates({ queryId: Q })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it.each([
    (r: any) => { r.items[0].sender_watched = true; }, (r: any) => { r.items[0].selected = true; },
    (r: any) => { r.items[0].match_brief.candidate_id = A; }, (r: any) => { r.items[0].match_brief.limitations = []; },
    (r: any) => { r.items[0].match_brief.score = 85; }, (r: any) => { r.items[0].fit_group = 'top_rank'; },
    (r: any) => { r.items[0].evidence[0].timestamp_seconds = Infinity; }, (r: any) => { r.items[0].evidence[0].source_url = 'javascript:alert(1)'; },
    (r: any) => { r.items[0].rank = 1; }, (r: any) => { r.items[0].evidence_status = 'verified_played'; },
  ])('rejects invented ranking, viewing confirmation and malformed evaluation evidence', async mutate => {
    const response = matchPage(evaluationResultFixture()); mutate(response);
    await expect(new MatchClient(vi.fn().mockResolvedValue(response)).evaluationResults({ id: E })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it.each(['revision', 'missing-creator'])('rejects a hidden identity change: %s', async kind => {
    const item = candidateFixture();
    if (kind === 'revision') { item.creator!.source_identity.revision = 2; item.creator!.contacts = []; }
    else item.creator = null;
    await expect(new MatchClient(vi.fn().mockResolvedValue(matchPage(item))).candidates({ queryId: Q })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('rejects an identity-changed evaluation falsely described as current', async () => {
    const item = evaluationResultFixture(); item.identity_changed = true;
    await expect(new MatchClient(vi.fn().mockResolvedValue(matchPage(item))).evaluationResults({ id: E })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('rejects recorded-evidence claims without a supplied recorded evidence row', async () => {
    const item = evaluationResultFixture(); item.evidence_status = 'recorded_evidence';
    await expect(new MatchClient(vi.fn().mockResolvedValue(matchPage(item))).evaluationResults({ id: E })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('rejects missing cited works instead of presenting unsupported model claims', async () => {
    const item = evaluationResultFixture(); item.match_brief!.cited_work_ids = [A];
    await expect(new MatchClient(vi.fn().mockResolvedValue(matchPage(item))).evaluationResults({ id: E })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('does not accept a successful activity creation bound to a different game', async () => {
    const item = activityFixture(); item.game_id = A;
    await expect(new MatchClient(vi.fn().mockResolvedValue(item)).createActivity({ data: { game_id: G, name: 'Activity' }, idempotencyKey: key })).rejects.toMatchObject({ code: 'save_outcome_unknown' });
  });
  it.each([
    { platform: 'youtube', query: 'gameplay', page_size: 51 },
    { platform: 'x', query: 'gameplay', page_size: 9 },
    { platform: 'x', query: 'gameplay', language_hint: 'en' },
    { platform: 'twitch', query: 'gameplay', search_mode: 'channel' },
    { platform: 'youtube', query: '   ' },
  ])('rejects impossible frozen provider conditions from a query response: %j', async provider => {
    const response = queryFixture(); response.conditions.providers = [provider as never];
    await expect(new MatchClient(vi.fn().mockResolvedValue(response)).query(Q)).rejects.toMatchObject({ code: 'invalid_response' });
  });
});
