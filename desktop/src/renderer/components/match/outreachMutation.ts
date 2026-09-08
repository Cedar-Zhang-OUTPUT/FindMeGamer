import type { PublicError, Result } from '../../../shared/bridge';
import type {
  OutreachAPI,
  Preparation,
  PreparationContact,
  RecipientBatchDetail,
  RecipientChoice,
  SelectionBulkChange,
  SelectionBulkResult,
  SelectionCreate,
  SelectionRevision,
  SelectionUpdate,
} from '../../../shared/outreach';

export type OutreachCommand =
  | { kind: 'add'; activityId: string; data: SelectionCreate }
  | { kind: 'bulk'; activityId: string; data: SelectionBulkChange }
  | { kind: 'update'; activityId: string; id: string; data: SelectionUpdate; observedContact?:PreparationContact }
  | { kind: 'cancel'; activityId: string; id: string; data: SelectionRevision }
  | { kind: 'freeze'; activityId: string; data: { recipients: RecipientChoice[] } };

export type OutreachReceipt =
  | { kind: 'add'; data: Preparation }
  | { kind: 'bulk'; data: SelectionBulkResult }
  | { kind: 'update'; data: Preparation }
  | { kind: 'cancel'; data: Preparation }
  | { kind: 'freeze'; data: RecipientBatchDetail };

export type OutreachInput = Parameters<OutreachAPI['add']>[0] | Parameters<OutreachAPI['bulk']>[0]
  | Parameters<OutreachAPI['update']>[0] | Parameters<OutreachAPI['cancel']>[0] | Parameters<OutreachAPI['freeze']>[0];

export interface OutreachAttempt {
  readonly command: OutreachCommand;
  readonly input: OutreachInput;
  readonly startedAt: number;
  readonly connectionChanged: boolean;
}

export const OUTREACH_RETRY_WINDOW = 86_400_000;
export const outreachWriteUnknown: PublicError = {
  code: 'outreach_outcome_unknown',
  message: 'The outreach change may already be saved. Check the current preparation or retry the same request.',
  retryable: false,
};
export const outreachConnectionChanged: PublicError = {
  code: 'connection_changed',
  message: 'Credentials changed. Check the original workspace before starting another outreach change.',
  retryable: false,
};
export const outreachReconciliationMismatch: PublicError = {
  code: 'outreach_reconciliation_mismatch',
  message: 'The saved outreach records do not prove this exact change. Reload or retry the same request.',
  retryable: false,
};

function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
}

export function freezeOutreachAttempt(command: OutreachCommand, startedAt = Date.now(), idempotencyKey = crypto.randomUUID(), requestId?: string): OutreachAttempt {
  const frozenCommand = deepFreeze(structuredClone(command));
  let input: OutreachInput;
  switch (frozenCommand.kind) {
    case 'add': input = { activityId: frozenCommand.activityId, data: frozenCommand.data, idempotencyKey }; break;
    case 'bulk': input = { activityId: frozenCommand.activityId, data: frozenCommand.data, idempotencyKey }; break;
    case 'update': input = { activityId: frozenCommand.activityId, id: frozenCommand.id, data: frozenCommand.data, idempotencyKey }; break;
    case 'cancel': input = { activityId: frozenCommand.activityId, id: frozenCommand.id, data: frozenCommand.data, idempotencyKey }; break;
    case 'freeze': input = { activityId: frozenCommand.activityId, data: { request_id: requestId ?? crypto.randomUUID(), recipients: frozenCommand.data.recipients }, idempotencyKey }; break;
  }
  return deepFreeze({ command: frozenCommand, input, startedAt, connectionChanged: false });
}

export function withOutreachConnectionChanged(attempt: OutreachAttempt): OutreachAttempt {
  return attempt.connectionChanged ? attempt : deepFreeze({ ...attempt, connectionChanged: true });
}

export function canRetryOutreach(attempt: OutreachAttempt, now = Date.now()): boolean {
  if (attempt.connectionChanged) return false;
  if (attempt.command.kind === 'freeze') return true;
  const age = now - attempt.startedAt;
  return age >= 0 && age < OUTREACH_RETRY_WINDOW;
}

export function outreachOutcomeUncertain(code: string): boolean {
  return code === 'outreach_outcome_unknown' || code === 'network_error' || code === 'connection_changed';
}

