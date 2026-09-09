import type * as DTO from '../shared/collaboration';
import { exact, identifier, integer, jsonObject, keys, object, stamp, text, unique } from './drafts-validation';
import { decodeDelivery } from './sending-validation';
import { PublicFailure } from './transport';
export { exact, identifier, integer, keys, object };
type Mode = 'input' | 'response';
export const followUp = ['not_followed_up', 'follow_up_needed', 'followed_up', 'no_follow_up_needed'] as const;
export const cooperation = ['not_started', 'in_discussion', 'collaboration_confirmed', 'in_production', 'awaiting_publication', 'published', 'settled', 'closed'] as const;
export const sendingStates = ['not_sent', 'queued', 'sending', 'sent', 'failed', 'unknown'] as const;
export const invitationStates = ['not_invited', 'awaiting_response', 'accepted', 'declined'] as const;
export function fail(mode: Mode): never { throw new PublicFailure(mode === 'input' ? 'request_invalid' : 'invalid_response', mode === 'input' ? 'Check the relationship, revision, progress and response evidence.' : 'The service returned unsupported collaboration records.', false); }
export function choice<T extends string>(v: unknown, options: readonly T[], mode: Mode): T { if (!options.includes(v as T)) fail(mode); return v as T; }
function list<T>(v: unknown, max: number, decode: (v: unknown) => T): T[] { if (!Array.isArray(v) || v.length > max) fail('response'); return v.map(decode); }
export function awareTime(v: unknown, mode: Mode): string { try { return stamp(v); } catch { return fail(mode); } }
export function collaborationBody(v: unknown, response: boolean): Record<string, unknown> {
  const r = object(v, 'input'); integer(r.expected_revision, 'input');
  if (response) { exact(r, ['expected_revision', 'outcome', 'source_note', 'responded_at'], 'input'); choice(r.outcome, ['accepted', 'declined'], 'input'); if (!text(r.source_note, 'input', 2000, 1).trim()) fail('input'); awareTime(r.responded_at, 'input'); }
  else { keys(r, ['expected_revision', 'follow_up_state', 'cooperation_state', 'notes'], 'input'); if (Object.keys(r).length < 2) fail('input'); if (Object.hasOwn(r, 'follow_up_state')) choice(r.follow_up_state, followUp, 'input'); if (Object.hasOwn(r, 'cooperation_state')) choice(r.cooperation_state, cooperation, 'input'); if (Object.hasOwn(r, 'notes')) text(r.notes, 'input', 10000); }
  return r;
}
function response(v: unknown): DTO.ActivityResponseView { const r = exact(v, ['id', 'revision', 'outcome', 'source_note', 'responded_at', 'recorded_at'], 'response'); identifier(r.id, 'response'); integer(r.revision, 'response', 1); choice(r.outcome, ['accepted', 'declined'], 'response'); if (!text(r.source_note, 'response', 2000, 1).trim()) fail('response'); stamp(r.responded_at); stamp(r.recorded_at); return r as unknown as DTO.ActivityResponseView; }
function membership(v: unknown): DTO.RecipientMembership { const r = exact(v, ['recipient_batch_id', 'recipient_snapshot_id', 'input_order', 'created_at', 'snapshot'], 'response'); identifier(r.recipient_batch_id, 'response'); identifier(r.recipient_snapshot_id, 'response'); integer(r.input_order, 'response'); stamp(r.created_at); const snapshot = jsonObject(r.snapshot); if (Object.hasOwn(snapshot, 'creator_id')) identifier(snapshot.creator_id, 'response'); return r as unknown as DTO.RecipientMembership; }
function history(v: unknown): DTO.InvitationSendHistory {
  const r = exact(v, ['send_batch_id', 'composition_id', 'draft_id', 'recipient_snapshot_id', 'created_at', 'qualification_status', 'exclusion_reason', 'delivery'], 'response'); for (const k of ['send_batch_id', 'composition_id', 'draft_id', 'recipient_snapshot_id']) identifier(r[k], 'response'); stamp(r.created_at); choice(r.qualification_status, ['eligible', 'needs_repair', 'excluded'], 'response');
  if (r.exclusion_reason !== null && !text(r.exclusion_reason, 'response', 1000, 1).trim()) fail('response'); if ((r.qualification_status === 'excluded') !== (r.exclusion_reason !== null)) fail('response');
  if (r.delivery !== null) { const d = decodeDelivery(r.delivery); if (r.qualification_status !== 'eligible' || d.send_batch_id !== r.send_batch_id || d.draft_id !== r.draft_id || d.recipient_snapshot_id !== r.recipient_snapshot_id) fail('response'); }
  return r as unknown as DTO.InvitationSendHistory;
}
export function decodeInvitation(v: unknown, activityId?: string, selectionId?: string): DTO.ActivityInvitation {
  const r = exact(v, ['selection_id', 'creator_id', 'activity_id', 'activity_name', 'selected', 'identity', 'display_name', 'revision', 'sending_state', 'invitation_state', 'follow_up_state', 'cooperation_state', 'notes', 'invited_at', 'responses', 'memberships', 'send_history'], 'response');
  for (const k of ['selection_id', 'creator_id', 'activity_id']) identifier(r[k], 'response'); if (activityId && activityId !== r.activity_id || selectionId && selectionId !== r.selection_id) fail('response');
  text(r.activity_name, 'response', 1000, 1); if (typeof r.selected !== 'boolean') fail('response'); jsonObject(r.identity); if (r.display_name !== null) text(r.display_name, 'response', 20000); const revision = integer(r.revision, 'response'); text(r.notes, 'response', 10000); if (r.invited_at !== null) stamp(r.invited_at);
  choice(r.sending_state, sendingStates, 'response'); choice(r.invitation_state, invitationStates, 'response'); choice(r.follow_up_state, followUp, 'response'); choice(r.cooperation_state, cooperation, 'response');
  const responses = list(r.responses, 10000, response), memberships = list(r.memberships, 10000, membership), sendHistory = list(r.send_history, 10000, history);
  unique(responses.map(v => v.id), 'response'); unique(memberships.map(v => v.recipient_snapshot_id), 'response'); unique(sendHistory.map(v => `${v.send_batch_id}:${v.recipient_snapshot_id}`), 'response');
  if (responses.some((row, i) => row.revision > revision || i > 0 && row.revision >= responses[i - 1].revision) || responses.length > 0 && r.invitation_state !== responses[0].outcome) fail('response');
  if (sendHistory.some(row => !memberships.some(m => m.recipient_snapshot_id === row.recipient_snapshot_id))) fail('response');
  return { ...r, responses, memberships, send_history: sendHistory } as unknown as DTO.ActivityInvitation;
}
export function decodePage(v: unknown, scope: { activityId?: string; creatorId?: string; sending_state?: string; invitation_state?: string; follow_up_state?: string }, offset: number, limit: number): DTO.ActivityInvitationPage {
  const r = exact(v, ['items', 'total', 'limit', 'offset'], 'response'); const total = integer(r.total, 'response'); if (r.offset !== offset || r.limit !== limit) fail('response');
  const items = list(r.items, limit, row => decodeInvitation(row, scope.activityId)); unique(items.map(row => row.selection_id), 'response'); if (items.length > Math.max(0, total - offset)) fail('response');
  for (const row of items) { if (scope.creatorId && row.creator_id !== scope.creatorId && !row.memberships.some(m => m.snapshot.creator_id === scope.creatorId)) fail('response'); for (const key of ['sending_state', 'invitation_state', 'follow_up_state'] as const) if (scope[key] !== undefined && row[key] !== scope[key]) fail('response'); }
  return { items, total, offset, limit };
}
