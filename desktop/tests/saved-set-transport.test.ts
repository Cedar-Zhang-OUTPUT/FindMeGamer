import { describe, expect, it, vi } from 'vitest';
import { authenticatedSavedSetRequest, type SavedSetRequest } from '../src/main/saved-set-transport';
import { ACTIVITY_ID, QUERY_ID } from './match-fixtures';
import { SET_ID, SET_KEY, savedSetCreateFixture, savedSetFixture } from './saved-set-fixtures';

const connection = { serviceUrl: 'https://workspace.example.test', key: 'SYNTHETIC_WORKSPACE_SECRET' };
const write: SavedSetRequest = { method: 'POST', path: `/api/v2/discovery/queries/${QUERY_ID}/saved-sets`, body: savedSetCreateFixture(), idempotencyKey: SET_KEY };
const detail: SavedSetRequest = { method: 'GET', path: `/api/v2/discovery/saved-sets/${SET_ID}` };

describe('Saved-set authenticated transport', () => {
  it('freezes outbound JSON and headers and performs one fetch per explicit request', async () => {
    const fetcher = vi.fn(async () => Response.json(savedSetFixture()));
    await authenticatedSavedSetRequest(fetcher, connection, write);
    await authenticatedSavedSetRequest(fetcher, connection, write);
    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const [url, init] of fetcher.mock.calls as unknown as [string, RequestInit][]) {
      expect(url).toBe(`https://workspace.example.test/api/v2/discovery/queries/${QUERY_ID}/saved-sets`);
      expect(init).toMatchObject({ method: 'POST', body: JSON.stringify(savedSetCreateFixture()), redirect: 'error', credentials: 'omit', cache: 'no-store',
        headers: { Authorization: 'Bearer SYNTHETIC_WORKSPACE_SECRET', Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': SET_KEY } });
      expect(init.signal).toBeInstanceOf(AbortSignal);
    }
  });

  it.each([
    { method: 'GET', path: `/api/v2/activities/${ACTIVITY_ID}/saved-sets`, query: { offset: '0', limit: '100' } },
    detail,
    { method: 'GET', path: `/api/v2/discovery/saved-sets/${SET_ID}/results`, query: { offset: '50', limit: '50', evidence: 'none', sort: 'recent_publish' } },
  ])('allows only the three metadata/results GET routes: $path', async input => {
    const fetcher = vi.fn(async () => Response.json({}));
    await authenticatedSavedSetRequest(fetcher, connection, input as SavedSetRequest);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(new URL(url).pathname).toBe(input.path);
    expect(Object.fromEntries(new URL(url).searchParams)).toEqual('query' in input ? input.query : {});
    expect(init).toMatchObject({ method: 'GET', redirect: 'error', credentials: 'omit', cache: 'no-store' });
    expect(init.body).toBeUndefined();
    expect(init.headers).not.toHaveProperty('Idempotency-Key');
  });

  it.each([
    { ...write, path: 'https://other.test/api/v2/discovery/queries/anything/saved-sets' },
    { ...write, path: `/api/v2/discovery/queries/${QUERY_ID}/saved-sets?extra=1` },
    { ...write, method: 'PATCH' }, { ...write, method: 'DELETE' }, { ...write, path: detail.path },
    { ...write, query: {} }, { ...write, headers: { Authorization: 'injected' } }, { ...write, idempotencyKey: 'short' },
    { ...write, body: { ...savedSetCreateFixture(), candidate_ids: [] } },
    { ...detail, body: {} }, { ...detail, path: '/api/v2/activities' },
    { ...detail, query: { sort: 'relevance' } },
    { method: 'GET', path: `/api/v2/activities/${ACTIVITY_ID}/saved-sets`, query: { evidence: 'all' } },
    { method: 'GET', path: `${detail.path}/results`, query: { sort: 'score' } },
    { method: 'GET', path: `${detail.path}/results`, query: { limit: '101' } },
    { method: 'GET', path: `${detail.path}/results`, query: { offset: '-1' } },
    { method: 'GET', path: `${detail.path}/results`, query: { limit: '01' } },
  ])('rejects unauthorized method/path/body/query before fetch: %j', async input => {
    const fetcher = vi.fn();
    await expect(authenticatedSavedSetRequest(fetcher, connection, input as SavedSetRequest)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([500, 502, 503])('does not automatically repeat a potentially saved HTTP %d request', async status => {
    const fetcher = vi.fn(async () => new Response('SYNTHETIC_ERROR_SECRET', { status }));
    await expect(authenticatedSavedSetRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown', retryable: false });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('separates read connectivity failures from unknown saves without leaking errors', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('SYNTHETIC_ERROR_SECRET'));
    await expect(authenticatedSavedSetRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown', retryable: false });
    try { await authenticatedSavedSetRequest(fetcher, connection, detail); expect.fail('Expected read failure'); }
    catch (error) { expect(error).toMatchObject({ code: 'network_error', retryable: true }); expect(String(error)).not.toContain('SYNTHETIC_ERROR_SECRET'); }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it.each([[401, 'workspace_key_invalid'], [403, 'access_denied'], [404, 'saved_set_not_found'], [409, 'save_conflict'], [422, 'request_invalid'], [429, 'rate_limited']] as const)('sanitizes arbitrary HTTP %d response details', async (status, code) => {
    const fetcher = vi.fn(async () => Response.json({ error: { code: 'SYNTHETIC_ERROR_SECRET', message: 'SYNTHETIC_ERROR_SECRET', correlation_id: 'SYNTHETIC_ERROR_SECRET' } }, { status }));
    try { await authenticatedSavedSetRequest(fetcher, connection, write); expect.fail('Expected rejection'); }
    catch (error) { expect(error).toMatchObject({ code, retryable: false, correlationId: undefined }); expect(String(error)).not.toContain('SYNTHETIC_ERROR_SECRET'); }
  });

  it.each([[409, 'saved_set_request_conflict'], [409, 'idempotency_key_conflict'], [422, 'saved_set_members_invalid'], [404, 'discovery_not_found']] as const)('retains deterministic %s %s codes for explicit recovery', async (status, code) => {
    const fetcher = vi.fn(async () => Response.json({ error: { code, message: 'SYNTHETIC_ERROR_SECRET', correlation_id: ACTIVITY_ID } }, { status }));
    await expect(authenticatedSavedSetRequest(fetcher, connection, write)).rejects.toMatchObject({ code, retryable: false, correlationId: ACTIVITY_ID });
  });

  it('bounds declared and actual response bytes and treats malformed successful saves as unknown', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('not JSON'))
      .mockResolvedValueOnce(new Response('{}', { headers: { 'content-length': String(8 * 1024 * 1024 + 1) } }))
      .mockResolvedValueOnce(new Response(new Uint8Array(8 * 1024 * 1024 + 1)));
    await expect(authenticatedSavedSetRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    await expect(authenticatedSavedSetRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    await expect(authenticatedSavedSetRequest(fetcher, connection, detail)).rejects.toMatchObject({ code: 'response_too_large' });
  });
});
