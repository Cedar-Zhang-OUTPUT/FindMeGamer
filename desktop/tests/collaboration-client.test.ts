import { it, expect, vi } from 'vitest';
import { CollaborationClient } from '../src/main/collaboration-client';
import { invitationFixture, collaborationIds as ids, activityResponseFixture } from './collaboration-fixtures';
it('emits the five scoped routes, exact filters, keyed revisions and preserves source histories', async () => {
  const row = invitationFixture(), request = vi.fn().mockResolvedValue({ items: [row], total: 1, offset: 0, limit: 50 }), client = new CollaborationClient(request);
  expect((await client.list({ activityId: ids.activity, sending_state: 'queued' })).items).toEqual([row]);
  request.mockResolvedValue(row); await client.detail({ activityId: ids.activity, selectionId: ids.selection });
  request.mockResolvedValue({ items: [row], total: 1, offset: 0, limit: 50 }); await client.creatorHistory({ creatorId: ids.creator, activityId: ids.activity });
  request.mockResolvedValue(invitationFixture({ revision: 1, notes: '' })); await client.update({ activityId: ids.activity, selectionId: ids.selection, data: { expected_revision: 0, notes: '' }, idempotencyKey: 'c-original-key' });
  request.mockResolvedValue(invitationFixture({ revision: 1, invitation_state: 'accepted', responses: [activityResponseFixture()] })); await client.respond({ activityId: ids.activity, selectionId: ids.selection, data: { expected_revision: 0, outcome: 'accepted', source_note: ' Synthetic actual reply ', responded_at: '2026-09-09T00:00:00Z' }, idempotencyKey: 'c-response-key' });
  expect(request.mock.calls.map(c => c[0])).toEqual([
    { method: 'GET', path: `/api/v2/activities/${ids.activity}/invitations`, query: { limit: '50', offset: '0', sending_state: 'queued' } },
    { method: 'GET', path: `/api/v2/activities/${ids.activity}/invitations/${ids.selection}` },
    { method: 'GET', path: `/api/v2/library/creators/${ids.creator}/invitations`, query: { limit: '50', offset: '0', activity_id: ids.activity } },
    { method: 'POST', path: `/api/v2/activities/${ids.activity}/invitations/${ids.selection}/update`, body: { expected_revision: 0, notes: '' }, idempotencyKey: 'c-original-key' },
    { method: 'POST', path: `/api/v2/activities/${ids.activity}/invitations/${ids.selection}/responses`, body: { expected_revision: 0, outcome: 'accepted', source_note: ' Synthetic actual reply ', responded_at: '2026-09-09T00:00:00Z' }, idempotencyKey: 'c-response-key' },
  ]);
});
it('retains historical Creator associations but rejects unrelated rows and cross-member deliveries', async () => {
  const row = invitationFixture({ creator_id: ids.selection }), request = vi.fn().mockResolvedValue({ items: [row], total: 1, offset: 0, limit: 50 }), client = new CollaborationClient(request);
  expect((await client.creatorHistory({ creatorId: ids.creator })).items[0].creator_id).toBe(ids.selection);
  await expect(client.creatorHistory({ creatorId: ids.response })).rejects.toMatchObject({ code: 'invalid_response' });
  row.send_history[0].delivery!.recipient_snapshot_id = ids.response; request.mockResolvedValue(row);
  await expect(client.detail({ activityId: ids.activity, selectionId: ids.selection })).rejects.toMatchObject({ code: 'invalid_response' });
});
it('rejects stale or different write receipts as unknown without exposing the server body', async () => {
  const request = vi.fn().mockResolvedValue(invitationFixture()), client = new CollaborationClient(request);
  await expect(client.update({ activityId: ids.activity, selectionId: ids.selection, data: { expected_revision: 0, notes: 'new' }, idempotencyKey: 'c-original-key' })).rejects.toMatchObject({ code: 'collaboration_write_unknown' });
});
it('rejects cross-scope pages, broken history membership, duplicate replies and unbounded JSON', async () => {
  const request = vi.fn(), client = new CollaborationClient(request);
  for (const row of [invitationFixture({ activity_id: ids.creator }), invitationFixture({ memberships: [] }), invitationFixture({ revision: 1, invitation_state: 'accepted', responses: [activityResponseFixture(), activityResponseFixture()] }), invitationFixture({ identity: { bad: 'x'.repeat(1000001) } })]) {
    request.mockResolvedValue({ items: [row], total: 1, offset: 0, limit: 50 }); await expect(client.list({ activityId: ids.activity })).rejects.toMatchObject({ code: 'invalid_response' });
  }
});
it('does not collapse distinct microsecond response events into one write receipt', async () => {
  const request = vi.fn().mockResolvedValue(invitationFixture({ revision: 1, invitation_state: 'accepted', responses: [activityResponseFixture({ responded_at: '2026-09-09T00:00:00.000001Z' })] })), client = new CollaborationClient(request);
  await expect(client.respond({ activityId: ids.activity, selectionId: ids.selection, data: { expected_revision: 0, outcome: 'accepted', source_note: 'Synthetic actual reply', responded_at: '2026-09-09T00:00:00.000002Z' }, idempotencyKey: 'c-response-key' })).rejects.toMatchObject({ code: 'collaboration_write_unknown' });
});
