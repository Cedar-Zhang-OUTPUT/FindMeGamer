import type { Delivery, DeliveryResolution, DeliveryRetry, FinalSendRequest, Qualification, SendBatch, SendingAPI } from '../../../shared/sending';
import type { PublicError, Result } from '../../../shared/bridge';
export type SendCommand = { kind: 'send'; compositionId: string; data: Omit<FinalSendRequest, 'request_id'>; observedQualification: Qualification }
  | { kind: 'retry'; id: string; data: DeliveryRetry; observedDelivery: Delivery }
  | { kind: 'resolve'; id: string; data: DeliveryResolution; observedDelivery: Delivery };
export type SendingReceipt = { kind: 'send'; data: SendBatch } | { kind: 'retry' | 'resolve'; data: Delivery };
export type SendingInput = Parameters<SendingAPI['send']>[0] | Parameters<SendingAPI['retry']>[0] | Parameters<SendingAPI['resolve']>[0];
export interface SendingAttempt { readonly command: SendCommand; readonly input: SendingInput; readonly startedAt: number; readonly connectionChanged: boolean }
export const sendingWriteUnknown: PublicError = { code: 'sending_write_unknown', message: 'This sending change may already be recorded. Keep its original request and check the current delivery.', retryable: false };
export const sendingConnectionChanged: PublicError = { code: 'connection_changed', message: 'The connection changed. This original sending operation cannot be replayed or confirmed on replacement credentials.', retryable: false };
export const sendingInvalidCommand: PublicError = { code: 'sending_command_stale', message: 'Read the current qualification or delivery before making this change.', retryable: false };
export const sendingReadbackMismatch: PublicError = { code: 'sending_readback_mismatch', message: 'The current delivery does not establish the submitted result or safely retire the original request.', retryable: false };
function freeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
}
const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
const token = (value: string) => /^[a-f0-9]{64}$/.test(value);
const timestamp = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
function validQualification(q: Qualification): boolean {
  return q.send_ready === true && q.members.length > 0 && q.members.length <= 600 && q.total_count === q.members.length
    && q.eligible_count > 0 && q.repair_count === 0 && token(q.qualification_token) && token(q.sending_account_token)
    && !!q.sender.address && new Set(q.members.map(m => m.draft_id)).size === q.members.length
    && new Set(q.members.map(m => m.recipient_snapshot_id)).size === q.members.length
    && q.eligible_count === q.members.filter(m => m.status === 'eligible').length
    && q.excluded_count === q.members.filter(m => m.status === 'excluded').length
    && q.eligible_count + q.excluded_count === q.total_count
    && q.members.every(m => m.status === 'excluded' ? !!m.exclusion_reason?.trim()
      : m.status === 'eligible' && !m.missing_fields.length && m.exclusion_reason === null && m.blocking_delivery_id === null
        && !!m.recipient_email && !!m.html && !!m.text && !!m.values && token(m.context_token) && token(m.fixed_hash));
}
function validObservedDelivery(row: Delivery): boolean {
  return row.id.length > 0 && row.send_batch_id.length > 0 && row.draft_id === row.snapshot.draft_id
    && row.recipient_snapshot_id === row.snapshot.recipient_snapshot_id && row.snapshot.status === 'eligible'
    && Number.isSafeInteger(row.attempt) && row.attempt >= 0;
}
export function validSendingCommand(command: SendCommand): boolean {
  if (command.kind === 'send') {
    const q = command.observedQualification, excluded = command.data.excluded;
    return validQualification(q) && q.composition_id === command.compositionId && q.qualification_token === command.data.qualification_token
      && excluded.length === q.excluded_count && new Set(excluded.map(item => item.draft_id)).size === excluded.length
      && excluded.every(item => item.reason.trim().length > 0 && item.reason.length <= 1000
        && q.members.some(m => m.draft_id === item.draft_id && m.status === 'excluded' && m.exclusion_reason === item.reason.trim()));
  }
  const row = command.observedDelivery;
  if (!validObservedDelivery(row) || row.id !== command.id || row.attempt !== command.data.expected_attempt) return false;
  if (command.kind === 'retry') return row.state === 'failed' || row.state === 'queued';
  return row.state === 'unknown' && (command.data.outcome === 'sent' || command.data.outcome === 'not_sent')
    && command.data.source_note.trim().length > 0 && command.data.source_note.length <= 2000;
}
export function freezeSendingAttempt(command: SendCommand, startedAt = Date.now()): SendingAttempt {
  const copy = structuredClone(command);
  if (!validSendingCommand(copy)) throw new Error(sendingInvalidCommand.message);
  const input: SendingInput = copy.kind === 'send'
    ? { compositionId: copy.compositionId, data: { ...copy.data, request_id: crypto.randomUUID() }, idempotencyKey: crypto.randomUUID() }
    : { id: copy.id, data: copy.data };
  return freeze({ command: copy, input, startedAt, connectionChanged: false });
}
export function withSendingConnectionChanged(attempt: SendingAttempt): SendingAttempt { return attempt.connectionChanged ? attempt : freeze({ ...attempt, connectionChanged: true }); }
export function canRetrySending(attempt: SendingAttempt): boolean { return !attempt.connectionChanged && attempt.command.kind === 'send'; }
export function sendingOutcomeUncertain(code: string): boolean {
  return ['sending_write_unknown', 'send_queue_unavailable', 'network_error', 'connection_changed', 'invalid_response'].includes(code);
}
function sameFrozenDelivery(before: Delivery, row: Delivery): boolean {
  return row.id === before.id && row.send_batch_id === before.send_batch_id && row.draft_id === before.draft_id
    && row.recipient_snapshot_id === before.recipient_snapshot_id && same(row.snapshot, before.snapshot);
}
function validBatch(batch: SendBatch): boolean {
  const q = batch.qualification;
  if (!validQualification(q) || batch.activity_id !== q.activity_id || batch.composition_id !== q.composition_id
    || batch.deliveries.length !== q.eligible_count || new Set(batch.deliveries.map(row => row.id)).size !== batch.deliveries.length) return false;
  const members = q.members.filter(m => m.status === 'eligible');
  return batch.deliveries.every((row, i) => validObservedDelivery(row) && row.send_batch_id === batch.id
    && row.draft_id === members[i].draft_id && row.recipient_snapshot_id === members[i].recipient_snapshot_id
    && same(row.snapshot, { ...members[i], sender: q.sender, sending_account_token: q.sending_account_token }));
}
function readTarget(attempt: SendingAttempt, batch: SendBatch): Delivery | null {
  if (attempt.command.kind === 'send' || !validBatch(batch)) return null;
  const before = attempt.command.observedDelivery;
  if (batch.id !== before.send_batch_id) return null;
  const row = batch.deliveries.find(item => item.id === before.id);
  return row && sameFrozenDelivery(before, row) ? row : null;
}
function exactResolution(command: Extract<SendCommand, { kind: 'resolve' }>, row: Delivery): boolean {
  const outcome = command.data.outcome, resolution = row.resolution;
  return sameFrozenDelivery(command.observedDelivery, row) && row.attempt === command.data.expected_attempt
    && resolution.outcome === outcome && resolution.source_note === command.data.source_note.trim()
    && resolution.attempt === command.data.expected_attempt && timestamp(resolution.at)
    && row.sending_at === command.observedDelivery.sending_at
    && (outcome === 'sent' ? row.state === 'sent' && !row.retryable && row.error_code === null && row.sent_at === resolution.at && row.failed_at === null
      : row.state === 'failed' && row.retryable && row.error_code === 'submission_verified_not_sent' && row.failed_at === resolution.at && row.sent_at === null);
}
/** A matching final-send DTO cannot prove request identity because request_id is not returned. */
export function reconcileSendingReadback(attempt: SendingAttempt, batch: SendBatch): SendingReceipt | null {
  if (attempt.connectionChanged || attempt.command.kind !== 'resolve') return null;
  const row = readTarget(attempt, batch);
  return row && exactResolution(attempt.command, row) ? { kind: 'resolve', data: row } : null;
}
/** Explicit current review is NOT a success receipt. At the same attempt, an old retry
 * may still change a queued/failed row, so only a strictly newer attempt retires it.
 */
