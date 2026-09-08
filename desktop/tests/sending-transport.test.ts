import { expect, it, vi } from 'vitest';
import { authenticatedSendingRequest, validateSendingRequest } from '../src/main/sending-transport';
const path = '/api/v2/outreach/deliveries/11111111-1111-4111-8111-111111111111/retry';
it('rejects invalid attempts before credentials and never accepts retry keys', async () => {
  const fetcher = vi.fn(), connection = { get serviceUrl(): string { throw Error('credential touched'); }, get key(): string { throw Error('credential touched'); } };
  await expect(authenticatedSendingRequest(fetcher, connection, { method: 'POST', path, body: { expected_attempt: true } })).rejects.toMatchObject({ code: 'request_invalid' });
  expect(fetcher).not.toHaveBeenCalled(); expect(() => validateSendingRequest({ method: 'POST', path, body: { expected_attempt: 1 }, idempotencyKey: 'forbidden-key' })).toThrow();
});
it('preserves committed queue503 without leaking messages and uses isolated transport', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'send_queue_unavailable', message: 'SECRET address' } }), { status: 503 }));
  await expect(authenticatedSendingRequest(fetcher, { serviceUrl: 'https://fixture.test', key: 'synthetic' }, { method: 'POST', path, body: { expected_attempt: 1 } })).rejects.toMatchObject({ code: 'send_queue_unavailable', retryable: false });
  expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'omit', redirect: 'error' }); expect(fetcher.mock.calls[0][1].headers).not.toHaveProperty('Idempotency-Key');
});
it('distinguishes lost/malformed/5xx writes from the read-only qualification POST', async () => {
  for (const fetcher of [vi.fn().mockRejectedValue(Error('secret')), vi.fn().mockResolvedValue(new Response('malformed')), vi.fn().mockResolvedValue(new Response('secret', { status: 500 })), vi.fn().mockResolvedValue(new Response('{}', { headers: { 'content-length': String(9 * 1024 * 1024) } }))]) await expect(authenticatedSendingRequest(fetcher, { serviceUrl: 'https://fixture.test', key: 'synthetic' }, { method: 'POST', path, body: { expected_attempt: 1 } })).rejects.toMatchObject({ code: 'sending_write_unknown', retryable: false });
  const q = { method: 'POST' as const, path: '/api/v2/outreach/compositions/11111111-1111-4111-8111-111111111111/qualification', body: { excluded: [] } };
  await expect(authenticatedSendingRequest(vi.fn().mockRejectedValue(Error('secret')), { serviceUrl: 'https://fixture.test', key: 'synthetic' }, q)).rejects.toMatchObject({ code: 'network_error', retryable: true });
  await expect(authenticatedSendingRequest(vi.fn().mockResolvedValue(new Response('malformed')), { serviceUrl: 'https://fixture.test', key: 'synthetic' }, q)).rejects.toMatchObject({ code: 'invalid_response' });
});
it.each(['qualification_changed', 'qualification_not_ready', 'qualification_exclusion_unknown', 'account_already_invited', 'final_send_request_conflict', 'delivery_retry_not_allowed', 'delivery_not_unknown'])('projects safe %s errors without addresses or messages', async code => {
  try { await authenticatedSendingRequest(vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code, message: 'SECRET secret@example.test' } }), { status: 409 })), { serviceUrl: 'https://fixture.test', key: 'synthetic' }, { method: 'POST', path, body: { expected_attempt: 1 } }); throw Error('Expected rejection'); } catch (error) { expect(error).toMatchObject({ code, retryable: false }); expect(String(error)).not.toContain('SECRET'); expect(String(error)).not.toContain('secret@example.test'); }
});