export async function dispatchOutreach(api: OutreachAPI, attempt: OutreachAttempt): Promise<Result<OutreachReceipt>> {
  const { command, input } = attempt;
  switch (command.kind) {
    case 'add': {
      const response = await api.add(input as Parameters<OutreachAPI['add']>[0]);
      return response.ok ? { ok: true, data: { kind: 'add', data: response.data } } : response;
    }
    case 'bulk': {
      const response = await api.bulk(input as Parameters<OutreachAPI['bulk']>[0]);
      return response.ok ? { ok: true, data: { kind: 'bulk', data: response.data } } : response;
    }
    case 'update': {
      const response = await api.update(input as Parameters<OutreachAPI['update']>[0]);
      return response.ok ? { ok: true, data: { kind: 'update', data: response.data } } : response;
    }
    case 'cancel': {
      const response = await api.cancel(input as Parameters<OutreachAPI['cancel']>[0]);
      return response.ok ? { ok: true, data: { kind: 'cancel', data: response.data } } : response;
    }
    case 'freeze': {
      const response = await api.freeze(input as Parameters<OutreachAPI['freeze']>[0]);
      return response.ok ? { ok: true, data: { kind: 'freeze', data: response.data } } : response;
    }
  }
}

function exactlyOne(items: Preparation[], predicate: (item: Preparation) => boolean): Preparation | null {
  const matches = items.filter(predicate);
  return matches.length === 1 ? matches[0] : null;
}

function sameIds(actual: string[], expected: string[]): boolean {
  return actual.length === expected.length && new Set(actual).size === actual.length
    && new Set(expected).size === expected.length && expected.every((id, index) => actual[index] === id);
}

function updatedFieldsMatch(command: Extract<OutreachCommand, { kind: 'update' }>, item: Preparation): boolean {
  const data = command.data;
  if (Object.hasOwn(data, 'contact_id')) {
    if(data.contact_id===null){if(item.selected_contact!==null||item.contact_status!=='not_selected')return false;}
    else if(!command.observedContact||item.contact_status!=='eligible'||item.selected_contact?.id!==data.contact_id
      ||canonical(item.selected_contact)!==canonical(command.observedContact))return false;
  }
  if (Object.hasOwn(data, 'evaluation_run_id') && item.evaluation_run_id !== data.evaluation_run_id) return false;
  if (Object.hasOwn(data, 'work_ids') && !sameIds(item.works.map(workItem => workItem.id), data.work_ids ?? [])) return false;
  if (Object.hasOwn(data, 'confirm_public_name')) {
    if (item.public_name_confirmed !== data.confirm_public_name) return false;
    if (data.confirm_public_name && (!item.public_name || item.name_confirmed_at === null)) return false;
    if (data.confirm_public_name === false && item.name_confirmed_at !== null) return false;
  }
  return true;
}

/** Stable local proof only; never included in the unchanged HTTP update body. */
function canonical(value:unknown):string{
  if(value===null||typeof value!=='object')return JSON.stringify(value);
  if(Array.isArray(value))return `[${value.map(canonical).join(',')}]`;
  return `{${Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>`${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
}

export function reconcileOutreachSelections(attempt: OutreachAttempt, preparations: Preparation[]): boolean {
  if (attempt.command.kind === 'freeze' || !Array.isArray(preparations)) return false;
  const command = attempt.command;
  if (command.kind === 'add') {
    return exactlyOne(preparations, item => item.activity_id === command.activityId && item.candidate_id === command.data.candidate_id && item.active) !== null;
  }
  if (command.kind === 'bulk') {
    const additions = command.data.add_candidate_ids ?? [], cancellations = command.data.cancel_selections ?? [];
    return additions.every(candidateId => exactlyOne(preparations, item => item.activity_id === command.activityId && item.candidate_id === candidateId && item.active) !== null)
      && cancellations.every(choice => exactlyOne(preparations, item => item.activity_id === command.activityId && item.id === choice.selection_id && !item.active && item.revision === choice.expected_revision + 1) !== null);
  }
  const item = exactlyOne(preparations, candidate => candidate.activity_id === command.activityId && candidate.id === command.id);
  if (!item || item.revision !== command.data.expected_revision + 1) return false;
  if (command.kind === 'cancel') return !item.active;
  return updatedFieldsMatch(command, item);
}

export function reconcileOutreachBatch(attempt: OutreachAttempt, batch: RecipientBatchDetail): boolean {
  if (attempt.command.kind !== 'freeze') return false;
  const input = attempt.input as Parameters<OutreachAPI['freeze']>[0], choices = input.data.recipients;
  if (batch.activity_id !== input.activityId || batch.request_id !== input.data.request_id || batch.recipient_count !== choices.length || batch.recipients.length !== choices.length) return false;
  return choices.every((choice, index) => {
    const recipient = batch.recipients[index], snapshot = recipient?.snapshot;
    return recipient?.selection_id === choice.selection_id && snapshot?.activity_id === input.activityId && snapshot?.id === choice.selection_id
      && snapshot.active && snapshot.revision === choice.expected_revision && snapshot.context_token === choice.context_token;
  });
}
