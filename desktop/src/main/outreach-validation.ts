import type * as DTO from '../shared/outreach';
import { decodeWork } from './creator-validation';
import { decodeEvaluationResult } from './match-validation';
import { PublicFailure } from './transport';

type Mode = 'input' | 'response';
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const TOKEN = /^[0-9a-f]{64}$/;
const platforms = ['youtube', 'x', 'twitch', 'instagram'] as const;

export function fail(mode: Mode): never {
  throw new PublicFailure(mode === 'input' ? 'request_invalid' : 'invalid_response', mode === 'input'
    ? 'Check the selected people, revisions, and preparation fields before continuing.'
    : 'The service returned unsupported outreach preparation data. Reload or check the service version.', false);
}
export function object(value: unknown, mode: Mode): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail(mode);
  return value as Record<string, unknown>;
}
export function keys(value: Record<string, unknown>, allowed: readonly string[], mode: Mode): void {
  if (Object.keys(value).some(key => !allowed.includes(key))) fail(mode);
}
function required(value: Record<string, unknown>, names: readonly string[], mode: Mode): void {
  if (names.some(name => !Object.hasOwn(value, name))) fail(mode);
}
export function identifier(value: unknown, mode: Mode): string {
  if (typeof value !== 'string' || !UUID.test(value)) fail(mode); return value;
}
export function integer(value: unknown, mode: Mode, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) fail(mode); return value;
}
function bool(value: unknown, mode: Mode): boolean { if (typeof value !== 'boolean') fail(mode); return value; }
function text(value: unknown, mode: Mode, max = 100_000, min = 0): string {
  if (typeof value !== 'string' || [...value].length < min || [...value].length > max) fail(mode); return value;
}
function optionalText(value: unknown, mode: Mode, max = 100_000): string | null { return value === null ? null : text(value, mode, max); }
function token(value: unknown, mode: Mode): string { const result = text(value, mode, 64, 64); if (!TOKEN.test(result)) fail(mode); return result; }
function enumeration<T extends string | number | boolean>(value: unknown, allowed: readonly T[], mode: Mode): T {
  if (!allowed.includes(value as T)) fail(mode); return value as T;
}
function list<T>(value: unknown, mode: Mode, max: number, decode: (item: unknown) => T, min = 0): T[] {
  if (!Array.isArray(value) || value.length < min || value.length > max) fail(mode); return value.map(decode);
}
function unique(values: string[], mode: Mode): string[] {
  if (new Set(values.map(value => value.toLowerCase())).size !== values.length) fail(mode); return values;
}
function timestamp(value: unknown, mode: Mode): string {
  const result = text(value, mode, 100, 1);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(result) || !Number.isFinite(Date.parse(result))) fail(mode);
  const [year, month, day, hour, minute, second] = result.slice(0, 19).split(/[-T:]/).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > days[month - 1] || hour > 23 || minute > 59 || second > 59) fail(mode);
  return result;
}
function json(value: unknown, mode: Mode, depth = 0): unknown {
  if (depth > 20) fail(mode);
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'string') return text(value, mode, 1_000_000);
  if (typeof value === 'number') { if (!Number.isFinite(value)) fail(mode); return value; }
  if (Array.isArray(value)) { if (value.length > 20_000) fail(mode); return value.map(item => json(item, mode, depth + 1)); }
  const raw = object(value, mode); if (Object.keys(raw).length > 10_000) fail(mode);
  for (const [key, item] of Object.entries(raw)) {
    if (['__proto__', 'prototype', 'constructor'].includes(key)) fail(mode);
    text(key, mode, 1000); json(item, mode, depth + 1);
  }
  return raw;
}
function jsonObject(value: unknown, mode: Mode) { object(value, mode); json(value, mode); return value as DTO.RecipientBatchDetail['source_snapshot']; }

