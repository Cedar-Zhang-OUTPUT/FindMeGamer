import { describe, expect, it, vi } from 'vitest';
import { authenticatedMatchRequest, validateMatchRequest } from '../src/main/match-transport';
import { ACTIVITY_ID as A, GAME_ID as G, PLAN_ID as P, QUERY_ID as Q, EVALUATION_ID as E, activityFixture } from './match-fixtures';
const connection = { serviceUrl: 'https://example.com', key: 'SYNTHETIC_SECRET' };
const key = 'match-operation-123';
const write = { method: 'POST' as const, path: '/api/v2/activities', body: { name: 'Activity', game_id: G }, idempotencyKey: key };

describe('Match transport authorization and failure boundary', () => {
  it.each([
    { method: 'GET', path: 'https://evil.invalid/api/v2/activities' }, { method: 'GET', path: '//evil.invalid/api/v2/activities' },
    { method: 'GET', path: '/api/v1/match' }, { method: 'GET', path: '/api/v2/activities/../settings' },
    { method: 'GET', path: '/api/v2/activities', query: { limit: '101' } },
    { method: 'GET', path: `/api/v2/activities/${A}/discovery-plans`, query: { limit: '201' } },
    { method: 'GET', path: '/api/v2/activities', query: { offset: '01' } },
    { method: 'GET', path: '/api/v2/activities', query: { cursor: 'manual' } },
    { method: 'GET', path: `/api/v2/discovery/plans/${P}`, query: { limit: '10' } },
    { method: 'POST', path: `/api/v2/activities/${A}/queries`, body: { providers: [] }, idempotencyKey: key },
    { method: 'POST', path: `/api/v2/discovery/queries/${Q}/stop`, body: {}, idempotencyKey: key },
    { method: 'POST', path: `/api/v2/discovery/plans/${P}/retry`, body: {}, idempotencyKey: key },
    { method: 'GET', path: `/api/v2/discovery/evaluations/${E}/retry` }, { ...write, method: 'PATCH' },
    { ...write, body: { name: 'Activity', game_id: G, selected: true } }, { ...write, idempotencyKey: 'bad' },
    { ...write, headers: { Authorization: 'other' } }, { ...write, query: {} },
  ])('rejects unsupported routes/fields before network: %j', async input => {
    const fetcher = vi.fn();
    await expect(authenticatedMatchRequest(fetcher, connection, input as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('preserves exact frozen payload and scoped header with no automatic POST retry', async () => {
    expect(validateMatchRequest(Object.freeze(write))).toEqual(write);
    const fetcher = vi.fn().mockImplementation(async () => Response.json(activityFixture()));
    await authenticatedMatchRequest(fetcher, connection, write); await authenticatedMatchRequest(fetcher, connection, write);
    expect(fetcher).toHaveBeenCalledTimes(2);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe('https://example.com/api/v2/activities');
    expect(init).toMatchObject({ method: 'POST', body: JSON.stringify(write.body), credentials: 'omit', redirect: 'error', cache: 'no-store', signal: expect.any(AbortSignal), headers: { Authorization: 'Bearer SYNTHETIC_SECRET', 'Idempotency-Key': key } });
    expect(fetcher.mock.calls[1][1].body).toBe(init.body); expect(fetcher.mock.calls[1][1].headers['Idempotency-Key']).toBe(key);
  });
  it('sends stop/retry with neither a JSON body nor content type', async () => {
    const fetcher = vi.fn().mockImplementation(async () => Response.json({}));
    for (const path of [`/api/v2/discovery/plans/${P}/retry`, `/api/v2/discovery/queries/${Q}/stop`]) {
      await authenticatedMatchRequest(fetcher, connection, { method: 'POST', path, idempotencyKey: key });
      expect(fetcher.mock.lastCall![1]).not.toHaveProperty('body');
      expect(fetcher.mock.lastCall![1].headers).not.toHaveProperty('Content-Type');
      expect(fetcher.mock.lastCall![1].headers['Idempotency-Key']).toBe(key);
    }
  });
  it.each(['http://example.com', 'https://user:password@example.com', 'https://example.com/path', 'file:///tmp/service'])('rejects unsafe configured origin %s', async serviceUrl => {
    const fetcher = vi.fn();
    await expect(authenticatedMatchRequest(fetcher, { ...connection, serviceUrl }, write)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([500, 502, 503, 504])('keeps HTTP %d POST outcome unknown without replay', async status => {
    const fetcher = vi.fn().mockResolvedValue(new Response('SYNTHETIC_SECRET', { status }));
    await expect(authenticatedMatchRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown', retryable: false });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('separates uncertain POST from retryable GET network errors and redacts details', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('SYNTHETIC_SECRET'));
    await expect(authenticatedMatchRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown', retryable: false });
    try { await authenticatedMatchRequest(fetcher, connection, { method: 'GET', path: '/api/v2/activities' }); }
    catch (error) { expect(error).toMatchObject({ code: 'network_error', retryable: true }); expect(String(error)).not.toContain('SYNTHETIC_SECRET'); }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it.each([[401, 'workspace_key_invalid'], [403, 'access_denied'], [404, 'match_not_found'], [409, 'save_conflict'], [422, 'request_invalid'], [429, 'rate_limited']])('maps HTTP %d without exposing arbitrary server data', async (status, code) => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code: 'SYNTHETIC_SECRET', message: 'SYNTHETIC_SECRET', correlation_id: 'SYNTHETIC_SECRET' } }, { status: status as number }));
    try { await authenticatedMatchRequest(fetcher, connection, write); expect.fail('Expected rejection'); }
    catch (error) { expect(error).toMatchObject({ code, correlationId: undefined, retryable: false }); expect(String(error)).not.toContain('SYNTHETIC_SECRET'); }
  });
  it.each(['idempotency_key_conflict', 'discovery_not_runnable', 'planning_not_retryable', 'evaluation_running', 'evaluation_not_retryable'])('retains safe %s code for explicit decisions', async code => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code, message: 'SYNTHETIC_SECRET', correlation_id: A } }, { status: 409 }));
    await expect(authenticatedMatchRequest(fetcher, connection, write)).rejects.toMatchObject({ code, retryable: false, correlationId: A });
  });
  it('bounds declared and actual response bytes and marks malformed POST replies unknown', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('not JSON'))
      .mockResolvedValueOnce(new Response('{}', { headers: { 'content-length': String(8 * 1024 * 1024 + 1) } }))
      .mockResolvedValueOnce(new Response(new Uint8Array(8 * 1024 * 1024 + 1)));
    await expect(authenticatedMatchRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    await expect(authenticatedMatchRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    await expect(authenticatedMatchRequest(fetcher, connection, { method: 'GET', path: '/api/v2/activities' })).rejects.toMatchObject({ code: 'response_too_large' });
  });
});
