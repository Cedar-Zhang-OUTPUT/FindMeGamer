import type { ActivityInvitation, ActivityResponseView } from '../src/shared/collaboration';
import { sendingIds, deliveryFixture } from './sending-fixtures';
export const collaborationIds = { ...sendingIds, selection: '12345678-1234-4234-8234-123456789abc', creator: '22345678-1234-4234-8234-123456789abc', response: '32345678-1234-4234-8234-123456789abc' };
export function activityResponseFixture(patch: Partial<ActivityResponseView> = {}): ActivityResponseView { return { id: collaborationIds.response, revision: 1, outcome: 'accepted', source_note: 'Synthetic actual reply', responded_at: '2026-09-09T08:00:00+08:00', recorded_at: '2026-09-09T00:01:00Z', ...patch }; }
export function invitationFixture(patch: Partial<ActivityInvitation> = {}): ActivityInvitation {
  return { selection_id: collaborationIds.selection, creator_id: collaborationIds.creator, activity_id: collaborationIds.activity, activity_name: 'C synthetic Activity', selected: true, identity: { platform: 'youtube', account_id: 'synthetic-account', revision: 0 }, display_name: 'Synthetic creator', revision: 0,
    sending_state: 'queued', invitation_state: 'not_invited', follow_up_state: 'not_followed_up', cooperation_state: 'not_started', notes: '', invited_at: null, responses: [],
    memberships: [{ recipient_batch_id: collaborationIds.batch, recipient_snapshot_id: collaborationIds.recipient, input_order: 0, created_at: '2026-09-09T00:00:00Z', snapshot: { creator_id: collaborationIds.creator, name: 'Frozen creator', identity: { platform: 'youtube', account_id: 'old-account', revision: 0 } } }],
    send_history: [{ send_batch_id: collaborationIds.batch, composition_id: collaborationIds.composition, draft_id: collaborationIds.draft, recipient_snapshot_id: collaborationIds.recipient, created_at: '2026-09-09T00:00:00Z', qualification_status: 'eligible', exclusion_reason: null, delivery: deliveryFixture() }], ...patch };
}