function revisionBody(value: unknown, withSelection = false): Record<string, unknown> {
  const raw = object(value, 'input'); const allowed = withSelection ? ['selection_id', 'expected_revision'] : ['expected_revision'];
  keys(raw, allowed, 'input'); required(raw, allowed, 'input');
  if (withSelection) identifier(raw.selection_id, 'input'); integer(raw.expected_revision, 'input'); return raw;
}
export type OutreachBodyKind = 'selectionCreate' | 'bulk' | 'update' | 'cancel' | 'freeze';
export function outreachBody(value: unknown, kind: OutreachBodyKind): Record<string, unknown> {
  const raw = object(value, 'input');
  if (kind === 'selectionCreate') {
    keys(raw, ['candidate_id'], 'input'); required(raw, ['candidate_id'], 'input'); identifier(raw.candidate_id, 'input'); return raw;
  }
  if (kind === 'cancel') return revisionBody(raw);
  if (kind === 'bulk') {
    keys(raw, ['add_candidate_ids', 'cancel_selections'], 'input');
    const additions = Object.hasOwn(raw, 'add_candidate_ids') ? unique(list(raw.add_candidate_ids, 'input', 600, item => identifier(item, 'input')), 'input') : [];
    const cancellations = Object.hasOwn(raw, 'cancel_selections') ? list(raw.cancel_selections, 'input', 600, item => revisionBody(item, true)) : [];
    const ids = cancellations.map(item => item.selection_id as string); unique(ids, 'input');
    if (!additions.length && !cancellations.length) fail('input'); return raw;
  }
  if (kind === 'update') {
    const allowed = ['expected_revision', 'context_token', 'contact_id', 'evaluation_run_id', 'work_ids', 'confirm_public_name'];
    keys(raw, allowed, 'input'); required(raw, ['expected_revision', 'context_token'], 'input');
    integer(raw.expected_revision, 'input'); token(raw.context_token, 'input');
    for (const name of ['contact_id', 'evaluation_run_id'] as const) if (Object.hasOwn(raw, name) && raw[name] !== null) identifier(raw[name], 'input');
    if (Object.hasOwn(raw, 'work_ids')) unique(list(raw.work_ids, 'input', 100, item => identifier(item, 'input')), 'input');
    if (Object.hasOwn(raw, 'confirm_public_name')) bool(raw.confirm_public_name, 'input'); return raw;
  }
  keys(raw, ['request_id', 'recipients'], 'input'); required(raw, ['request_id', 'recipients'], 'input'); identifier(raw.request_id, 'input');
  const recipients = list(raw.recipients, 'input', 600, item => {
    const choice = revisionBodyWithContext(item); return choice;
  }, 1);
  unique(recipients.map(item => item.selection_id as string), 'input'); return raw;
}
function revisionBodyWithContext(value: unknown): Record<string, unknown> {
  const raw = object(value, 'input'); const allowed = ['selection_id', 'expected_revision', 'context_token'];
  keys(raw, allowed, 'input'); required(raw, allowed, 'input'); identifier(raw.selection_id, 'input');
  integer(raw.expected_revision, 'input'); token(raw.context_token, 'input'); return raw;
}

const contactKeys = ['id', 'email', 'purpose', 'source_url', 'source_type', 'source_fields', 'manual_overrides', 'validation_state', 'identity_revision', 'updated_at', 'status'] as const;
function decodeContact(value: unknown): DTO.PreparationContact {
  const raw = object(value, 'response'); keys(raw, contactKeys, 'response'); required(raw, contactKeys, 'response');
  return {
    id: identifier(raw.id, 'response'), email: text(raw.email, 'response', 254, 3), purpose: optionalText(raw.purpose, 'response', 512),
    source_url: optionalText(raw.source_url, 'response', 2048), source_type: text(raw.source_type, 'response', 255, 1),
    source_fields: jsonObject(raw.source_fields, 'response'), manual_overrides: jsonObject(raw.manual_overrides, 'response'),
    validation_state: text(raw.validation_state, 'response', 255, 1), identity_revision: integer(raw.identity_revision, 'response'),
    updated_at: timestamp(raw.updated_at, 'response'), status: enumeration(raw.status, ['eligible', 'inactive', 'invalid', 'historical'] as const, 'response'),
  };
}
const preparationKeys = ['id', 'activity_id', 'creator_id', 'candidate_id', 'active', 'revision', 'identity', 'identity_changed', 'game_changed', 'name',
  'public_name', 'public_name_confirmed', 'name_confirmed_at', 'contact_options', 'selected_contact', 'contact_status', 'works', 'missing_work_ids',
  'evaluation', 'evaluation_run_id', 'missing_fields', 'context_token', 'freeze_ready', 'send_ready', 'sender_watched', 'pending_send_requirements'] as const;
