import type { PublicError, Result } from '../../../shared/bridge';
import type { CompositionView, DraftsAPI, DraftView, TemplateVersion, TemplateVersionCreate, CompositionCreate, DraftEdit, DraftRevision, SenderFacts } from '../../../shared/drafts';

export type DraftCommand =
  | { kind: 'registerCanonical'; gameId: string; canonicalFixedHash?: string }
  | { kind: 'createTemplate'; data: Omit<TemplateVersionCreate, 'request_id'> }
  | { kind: 'createComposition'; activityId: string; data: Omit<CompositionCreate, 'request_id'> }
  | { kind: 'edit'; id: string; data: DraftEdit; observedDraft?: DraftView }
  | { kind: 'refresh' | 'retry'; id: string; data: DraftRevision; observedDraft?: DraftView }
  | { kind: 'senderFacts'; compositionId: string; data: SenderFacts; observedComposition?: CompositionView };
type WriteKind = DraftCommand['kind'];
export type DraftReceipt = { [K in WriteKind]: { kind: K; data: K extends 'registerCanonical' | 'createTemplate' ? TemplateVersion : K extends 'createComposition' | 'senderFacts' ? CompositionView : DraftView } }[WriteKind];
export type DraftInput = { [K in WriteKind]: Parameters<DraftsAPI[K]>[0] }[WriteKind];
export interface DraftAttempt { readonly command: DraftCommand; readonly input: DraftInput; readonly startedAt: number; readonly connectionChanged: boolean }
export type DraftReadback = { kind: 'templates'; items: TemplateVersion[] } | { kind: 'composition'; data: CompositionView };
export const DRAFT_RETRY_WINDOW = 86_400_000;
export const draftWriteUnknown: PublicError = { code: 'draft_outcome_unknown', message: 'The draft change may already be saved. Read the current version before another change.', retryable: false };
export const draftConnectionChanged: PublicError = { code: 'connection_changed', message: 'Credentials changed. This original operation cannot be replayed or confirmed with replacement credentials.', retryable: false };
export const draftReadbackMismatch: PublicError = { code: 'draft_reconciliation_mismatch', message: 'The current records do not prove the submitted change.', retryable: false };
function freeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

export function freezeDraftAttempt(command: DraftCommand, startedAt = Date.now()): DraftAttempt {
  const copy = structuredClone(command);
  let input: DraftInput;
  switch (copy.kind) {
    case 'registerCanonical': input = { gameId: copy.gameId, idempotencyKey: crypto.randomUUID() }; break;
    case 'createTemplate': input = { data: { ...copy.data, request_id: crypto.randomUUID() }, idempotencyKey: crypto.randomUUID() }; break;
    case 'createComposition': input = { activityId: copy.activityId, data: { ...copy.data, request_id: crypto.randomUUID() }, idempotencyKey: crypto.randomUUID() }; break;
    case 'senderFacts': input = { compositionId: copy.compositionId, data: copy.data }; break;
    default: input = { id: copy.id, data: copy.data };
  }
  return freeze({ command: copy, input, startedAt, connectionChanged: false });
}

export function withDraftConnectionChanged(attempt: DraftAttempt): DraftAttempt {
  return attempt.connectionChanged ? attempt : freeze({ ...attempt, connectionChanged: true });
}

export function canRetryDraft(attempt: DraftAttempt, now = Date.now()): boolean {
  if (attempt.connectionChanged) return false;
  if (attempt.command.kind === 'createTemplate' || attempt.command.kind === 'createComposition') return true;
  return attempt.command.kind === 'registerCanonical' && now >= attempt.startedAt && now - attempt.startedAt < DRAFT_RETRY_WINDOW;
}

export function draftOutcomeUncertain(code: string): boolean {
  return ['draft_write_unknown', 'draft_outcome_unknown', 'draft_queue_unavailable', 'network_error', 'connection_changed', 'invalid_response'].includes(code);
}

export async function dispatchDraft(api: DraftsAPI, attempt: DraftAttempt): Promise<Result<DraftReceipt>> {
  const { input } = attempt;
  switch (attempt.command.kind) {
    case 'registerCanonical': {
      const result = await api.registerCanonical(input as Parameters<DraftsAPI['registerCanonical']>[0]);
      return result.ok ? { ok: true, data: { kind: 'registerCanonical', data: result.data } } : result;
    }
    case 'createTemplate': {
      const result = await api.createTemplate(input as Parameters<DraftsAPI['createTemplate']>[0]);
      return result.ok ? { ok: true, data: { kind: 'createTemplate', data: result.data } } : result;
    }
    case 'createComposition': {
      const result = await api.createComposition(input as Parameters<DraftsAPI['createComposition']>[0]);
      return result.ok ? { ok: true, data: { kind: 'createComposition', data: result.data } } : result;
    }
    case 'edit': {
      const result = await api.edit(input as Parameters<DraftsAPI['edit']>[0]);
      return result.ok ? { ok: true, data: { kind: 'edit', data: result.data } } : result;
    }
    case 'refresh': {
      const result = await api.refresh(input as Parameters<DraftsAPI['refresh']>[0]);
      return result.ok ? { ok: true, data: { kind: 'refresh', data: result.data } } : result;
    }
    case 'retry': {
      const result = await api.retry(input as Parameters<DraftsAPI['retry']>[0]);
      return result.ok ? { ok: true, data: { kind: 'retry', data: result.data } } : result;
    }
    case 'senderFacts': {
      const result = await api.senderFacts(input as Parameters<DraftsAPI['senderFacts']>[0]);
      return result.ok ? { ok: true, data: { kind: 'senderFacts', data: result.data } } : result;
    }
  }
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
}
const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
function sameMember(a: DraftView, b: DraftView): boolean {
  return a.id === b.id && a.composition_id === b.composition_id && a.recipient_snapshot_id === b.recipient_snapshot_id
    && a.selection_id === b.selection_id && a.input_order === b.input_order;
}
function member(composition: CompositionView, before: DraftView): DraftView | null {
  if (composition.id !== before.composition_id || composition.send_ready !== false
    || composition.recipient_count !== composition.drafts.length || new Set(composition.drafts.map(row => row.id)).size !== composition.drafts.length) return null;
  const row = composition.drafts.find(item => item.id === before.id);
  return row && sameMember(row, before) && row.send_ready === false ? row : null;
}
function sameComposition(before: CompositionView, after: CompositionView): boolean {
  return before.id === after.id && before.activity_id === after.activity_id && before.recipient_batch_id === after.recipient_batch_id
    && before.template_version_id === after.template_version_id && before.recipient_count === after.recipient_count
    && before.drafts.length === after.drafts.length && before.drafts.every((row, i) => sameMember(row, after.drafts[i]));
}
function exactSource(before: DraftView, after: DraftView, expected: DraftRevision): boolean {
  return before.revision === expected.expected_revision && before.context_token === expected.context_token && !before.source_changed
    && after.revision === expected.expected_revision + 1 && after.context_token === expected.context_token && !after.source_changed
    && same(before.input, after.input) && same(before.slot_sources, after.slot_sources) && after.status === 'succeeded'
    && after.error_code === null && after.rendered !== null && after.rendered.fixed_hash === after.input.fixed_hash;
}

