import { describe, expect, it, vi } from 'vitest';
import { authenticatedCreatorRequest, validateCreatorRequest } from '../src/main/creator-transport';
import { creatorFixture, CREATOR_ID, CONTACT_ID } from './creator-fixtures';
const path = '/api/v2/library/creators';
const connection = { serviceUrl: 'http://127.0.0.1:18090', key: 'RAW_SECRET' };
const write = { method: 'POST' as const, path, body: { account_id: 'UCfixture' }, idempotencyKey: 'creator-key-123' };

describe('Creator transport boundary', () => {
  it.each([
    { method: 'DELETE', path: `${path}/${CREATOR_ID}` }, { method: 'GET', path: `${path}/${CREATOR_ID}/contacts` },
    { method: 'POST', path: `${path}/${CREATOR_ID}/identity`, body: {}, idempotencyKey: 'creator-key-123' },
    { method: 'GET', path, query: { cursor: 'abc' } }, { method: 'GET', path, query: { limit: '101' } },
    { method: 'GET', path: `${path}/${CREATOR_ID}`, query: { query: 'x' } },
    { ...write, body: { account_id: 'UCfixture', source_identity: {} } }, { ...write, idempotencyKey: 'bad' },
    { ...write, headers: { cookie: 'secret' } }, { method: 'GET', path: `${path}/../settings` },
    { method: 'PATCH', path: `${path}/${CREATOR_ID}/contacts/${CONTACT_ID}`, body: { expected_revision: 3, email: null } },
  ])('rejects unsupported raw request %j', async request => {
    const fetcher = vi.fn();
    await expect(authenticatedCreatorRequest(fetcher, connection, request as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('validates without changing frozen omitted payload fields', () => {
    expect(validateCreatorRequest(Object.freeze(write))).toEqual(write);
  });
  it.each(['a..b@example.com', 'a@-example.com', 'a@example..com'])('rejects invalid raw contact email before fetch: %s', async email => {
    const fetcher = vi.fn();
    await expect(authenticatedCreatorRequest(fetcher, connection, { method: 'POST', path: `${path}/${CREATOR_ID}/contacts`,
      body: { email, expected_revision: 3 }, idempotencyKey: 'creator-key-123' })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('sends scoped authentication with omitted cookies, redirect rejection and a timeout', async () => {
    const timeout = vi.spyOn(AbortSignal, 'timeout');
    const fetcher = vi.fn().mockResolvedValue(Response.json(creatorFixture()));
    await authenticatedCreatorRequest(fetcher, connection, write);
    expect(fetcher).toHaveBeenCalledWith(`${connection.serviceUrl}${path}`, expect.objectContaining({ method: 'POST', body: JSON.stringify(write.body),
      credentials: 'omit', redirect: 'error', cache: 'no-store', signal: expect.any(AbortSignal),
      headers: expect.objectContaining({ Authorization: 'Bearer RAW_SECRET', 'Idempotency-Key': write.idempotencyKey }) }));
    expect(timeout).toHaveBeenCalledWith(20_000); timeout.mockRestore();
  });
  it.each(['creator_revision_conflict', 'work_revision_conflict', 'creator_identity_changed', 'creator_identity_conflict',
    'creator_contact_conflict', 'creator_analysis_in_progress', 'creator_delivery_in_progress', 'idempotency_key_conflict'])('maps %s without raw error details', async code => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code, message: 'RAW_SECRET', detail: 'RAW_SECRET', correlation_id: CREATOR_ID } }, { status: 409 }));
    try { await authenticatedCreatorRequest(fetcher, connection, write); throw Error('expected rejection'); }
    catch (error) { expect(error).toMatchObject({ code, retryable: false, correlationId: CREATOR_ID }); expect(String(error)).not.toContain('RAW_SECRET'); }
  });
  it.each([['creator_not_found', 404], ['creator_contact_not_found', 404], ['creator_work_not_found', 404], ['game_not_found', 404], ['workspace_key_invalid', 401]])('maps %s safely', async (code, status) => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code, correlation_id: 'RAW_SECRET' } }, { status: status as number }));
    await expect(authenticatedCreatorRequest(fetcher, connection, write)).rejects.toMatchObject({ code, correlationId: undefined });
  });
  it.each([500, 502, 503])('marks HTTP %d write outcome unknown', async status => {
    const fetcher = vi.fn().mockResolvedValue(new Response('RAW_SECRET', { status }));
    await expect(authenticatedCreatorRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown', retryable: false });
  });
  it('redacts network errors and marks malformed or oversized mutation responses unknown', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('RAW_SECRET'));
    await expect(authenticatedCreatorRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    await expect(authenticatedCreatorRequest(fetcher, connection, { method: 'GET', path })).rejects.toMatchObject({ code: 'network_error', retryable: true });
    fetcher.mockResolvedValueOnce(new Response('RAW_SECRET'));
    await expect(authenticatedCreatorRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    fetcher.mockResolvedValueOnce(new Response('{}', { headers: { 'content-length': String(8 * 1024 * 1024 + 1) } }));
    await expect(authenticatedCreatorRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'save_outcome_unknown' });
  });
  it('bounds actual streamed bytes independently of content-length', async () => {
    const response = new Response(new Uint8Array(8 * 1024 * 1024 + 1));
    const fetcher = vi.fn().mockResolvedValue(response);
    await expect(authenticatedCreatorRequest(fetcher, connection, { method: 'GET', path })).rejects.toMatchObject({ code: 'response_too_large' });
  });
  it.each([[403, 'access_denied'], [409, 'save_conflict'], [422, 'request_invalid'], [429, 'rate_limited']])('sanitizes unknown HTTP %d response details', async (status, code) => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ error: { code: 'RAW_SECRET', message: 'RAW_SECRET' } }, { status: status as number }));
    await expect(authenticatedCreatorRequest(fetcher, connection, write)).rejects.toMatchObject({ code, retryable: false });
  });
});
