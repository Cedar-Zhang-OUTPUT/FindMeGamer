import { describe, expect, it, vi } from 'vitest';
import { authenticatedDraftsRequest, validateDraftsRequest } from '../src/main/drafts-transport';
const id = '11111111-1111-4111-8111-111111111111';
const request = { method: 'POST' as const, path: `/api/v2/outreach/drafts/${id}/retry`, body: { expected_revision: 0, context_token: 'a'.repeat(64) } };
describe('drafts transport boundary', () => {
  it('rejects a revision idempotency header and unknown routes', () => {
    expect(() => validateDraftsRequest({ ...request, idempotencyKey: 'never-send' })).toThrow();
    expect(() => validateDraftsRequest({ ...request, path: '/api/v2/outreach/send' })).toThrow();
  });
  it('preserves committed queue failure and omits cookies and redirects', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'draft_queue_unavailable', message: 'SECRET' } }), { status: 503 }));
    await expect(authenticatedDraftsRequest(fetcher, { serviceUrl: 'http://127.0.0.1:62611', key: 'synthetic' }, request)).rejects.toMatchObject({ code: 'draft_queue_unavailable', retryable: false });
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'omit', redirect: 'error', method: 'POST' });
    expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty('Idempotency-Key');
  });
  it('classifies lost, malformed, oversized and 5xx write outcomes as unknown', async () => {
    for (const fetcher of [vi.fn().mockRejectedValue(new Error('SECRET')), vi.fn().mockResolvedValue(new Response('broken')), vi.fn().mockResolvedValue(new Response('{}', { headers: { 'content-length': String(9 * 1024 * 1024) } })), vi.fn().mockResolvedValue(new Response('SECRET', { status: 500 }))]) {
      await expect(authenticatedDraftsRequest(fetcher, { serviceUrl: 'http://127.0.0.1:62611', key: 'fixture' }, request)).rejects.toMatchObject({ code: 'draft_write_unknown', retryable: false });
    }
  });
  it('validates before reading credentials or calling fetch and bounds facts members', async () => {
    const credentials = { get serviceUrl(): string { throw new Error('credential accessed'); }, get key(): string { throw new Error('credential accessed'); } }, fetcher = vi.fn();
    await expect(authenticatedDraftsRequest(fetcher, credentials, { ...request, body: { ...request.body, expected_revision: true } })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
    expect(() => validateDraftsRequest({ method: 'POST', path: `/api/v2/outreach/compositions/${id}/sender-facts`, body: { members: Array(601).fill({ draft_id: id, ...request.body }), following: true, enjoyed: true, liked: true } })).toThrow();
  });
});