/** DTOs omit durable request_id: same-content creations cannot establish identity. */
export function reconcileDraftReadback(attempt: DraftAttempt, readback: DraftReadback): DraftReceipt | null {
  if (attempt.connectionChanged) return null;
  const command = attempt.command;
  if (command.kind === 'registerCanonical' && readback.kind === 'templates' && command.canonicalFixedHash) {
    const matches = readback.items.filter(item => item.game_id === command.gameId && item.fixed_hash === command.canonicalFixedHash && ['canonical','game_bound'].includes(item.source_metadata.kind));
    return matches.length === 1 ? { kind: 'registerCanonical', data: matches[0] } : null;
  }
  if (readback.kind !== 'composition') return null;
  if (command.kind === 'edit' && command.observedDraft && command.id === command.observedDraft.id) {
    const row = member(readback.data, command.observedDraft);
    if (!row || !exactSource(command.observedDraft, row, command.data) || !same(row.values, command.data.values)
      || row.sender_facts_valid || !same(row.sender_facts, {}) || row.values?.firstName !== row.input.public_name
      || row.values?.channelName !== row.input.channel_name || row.values?.reference !== row.input.reference) return null;
    return { kind: 'edit', data: row };
  }
  if (command.kind === 'senderFacts' && command.observedComposition && command.compositionId === command.observedComposition.id
    && sameComposition(command.observedComposition, readback.data) && command.data.members.length > 0
    && new Set(command.data.members.map(item => item.draft_id)).size === command.data.members.length) {
    for (const expected of command.data.members) {
      const before = command.observedComposition.drafts.find(item => item.id === expected.draft_id);
      const row = before && member(readback.data, before);
      if (!before || !row || before.status !== 'succeeded' || !before.values || !exactSource(before, row, expected)
        || !same(before.values, row.values) || !same(before.rendered, row.rendered)) return null;
      const flags = ['following', 'enjoyed', 'liked'] as const;
      if (flags.some(key => row.sender_facts[key] !== command.data[key])
        || typeof row.sender_facts.at !== 'string' || !Number.isFinite(Date.parse(row.sender_facts.at))
        || typeof row.sender_facts.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(row.sender_facts.fingerprint)) return null;
      const sender = row.input.sender;
      const shouldBeValid = flags.every(key => command.data[key]) && !!(sender && typeof sender === 'object' && !Array.isArray(sender) && sender.username);
      if (row.sender_facts_valid !== shouldBeValid) return null;
    }
    return { kind: 'senderFacts', data: readback.data };
  }
  // A worker can advance a refresh/retry before GET. Do not invent a receipt.
  return null;
}

/** Explicit user review only; true retires the old intent, never proves its success.
 * Every affected revision must have advanced, so the old expected revision cannot commit later.
 * The parent supplies a fresh GET and presents its current source context and generation state.
 */
export function reviewDraftReadback(attempt: DraftAttempt, data: CompositionView): boolean {
  if (attempt.connectionChanged) return false;
  const command = attempt.command;
  const advanced = (before: DraftView, expected: DraftRevision): boolean => {
    const row = member(data, before);
    return !!row && before.revision === expected.expected_revision && row.revision > expected.expected_revision
      && /^[a-f0-9]{64}$/.test(row.context_token) && typeof row.source_changed === 'boolean'
      && ['pending', 'running', 'succeeded', 'failed', 'needs_repair'].includes(row.status);
  };
  if (command.kind === 'edit' || command.kind === 'refresh' || command.kind === 'retry') {
    return !!command.observedDraft && command.id === command.observedDraft.id && advanced(command.observedDraft, command.data);
  }
  if (command.kind === 'senderFacts' && command.observedComposition && command.compositionId === command.observedComposition.id
    && sameComposition(command.observedComposition, data) && command.data.members.length > 0
    && new Set(command.data.members.map(row => row.draft_id)).size === command.data.members.length) {
    return command.data.members.every(expected => {
      const before = command.observedComposition!.drafts.find(row => row.id === expected.draft_id);
      return !!before && advanced(before, expected);
    });
  }
  return false;
}
