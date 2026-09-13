import type * as DTO from '../shared/sending';
import { exact, fixed, identifier, integer, jsonObject, keys, object, same, slots, draftSlots, sources, stamp, text, token, unique } from './drafts-validation';
import { PublicFailure } from './transport';
export { exact, identifier, integer, keys, object, same, text, token };
type Mode = 'input' | 'response';
export function fail(mode: Mode): never { throw new PublicFailure(mode === 'input' ? 'request_invalid' : 'invalid_response', mode === 'input' ? 'Check the chosen exclusions, qualification, and delivery attempt.' : 'The service returned unsupported sending records.', false); }
function list<T>(v: unknown, max: number, f: (v: unknown) => T, min = 0): T[] { if (!Array.isArray(v) || v.length < min || v.length > max) fail('response'); return v.map(f); }
function bool(v: unknown): boolean { if (typeof v !== 'boolean') fail('response'); return v; }
function plain(v: unknown, m: Mode, max: number, min = 0) { const s = text(v, m, max, min); if (/[\x00-\x1f\x7f]/.test(s)) fail(m); return s; }
function address(v: unknown, required = false): string | null { if (v === null && !required) return null; const s = plain(v, 'response', 254, 3); if (!/^[^\s@<>,;"()]+@[^\s@<>,;"()]+\.[^\s@<>,;"()]+$/.test(s)) fail('response'); return s; }
export function exclusions(v: unknown, mode: Mode): DTO.Exclusion[] { if (!Array.isArray(v) || v.length > 600) fail(mode); const result = v.map(v => { const r = exact(v, ['draft_id', 'reason'], mode); const reason = text(r.reason, mode, 1000, 1); if (!reason.trim()) fail(mode); return { draft_id: identifier(r.draft_id, mode), reason }; }); unique(result.map(v => v.draft_id), mode); return result; }
export function sendingBody(v: unknown, kind: 'qualify' | 'send' | 'retry' | 'resolve'): Record<string, unknown> {
  const m = 'input';
  if (kind === 'qualify' || kind === 'send') { const r = exact(v, kind === 'send' ? ['request_id', 'qualification_token', 'excluded'] : ['excluded'], m); exclusions(r.excluded, m); if (kind === 'send') { identifier(r.request_id, m); token(r.qualification_token, m); } return r; }
  const r = exact(v, kind === 'retry' ? ['expected_attempt'] : ['expected_attempt', 'outcome', 'source_note'], m); integer(r.expected_attempt, m); if (kind === 'resolve') { if (r.outcome !== 'sent' && r.outcome !== 'not_sent') fail(m); if (!text(r.source_note, m, 2000, 1).trim()) fail(m); } return r;
}
export function decodeIdentity(v: unknown): DTO.SendingIdentity { const r = exact(v, ['address', 'name', 'reply_to'], 'response'); return { address: address(r.address), name: r.name === null ? null : plain(r.name, 'response', 1000), reply_to: address(r.reply_to) }; }
function facts(v: unknown) { const r = jsonObject(v); if (Object.keys(r).length) { exact(r, ['following', 'enjoyed', 'liked', 'at', 'fingerprint'], 'response'); ['following', 'enjoyed', 'liked'].forEach(k => bool(r[k])); stamp(r.at); token(r.fingerprint, 'response'); } return r; }
const memberKeys = ['draft_id', 'recipient_snapshot_id', 'status', 'missing_fields', 'exclusion_reason', 'recipient_email', 'subject', 'html', 'text', 'values', 'slot_sources', 'template_version_id', 'fixed_hash', 'revision', 'context_token', 'sender_facts', 'identity', 'blocking_delivery_id'];
function decodeMember(v: unknown): DTO.QualifiedMember {
  const m = 'response', r = exact(v, memberKeys, m); identifier(r.draft_id, m); identifier(r.recipient_snapshot_id, m); identifier(r.template_version_id, m); token(r.fixed_hash, m); token(r.context_token, m); integer(r.revision, m);
  if (!['eligible', 'needs_repair', 'excluded'].includes(r.status as string)) fail(m); const missing = list(r.missing_fields, 100, v => text(v, m, 255, 1)); unique(missing, m);
  if (r.blocking_delivery_id !== null) identifier(r.blocking_delivery_id, m); if (r.exclusion_reason !== null && !text(r.exclusion_reason, m, 1000, 1).trim()) fail(m);
  if (r.recipient_email !== null) plain(r.recipient_email, m, 254, 1); plain(r.subject, m, 998, 1);
  if ((r.status === 'excluded') !== (r.exclusion_reason !== null) || (r.status === 'needs_repair' && !missing.length) || (r.status === 'eligible' && missing.length)) fail(m);
  const identity = exact(r.identity, ['platform', 'account_id', 'revision'], m); if (!['youtube', 'x', 'twitch', 'instagram'].includes(identity.platform as string)) fail(m); text(identity.account_id, m, 512, 1); integer(identity.revision, m); jsonObject(r.slot_sources); sources(r.slot_sources); facts(r.sender_facts);
  if ((r.values === null) !== (r.html === null) || (r.html === null) !== (r.text === null)) fail(m);
  if (r.values !== null) {
    const values = r.status === 'eligible' ? slots(r.values, m) : draftSlots(r.values, m), html = text(r.html, m, 120_000), plainText = text(r.text, m, 120_000);
    const marked = /<span background-color="rgba\(255,246,122,0\.8\)">(.*?)<\/span>/gs, matches = [...html.matchAll(marked)];
    const escape = (s: string) => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#x27;');
    const slotKeys = ['firstName', 'channelName', 'reference', 'observation'] as const;
    if (matches.length !== 4 || matches.some((v, i) => v[1] !== escape(values[slotKeys[i]])) || fixed(r.subject, html.split(marked).filter((_, i) => i % 2 === 0), m) !== r.fixed_hash || slotKeys.some(k => !plainText.includes(values[k]))) fail(m);
  }
  if (r.status === 'eligible') { address(r.recipient_email, true); if (r.values === null || r.blocking_delivery_id !== null || !['following', 'enjoyed', 'liked'].every(k => (r.sender_facts as Record<string, unknown>)[k] === true)) fail(m); }
  return r as unknown as DTO.QualifiedMember;
}
export function decodeQualification(v: unknown, compositionId?: string, activityId?: string): DTO.Qualification {
  const m = 'response', r = exact(v, ['composition_id', 'activity_id', 'qualification_token', 'sending_account_token', 'total_count', 'eligible_count', 'repair_count', 'excluded_count', 'sender', 'members', 'send_ready'], m);
  const composition = identifier(r.composition_id, m), activity = identifier(r.activity_id, m); if ((compositionId && !same(composition, compositionId)) || (activityId && !same(activity, activityId))) fail(m); token(r.qualification_token, m); token(r.sending_account_token, m);
  const members = list(r.members, 600, decodeMember), sender = decodeIdentity(r.sender); integer(r.total_count, m, 0, 600); if (r.total_count !== members.length) fail(m);
  unique(members.map(v => v.draft_id), m); unique(members.map(v => v.recipient_snapshot_id), m);
  for (const [status, key] of [['eligible', 'eligible_count'], ['needs_repair', 'repair_count'], ['excluded', 'excluded_count']]) if (integer(r[key], m, 0, 600) !== members.filter(v => v.status === status).length) fail(m);
  if (bool(r.send_ready) !== ((r.eligible_count as number) > 0 && r.repair_count === 0)) fail(m);
  if ((r.eligible_count as number) > 0) { address(sender.address, true); unique(members.filter(v => v.status === 'eligible').map(v => v.recipient_email!), m); }
  return { ...r, members, sender } as unknown as DTO.Qualification;
}
export function sameJSON(a: unknown, b: unknown): boolean { const stable = (v: any): any => Array.isArray(v) ? v.map(stable) : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k => [k, stable(v[k])])) : v; return JSON.stringify(stable(a)) === JSON.stringify(stable(b)); }
export function checkExclusions(q: DTO.Qualification, submitted: DTO.Exclusion[]): void { const actual = q.members.filter(m => m.status === 'excluded'); if (actual.length !== submitted.length || submitted.some(e => !actual.some(m => same(m.draft_id, e.draft_id) && m.exclusion_reason === e.reason.trim()))) fail('response'); }
export function decodeDelivery(v: unknown, id?: string, batchId?: string): DTO.Delivery {
  const m = 'response', r = exact(v, ['id', 'send_batch_id', 'draft_id', 'recipient_snapshot_id', 'snapshot', 'state', 'attempt', 'retryable', 'error_code', 'sending_at', 'sent_at', 'failed_at', 'resolution'], m);
  const actualId = identifier(r.id, m), batch = identifier(r.send_batch_id, m); if ((id && !same(id, actualId)) || (batchId && !same(batchId, batch))) fail(m); identifier(r.draft_id, m); identifier(r.recipient_snapshot_id, m);
  const snap = exact(r.snapshot, [...memberKeys, 'sender', 'sending_account_token'], m); const { sender, sending_account_token, ...member } = snap; const decoded = decodeMember(member); if (decoded.status !== 'eligible' || !same(decoded.draft_id, r.draft_id as string) || !same(decoded.recipient_snapshot_id, r.recipient_snapshot_id as string)) fail(m); const senderIdentity = decodeIdentity(sender); address(senderIdentity.address, true); token(sending_account_token, m);
  if (!['queued', 'sending', 'sent', 'failed', 'unknown'].includes(r.state as string)) fail(m); const attempt = integer(r.attempt, m); if (r.state !== 'queued' && attempt < 1) fail(m); if (bool(r.retryable) !== (r.state === 'failed')) fail(m); if (r.error_code !== null && !['smtp_outcome_unknown', 'smtp_rejected', 'smtp_temporarily_unavailable', 'smtp_preparation_failed', 'sending_account_changed', 'submission_verified_not_sent'].includes(r.error_code as string)) fail(m);
  for (const k of ['sending_at', 'sent_at', 'failed_at']) if (r[k] !== null) stamp(r[k]); if (r.state === 'sent' && r.sent_at === null) fail(m); if (r.state === 'failed' && r.failed_at === null) fail(m);
  const resolution = jsonObject(r.resolution); if (Object.keys(resolution).length) { exact(resolution, ['outcome', 'source_note', 'at', 'attempt'], m); if (!['sent', 'not_sent'].includes(resolution.outcome as string) || !text(resolution.source_note, m, 2000, 1).trim()) fail(m); stamp(resolution.at); integer(resolution.attempt, m, 1, attempt); if (resolution.outcome === 'sent' && (r.state !== 'sent' || resolution.attempt !== attempt)) fail(m); }
  return r as unknown as DTO.Delivery;
}
export function decodeBatch(v: unknown, id?: string, compositionId?: string, activityId?: string): DTO.SendBatch {
  const m = 'response', r = exact(v, ['id', 'activity_id', 'composition_id', 'created_at', 'qualification', 'deliveries'], m), actualId = identifier(r.id, m), activity = identifier(r.activity_id, m), composition = identifier(r.composition_id, m);
  if ((id && !same(id, actualId)) || (compositionId && !same(compositionId, composition)) || (activityId && !same(activityId, activity))) fail(m); stamp(r.created_at);
  const qualification = decodeQualification(r.qualification, composition, activity); if (!qualification.send_ready) fail(m); const eligible = qualification.members.filter(v => v.status === 'eligible'); const deliveries = list(r.deliveries, 600, v => decodeDelivery(v, undefined, actualId), 1); unique(deliveries.map(v => v.id), m);
  if (deliveries.length !== eligible.length || deliveries.some((d, i) => !sameJSON(d.snapshot, { ...eligible[i], sender: qualification.sender, sending_account_token: qualification.sending_account_token }))) fail(m);
  return { ...r, qualification, deliveries } as unknown as DTO.SendBatch;
}
export function decodePage(v: unknown, activityId: string, offset: number, limit: number): DTO.SendBatchPage { const r = exact(v, ['items', 'total', 'offset', 'limit'], 'response'); if (r.offset !== offset || r.limit !== limit) fail('response'); const items = list(r.items, limit, v => decodeBatch(v, undefined, undefined, activityId)), total = integer(r.total, 'response'); unique(items.map(v => v.id), 'response'); if (items.length > Math.max(0, total - offset)) fail('response'); return { items, total, offset, limit }; }