export function decodePreparation(value: unknown, expectedId?: string, activityId?: string): DTO.Preparation {
  const raw = object(value, 'response'); keys(raw, preparationKeys, 'response'); required(raw, preparationKeys, 'response');
  const id = identifier(raw.id, 'response'), actualActivity = identifier(raw.activity_id, 'response'), creatorId = identifier(raw.creator_id, 'response');
  if ((expectedId && id.toLowerCase() !== expectedId.toLowerCase()) || (activityId && actualActivity.toLowerCase() !== activityId.toLowerCase())) fail('response');
  const candidateId = identifier(raw.candidate_id, 'response');
  const identityRaw = object(raw.identity, 'response'); const identityKeys = ['platform', 'account_id', 'revision'] as const;
  keys(identityRaw, identityKeys, 'response'); required(identityRaw, identityKeys, 'response');
  const identity: DTO.SelectionIdentity = { platform: enumeration(identityRaw.platform, platforms, 'response'),
    account_id: text(identityRaw.account_id, 'response', 512, 1), revision: integer(identityRaw.revision, 'response') };
  const contacts = list(raw.contact_options, 'response', 10_000, decodeContact); unique(contacts.map(item => item.id), 'response');
  const selected = raw.selected_contact === null ? null : decodeContact(raw.selected_contact);
  const works = list(raw.works, 'response', 10_000, item => {
    const work = object(item, 'response');
    if (!Object.hasOwn(work, 'relation') || !Object.hasOwn(work, 'evidence_status')) fail('response');
    const { relation, evidence_status, ...detail } = work;
    return { ...decodeWork(detail, creatorId), relation: enumeration(relation, ['current_game', 'reference_game', 'related_content'] as const, 'response'),
      evidence_status: enumeration(evidence_status, ['recorded_evidence', 'metadata_only'] as const, 'response') };
  });
  unique(works.map(item => item.id), 'response');
  const evaluation = raw.evaluation === null ? null : decodeEvaluationResult(raw.evaluation);
  if (evaluation && (evaluation.creator_id.toLowerCase() !== creatorId.toLowerCase()
    || evaluation.platform !== identity.platform || evaluation.account_id !== identity.account_id)) fail('response');
  const evaluationRunId = raw.evaluation_run_id === null ? null : identifier(raw.evaluation_run_id, 'response');
  if ((evaluation === null) !== (evaluationRunId === null)) fail('response');
  const missingWorkIds = unique(list(raw.missing_work_ids, 'response', 100, item => identifier(item, 'response')), 'response');
  const result: DTO.Preparation = {
    id, activity_id: actualActivity, creator_id: creatorId, candidate_id: candidateId, active: bool(raw.active, 'response'),
    revision: integer(raw.revision, 'response'), identity, identity_changed: bool(raw.identity_changed, 'response'), game_changed: bool(raw.game_changed, 'response'),
    name: optionalText(raw.name, 'response'), public_name: optionalText(raw.public_name, 'response'), public_name_confirmed: bool(raw.public_name_confirmed, 'response'),
    name_confirmed_at: raw.name_confirmed_at === null ? null : timestamp(raw.name_confirmed_at, 'response'), contact_options: contacts, selected_contact: selected,
    contact_status: enumeration(raw.contact_status, ['not_selected', 'eligible', 'changed', 'inactive', 'invalid', 'historical', 'missing'] as const, 'response'),
    works, missing_work_ids: missingWorkIds, evaluation, evaluation_run_id: evaluationRunId,
    missing_fields: list(raw.missing_fields, 'response', 100, item => text(item, 'response', 255, 1)), context_token: token(raw.context_token, 'response'),
    freeze_ready: bool(raw.freeze_ready, 'response'), send_ready: enumeration(raw.send_ready, [false] as const, 'response'),
    sender_watched: enumeration(raw.sender_watched, [false] as const, 'response'),
    pending_send_requirements: list(raw.pending_send_requirements, 'response', 100, item => text(item, 'response', 255, 1)),
  };
  return result;
}

