import { it, expect, vi } from 'vitest';
import { authenticatedCollaborationRequest, validateCollaborationRequest, type CollaborationRequest } from '../src/main/collaboration-transport';
import { collaborationIds as ids } from './collaboration-fixtures';
const path = `/api/v2/activities/${ids.activity}/invitations/${ids.selection}/update`;
const write: CollaborationRequest = { method: 'POST', path, body: { expected_revision: 0, notes: '' }, idempotencyKey: 'c-original-key' };
it('validates exact paths, filters, non-null changes and aware response time before credentials or HTTP', async () => {
  const fetcher = vi.fn(), connection = { get serviceUrl(): string { throw new Error('credentials accessed'); }, key: 'secret' };
  for (const value of [{ ...write, body: { expected_revision: 0 } }, { ...write, body: { expected_revision: 0, notes: null } }, { ...write, body: { expected_revision: -1, notes: '' } }, { ...write, body: { expected_revision: 0, notes: 'x'.repeat(10001) } }, { ...write, idempotencyKey: undefined }, { method: 'GET', path: `/api/v2/activities/${ids.activity}/invitations`, query: { limit: '201' } }, { ...write, path: path.replace('update', 'responses'), body: { expected_revision: 0, outcome: 'accepted', source_note: 'source', responded_at: '2026-09-09T12:00:00' } }]) {
    await expect(authenticatedCollaborationRequest(fetcher, connection, value as CollaborationRequest)).rejects.toMatchObject({ code: 'request_invalid' });
  }
  expect(fetcher).not.toHaveBeenCalled(); expect(validateCollaborationRequest(write)).toEqual(write);
});
it('uses no cookies, no redirects, bounded responses and preserves only public safe conflicts', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{}')), connection = { serviceUrl: 'http://127.0.0.1:1234', key: 'secret' };
  await authenticatedCollaborationRequest(fetcher, connection, write); expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'omit', redirect: 'error', cache: 'no-store', body: JSON.stringify(write.body), headers: { 'Idempotency-Key': 'c-original-key' } });
  fetcher.mockResolvedValue(new Response(JSON.stringify({ error: { code: 'collaboration_revision_conflict', message: 'private@example.test' } }), { status: 409 }));
  const error = await authenticatedCollaborationRequest(fetcher, connection, write).catch(e => e) as Error & { code: string }; expect(error.code).toBe('collaboration_revision_conflict'); expect(error.message).not.toContain('private@');
  fetcher.mockResolvedValue(new Response('broken', { status: 502 })); await expect(authenticatedCollaborationRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'collaboration_write_unknown' });
  fetcher.mockResolvedValue(new Response('{}', { headers: { 'content-length': '999999999' } })); await expect(authenticatedCollaborationRequest(fetcher, connection, { method: 'GET', path: path.replace(/\/update$/, '') })).rejects.toMatchObject({ code: 'response_too_large' });
  fetcher.mockRejectedValue(new Error('secret network error')); await expect(authenticatedCollaborationRequest(fetcher, connection, write)).rejects.toMatchObject({ code: 'collaboration_write_unknown' });
});