export function reviewSendingReadback(attempt: SendingAttempt, batch: SendBatch): boolean {
  if (attempt.connectionChanged || attempt.command.kind === 'send') return false;
  const row = readTarget(attempt, batch);
  return !!row && row.attempt > attempt.command.data.expected_attempt
    && ['queued', 'sending', 'sent', 'failed', 'unknown'].includes(row.state);
}
export async function dispatchSending(api: SendingAPI, attempt: SendingAttempt): Promise<Result<SendingReceipt>> {
  const command = attempt.command;
  if (command.kind === 'send') {
    const response = await api.send(attempt.input as Parameters<SendingAPI['send']>[0]);
    if (!response.ok) return response;
    return validBatch(response.data) && same(response.data.qualification, command.observedQualification)
      ? { ok: true, data: { kind: 'send', data: response.data } } : { ok: false, error: sendingWriteUnknown };
  }
  if (command.kind === 'retry') {
    const response = await api.retry(attempt.input as Parameters<SendingAPI['retry']>[0]);
    if (!response.ok) return response;
    const row = response.data;
    return sameFrozenDelivery(command.observedDelivery, row) && row.attempt === command.data.expected_attempt && row.state === 'queued' && !row.retryable && row.error_code === null
      ? { ok: true, data: { kind: 'retry', data: row } } : { ok: false, error: sendingWriteUnknown };
  }
  const response = await api.resolve(attempt.input as Parameters<SendingAPI['resolve']>[0]);
  if (!response.ok) return response;
  return exactResolution(command, response.data) ? { ok: true, data: { kind: 'resolve', data: response.data } } : { ok: false, error: sendingWriteUnknown };
}
