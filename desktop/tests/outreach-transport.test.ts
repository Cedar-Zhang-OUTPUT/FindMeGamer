import { describe, expect, it, vi } from 'vitest';
import { authenticatedOutreachRequest, validateOutreachRequest, type OutreachRequest } from '../src/main/outreach-transport';
import { ACTIVITY_ID, CANDIDATE_ID } from './match-fixtures';
import { CONTEXT_TOKEN, OUTREACH_KEY, RECIPIENT_BATCH_ID, REQUEST_ID, SELECTION_ID, recipientBatchFixture } from './outreach-fixtures';

const connection = { serviceUrl: 'https://workspace.example.test', key: 'SYNTHETIC_WORKSPACE_SECRET' };
const base = `/api/v2/activities/${ACTIVITY_ID}`;
const write: OutreachRequest = { method: 'POST', path: `${base}/recipient-batches`, body: { request_id: REQUEST_ID,
  recipients: [{ selection_id: SELECTION_ID, expected_revision: 3, context_token: CONTEXT_TOKEN }] }, idempotencyKey: OUTREACH_KEY };

describe('Outreach authenticated transport', () => {
  it('emits a literal URL/header/body boundary with cookies omitted, redirects rejected and timeout bounded', async () => {
    const fetcher = vi.fn(async () => Response.json(recipientBatchFixture()));
    await authenticatedOutreachRequest(fetcher, connection, write);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`https://workspace.example.test${base}/recipient-batches`);
    expect(init).toMatchObject({ method: 'POST', body: JSON.stringify(write.body), redirect: 'error', credentials: 'omit', cache: 'no-store',
      headers: { Authorization: 'Bearer SYNTHETIC_WORKSPACE_SECRET', Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': OUTREACH_KEY } });
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it.each([
    { method: 'GET', path: `${base}/selections`, query: { include_cancelled: 'false', offset: '0', limit: '200' } },
    { method: 'GET', path: `${base}/selections/${SELECTION_ID}` },
    { method: 'POST', path: `${base}/selections`, body: { candidate_id: CANDIDATE_ID }, idempotencyKey: OUTREACH_KEY },
    { method: 'POST', path: `${base}/selections/bulk`, body: { add_candidate_ids: [CANDIDATE_ID] }, idempotencyKey: OUTREACH_KEY },
    { method: 'POST', path: `${base}/selections/${SELECTION_ID}/update`, body: { expected_revision: 0, context_token: CONTEXT_TOKEN }, idempotencyKey: OUTREACH_KEY },
    { method: 'POST', path: `${base}/selections/${SELECTION_ID}/cancel`, body: { expected_revision: 0 }, idempotencyKey: OUTREACH_KEY },
    { method: 'GET', path: `${base}/recipient-batches`, query: { offset: '0', limit: '50' } },
    { method: 'GET', path: `${base}/recipient-batches/${RECIPIENT_BATCH_ID}` }, write,
  ])('accepts only an exact outreach operation: $method $path', input => {
    expect(validateOutreachRequest(input as OutreachRequest)).toEqual(input);
  });

  it.each([
    { ...write, path: `https://evil.test${base}/recipient-batches` }, { ...write, path: `${base}/recipient-batches?x=1` },
    { ...write, method: 'PUT' }, { ...write, method: 'DELETE' }, { ...write, path: `${base}/recipient-batches/${RECIPIENT_BATCH_ID}` },
    { ...write, query: {} }, { ...write, headers: { Authorization: 'injected' } }, { ...write, idempotencyKey: 'short' },
    { method: 'GET', path: `${base}/selections`, query: { cancelled: 'true' } },
    { method: 'GET', path: `${base}/selections`, query: { include_cancelled: 'TRUE' } },
    { method: 'GET', path: `${base}/recipient-batches`, query: { limit: '201' } },
    { method: 'GET', path: `${base}/recipient-batches`, query: { offset: '-1' } },
    { method: 'GET', path: `${base}/recipient-batches/${RECIPIENT_BATCH_ID}`, query: {} },
  ])('rejects invalid routes or envelopes before fetch: %j', async input => {
    const fetcher = vi.fn();
    await expect(authenticatedOutreachRequest(fetcher, connection, input as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([500, 502, 503])('never automatically repeats an unresolved POST response %d', async status => {
    const fetcher = vi.fn(async () => new Response('SYNTHETIC_ERROR_SECRET', { status }));
    await expect(authenticatedOutreachRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'outreach_outcome_unknown', retryable: false });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('keeps a rate-limit rejection deterministic and never retries it automatically', async () => {
    const fetcher = vi.fn(async () => new Response('SYNTHETIC_ERROR_SECRET', { status: 429 }));
    await expect(authenticatedOutreachRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'rate_limited', retryable: false });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    [409, 'selection_revision_conflict'], [409, 'preparation_context_changed'], [409, 'recipient_batch_request_conflict'],
    [409, 'selection_identity_changed'], [409, 'selection_not_current'], [422, 'candidate_activity_mismatch'],
    [422, 'contact_not_eligible'], [422, 'evaluation_activity_mismatch'], [422, 'evaluation_identity_mismatch'],
    [422, 'work_not_current'], [422, 'public_name_missing'], [422, 'selection_change_ambiguous'],
    [422, 'recipient_not_ready'], [404, 'selection_not_found'], [404, 'recipient_batch_not_found'], [409, 'idempotency_key_conflict'],
  ] as const)('retains deterministic %s %s codes without server messages', async (status, code) => {
    const fetcher = vi.fn(async () => Response.json({ error: { code, message: 'SYNTHETIC_ERROR_SECRET', correlation_id: ACTIVITY_ID } }, { status }));
    const error = await authenticatedOutreachRequest(fetcher, connection, write).catch(value => value);
    expect(error).toMatchObject({ code, retryable: false, correlationId: ACTIVITY_ID });
    expect(String(error)).not.toContain('SYNTHETIC_ERROR_SECRET');
  });

  it('keeps deterministic rejection editable while GET failures remain retryable', async () => {
    const conflict = vi.fn(async () => Response.json({ error: { code: 'selection_revision_conflict', message: 'PRIVATE' } }, { status: 409 }));
    await expect(authenticatedOutreachRequest(conflict, connection, write)).rejects.toMatchObject({ code: 'selection_revision_conflict', retryable: false });
    const network = vi.fn().mockRejectedValue(new Error('SYNTHETIC_ERROR_SECRET'));
    await expect(authenticatedOutreachRequest(network, connection, { method: 'GET', path: `${base}/selections/${SELECTION_ID}` }))
      .rejects.toMatchObject({ code: 'network_error', retryable: true });
  });

  it('bounds responses and maps malformed successful writes to unknown outcome', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('not-json'))
      .mockResolvedValueOnce(new Response('{}', { headers: { 'content-length': String(8 * 1024 * 1024 + 1) } }))
      .mockResolvedValueOnce(new Response(new Uint8Array(8 * 1024 * 1024 + 1)));
    await expect(authenticatedOutreachRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'outreach_outcome_unknown' });
    await expect(authenticatedOutreachRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'outreach_outcome_unknown' });
    await expect(authenticatedOutreachRequest(fetcher, connection, { method: 'GET', path: `${base}/selections/${SELECTION_ID}` }))
      .rejects.toMatchObject({ code: 'response_too_large', retryable: true });
  });
});