const summaryKeys = ['id', 'activity_id', 'request_id', 'status', 'send_ready', 'recipient_count', 'send_ready_count', 'needs_repair_count', 'created_at'] as const;
function decodeSummary(value: unknown, activityId?: string, expectedId?: string): DTO.RecipientBatchSummary {
  const raw = object(value, 'response'); keys(raw, summaryKeys, 'response'); required(raw, summaryKeys, 'response');
  const id = identifier(raw.id, 'response'), actualActivity = identifier(raw.activity_id, 'response');
  if ((expectedId && id.toLowerCase() !== expectedId.toLowerCase()) || (activityId && actualActivity.toLowerCase() !== activityId.toLowerCase())) fail('response');
  const count = integer(raw.recipient_count, 'response'), repairs = integer(raw.needs_repair_count, 'response');
  if (repairs !== count) fail('response');
  return { id, activity_id: actualActivity, request_id: identifier(raw.request_id, 'response'), status: enumeration(raw.status, ['frozen'] as const, 'response'),
    send_ready: enumeration(raw.send_ready, [false] as const, 'response'), recipient_count: count,
    send_ready_count: enumeration(raw.send_ready_count, [0] as const, 'response'), needs_repair_count: repairs, created_at: timestamp(raw.created_at, 'response') };
}
export function decodeSelectionPage(value: unknown, activityId: string): DTO.SelectionPage {
  const raw = object(value, 'response'); const allowed = ['items', 'total', 'limit', 'offset'] as const;
  keys(raw, allowed, 'response'); required(raw, allowed, 'response');
  const limit = integer(raw.limit, 'response', 1, 200), items = list(raw.items, 'response', limit, item => decodePreparation(item, undefined, activityId));
  unique(items.map(item => item.id), 'response'); const total = integer(raw.total, 'response'); if (items.length > total) fail('response');
  return { items, total, limit, offset: integer(raw.offset, 'response') };
}
export function decodeBulkResult(value: unknown): DTO.SelectionBulkResult {
  const raw = object(value, 'response'); const allowed = ['added_selection_ids', 'cancelled_selection_ids'] as const;
  keys(raw, allowed, 'response'); required(raw, allowed, 'response');
  const added = unique(list(raw.added_selection_ids, 'response', 600, item => identifier(item, 'response')), 'response');
  const cancelled = unique(list(raw.cancelled_selection_ids, 'response', 600, item => identifier(item, 'response')), 'response');
  const addedSet = new Set(added.map(id => id.toLowerCase())); if (cancelled.some(id => addedSet.has(id.toLowerCase()))) fail('response');
  return { added_selection_ids: added, cancelled_selection_ids: cancelled };
}
export function decodeRecipientBatch(value: unknown, expectedId?: string, activityId?: string): DTO.RecipientBatchDetail {
  const raw = object(value, 'response'); keys(raw, [...summaryKeys, 'source_snapshot', 'recipients'], 'response'); required(raw, [...summaryKeys, 'source_snapshot', 'recipients'], 'response');
  const summary = decodeSummary(Object.fromEntries(summaryKeys.map(key => [key, raw[key]])), activityId, expectedId);
  const recipients = list(raw.recipients, 'response', 600, item => {
    const member = object(item, 'response'); const allowed = ['id', 'selection_id', 'snapshot', 'preparation', 'source_changed', 'current_missing_fields'] as const;
    keys(member, allowed, 'response'); required(member, allowed, 'response'); const selectionId = identifier(member.selection_id, 'response');
    return { id: identifier(member.id, 'response'), selection_id: selectionId,
      snapshot: decodePreparation(member.snapshot, selectionId, summary.activity_id), preparation: decodePreparation(member.preparation, selectionId, summary.activity_id),
      source_changed: bool(member.source_changed, 'response'), current_missing_fields: list(member.current_missing_fields, 'response', 100, field => text(field, 'response', 255, 1)) };
  });
  unique(recipients.map(item => item.id), 'response'); unique(recipients.map(item => item.selection_id), 'response');
  if (recipients.length !== summary.recipient_count) fail('response');
  return { ...summary, source_snapshot: jsonObject(raw.source_snapshot, 'response'), recipients };
}
export function decodeRecipientBatchPage(value: unknown, activityId: string): DTO.RecipientBatchPage {
  const raw = object(value, 'response'); const allowed = ['items', 'total', 'limit', 'offset'] as const;
  keys(raw, allowed, 'response'); required(raw, allowed, 'response');
  const limit = integer(raw.limit, 'response', 1, 200), items = list(raw.items, 'response', limit, item => decodeSummary(item, activityId));
  unique(items.map(item => item.id), 'response'); const total = integer(raw.total, 'response'); if (items.length > total) fail('response');
  return { items, total, limit, offset: integer(raw.offset, 'response') };
}
