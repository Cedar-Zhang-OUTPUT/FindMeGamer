import type { Result } from './bridge';
import type { JsonObject } from './library';
import type { Delivery } from './sending';
export type FollowUpState = 'not_followed_up' | 'follow_up_needed' | 'followed_up' | 'no_follow_up_needed';
export type CooperationState = 'not_started' | 'in_discussion' | 'collaboration_confirmed' | 'in_production' | 'awaiting_publication' | 'published' | 'settled' | 'closed';
export type SendingState = 'not_sent' | 'queued' | 'sending' | 'sent' | 'failed' | 'unknown';
export type InvitationState = 'not_invited' | 'awaiting_response' | 'accepted' | 'declined';
export interface CollaborationUpdate { expected_revision: number; follow_up_state?: FollowUpState; cooperation_state?: CooperationState; notes?: string }
export interface ManualActivityResponse { expected_revision: number; outcome: 'accepted' | 'declined'; source_note: string; responded_at: string }
export interface ActivityResponseView { id: string; revision: number; outcome: 'accepted' | 'declined'; source_note: string; responded_at: string; recorded_at: string }
export interface RecipientMembership { recipient_batch_id: string; recipient_snapshot_id: string; input_order: number; created_at: string; snapshot: JsonObject }
export interface InvitationSendHistory { send_batch_id: string; composition_id: string; draft_id: string; recipient_snapshot_id: string; created_at: string; qualification_status: 'eligible' | 'needs_repair' | 'excluded'; exclusion_reason: string | null; delivery: Delivery | null }
export interface ActivityInvitation {
  selection_id: string; creator_id: string; activity_id: string; activity_name: string; selected: boolean; identity: JsonObject; display_name: string | null; revision: number;
  sending_state: SendingState; invitation_state: InvitationState; follow_up_state: FollowUpState; cooperation_state: CooperationState; notes: string; invited_at: string | null;
  responses: ActivityResponseView[]; memberships: RecipientMembership[]; send_history: InvitationSendHistory[];
}
export interface ActivityInvitationPage { items: ActivityInvitation[]; total: number; limit: number; offset: number }
export interface CollaborationAPI {
  list(input: { activityId: string; sending_state?: SendingState; invitation_state?: InvitationState; follow_up_state?: FollowUpState; limit?: number; offset?: number }): Promise<Result<ActivityInvitationPage>>;
  detail(input: { activityId: string; selectionId: string }): Promise<Result<ActivityInvitation>>;
  creatorHistory(input: { creatorId: string; activityId?: string; limit?: number; offset?: number }): Promise<Result<ActivityInvitationPage>>;
  update(input: { activityId: string; selectionId: string; data: CollaborationUpdate; idempotencyKey: string }): Promise<Result<ActivityInvitation>>;
  respond(input: { activityId: string; selectionId: string; data: ManualActivityResponse; idempotencyKey: string }): Promise<Result<ActivityInvitation>>;
}
