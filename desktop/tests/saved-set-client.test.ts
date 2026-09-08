import { describe, expect, it, vi } from 'vitest';
import { SavedSetClient } from '../src/main/saved-set-client';
import { ACTIVITY_ID, CANDIDATE_ID, QUERY_ID, candidateFixture, matchPage } from './match-fixtures';
import { REQUEST_ID, SECOND_CANDIDATE_ID, SET_ID, SET_KEY, savedSetCreateFixture, savedSetFixture } from './saved-set-fixtures';

describe('Saved-set client contract', () => {
  it('routes metadata reads with their owner and default pagination', async () => {
    const request = vi.fn().mockResolvedValueOnce(matchPage(savedSetFixture())).mockResolvedValueOnce(savedSetFixture());
    const client = new SavedSetClient(request);
    expect(await client.list({ activityId: ACTIVITY_ID })).toEqual(matchPage(savedSetFixture()));
    expect(request.mock.calls[0][0]).toEqual({ method: 'GET', path: `/api/v2/activities/${ACTIVITY_ID}/saved-sets`, query: { offset: '0', limit: '50' } });
    expect(await client.detail(SET_ID)).toEqual(savedSetFixture());
    expect(request.mock.calls[1][0]).toEqual({ method: 'GET', path: `/api/v2/discovery/saved-sets/${SET_ID}` });
  });

  it('sends server-wide evidence and sort only on results and preserves omitted options', async () => {
    const page = matchPage(candidateFixture(), 100), request = vi.fn().mockResolvedValue(page), client = new SavedSetClient(request);
    expect(await client.results({ id: SET_ID, evidence: 'current_game', sort: 'relevance', offset: 100, limit: 100 })).toEqual(page);
    expect(request.mock.calls[0][0]).toEqual({ method: 'GET', path: `/api/v2/discovery/saved-sets/${SET_ID}/results`, query: { offset: '100', limit: '100', evidence: 'current_game', sort: 'relevance' } });
    await client.results({ id: SET_ID });
    expect(request.mock.calls[1][0]).toEqual({ method: 'GET', path: `/api/v2/discovery/saved-sets/${SET_ID}/results`, query: { offset: '0', limit: '50' } });
  });

  it('preserves the full frozen create body, persistent request ID and HTTP key across retries', async () => {
    const request = vi.fn().mockResolvedValue(savedSetFixture()), client = new SavedSetClient(request);
    const data = savedSetCreateFixture(), original = structuredClone(data);
    Object.freeze(data.candidate_ids); Object.freeze(data);
    expect(await client.create({ queryId: QUERY_ID, data, idempotencyKey: SET_KEY })).toEqual(savedSetFixture());
    await client.create({ queryId: QUERY_ID, data, idempotencyKey: SET_KEY });
    expect(request.mock.calls.map(call => call[0])).toEqual([
      { method: 'POST', path: `/api/v2/discovery/queries/${QUERY_ID}/saved-sets`, body: original, idempotencyKey: SET_KEY },
      { method: 'POST', path: `/api/v2/discovery/queries/${QUERY_ID}/saved-sets`, body: original, idempotencyKey: SET_KEY },
    ]);
    expect(data).toEqual(original);
  });

  it('accepts Unicode character limits and all 600 explicitly supplied members', async () => {
    const ids = Array.from({ length: 600 }, (_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`);
    const data = { request_id: REQUEST_ID, name: '🎮'.repeat(255), candidate_ids: ids };
    const response = { ...savedSetFixture(), name: data.name, candidate_ids: ids, count: 600 };
    const client = new SavedSetClient(async () => response);
    expect(await client.create({ queryId: QUERY_ID, data, idempotencyKey: SET_KEY })).toEqual(response);
  });

  it.each([
    { request_id: 'not-a-uuid' }, { request_id: undefined }, { name: '' }, { name: ' \n\t' }, { name: '🎮'.repeat(256) },
    { candidate_ids: [] }, { candidate_ids: ['not-a-uuid'] }, { candidate_ids: Array(601).fill(CANDIDATE_ID) }, { selected: true },
  ])('rejects invalid create fields before dispatch: %j', async patch => {
    const request = vi.fn(), client = new SavedSetClient(request);
    await expect(client.create({ queryId: QUERY_ID, data: { ...savedSetCreateFixture(), ...patch } as never, idempotencyKey: SET_KEY })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });

  it.each([
    ['list', { activityId: ACTIVITY_ID, limit: 0 }], ['list', { activityId: ACTIVITY_ID, limit: 101 }],
    ['list', { activityId: ACTIVITY_ID, offset: -1 }], ['list', { activityId: ACTIVITY_ID, evidence: 'all' }],
    ['list', { activityId: ACTIVITY_ID, sort: 'relevance' }], ['detail', `${SET_ID}/results`],
    ['results', { id: SET_ID, sort: 'score' }], ['results', { id: SET_ID, evidence: 'played' }],
    ['results', { id: SET_ID, selected: true }], ['results', { id: SET_ID, limit: 101 }],
  ] as const)('rejects unsupported %s input before dispatch', async (method, input) => {
    const request = vi.fn(), client = new SavedSetClient(request);
    await expect((client[method] as (value: unknown) => Promise<unknown>)(input)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });

  it('rejects wrong metadata ownership for list and detail', async () => {
    const request = vi.fn().mockResolvedValueOnce(matchPage({ ...savedSetFixture(), activity_id: QUERY_ID }))
      .mockResolvedValueOnce({ ...savedSetFixture(), id: QUERY_ID });
    const client = new SavedSetClient(request);
    await expect(client.list({ activityId: ACTIVITY_ID })).rejects.toMatchObject({ code: 'invalid_response' });
    await expect(client.detail(SET_ID)).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it.each([
    { query_id: ACTIVITY_ID }, { name: 'Different saved set' }, { candidate_ids: [CANDIDATE_ID, SECOND_CANDIDATE_ID] },
    { candidate_ids: [CANDIDATE_ID], count: 1 }, { count: 1 }, { request_id: REQUEST_ID },
  ])('treats a mismatched create receipt as unknown rather than saved: %j', async patch => {
    const client = new SavedSetClient(async () => ({ ...savedSetFixture(), ...patch }));
    await expect(client.create({ queryId: QUERY_ID, data: savedSetCreateFixture(), idempotencyKey: SET_KEY })).rejects.toMatchObject({ code: 'save_outcome_unknown', retryable: false });
  });

  it.each([
    { count: 0 }, { count: 3 }, { candidate_ids: [CANDIDATE_ID, CANDIDATE_ID.toUpperCase()] },
    { candidate_ids: ['bad-id'] }, { name: '  untrimmed ' }, { created_at: '2026-02-30T00:00:00Z' },
    { created_at: null }, { selected: true },
  ])('rejects malformed metadata without inventing membership: %j', async patch => {
    const client = new SavedSetClient(async () => ({ ...savedSetFixture(), ...patch }));
    await expect(client.detail(SET_ID)).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('uses current-identity candidate validation and rejects invalid pages', async () => {
    const rebound = { ...candidateFixture(), identity_changed: true, creator: null };
    const request = vi.fn().mockResolvedValueOnce(matchPage(rebound)).mockResolvedValueOnce(matchPage({ ...rebound, selected: true }))
      .mockResolvedValueOnce({ ...matchPage(candidateFixture()), total: 0 });
    const client = new SavedSetClient(request);
    expect((await client.results({ id: SET_ID })).items[0]).toEqual(rebound);
    await expect(client.results({ id: SET_ID })).rejects.toMatchObject({ code: 'invalid_response' });
    await expect(client.results({ id: SET_ID })).rejects.toMatchObject({ code: 'invalid_response' });
  });
});
