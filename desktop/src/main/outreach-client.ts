import type * as DTO from '../shared/outreach';
import { decodeBulkResult, decodePreparation, decodeRecipientBatch, decodeRecipientBatchPage, decodeSelectionPage,
  fail, identifier, integer, keys, object } from './outreach-validation';
import { outreachOutcomeUnknown, validateOutreachRequest, type OutreachRequest } from './outreach-transport';

export type { OutreachRequest } from './outreach-transport';
export { decodePreparation, decodeRecipientBatch, outreachOutcomeUnknown, validateOutreachRequest };
type Input<K extends keyof DTO.OutreachAPI> = Parameters<DTO.OutreachAPI[K]>[0];
const same = (actual: string, expected: string) => actual.toLowerCase() === expected.toLowerCase();

function input(value: unknown, allowed: readonly string[]): Record<string, unknown> {
  const raw = object(value, 'input'); keys(raw, allowed, 'input'); return raw;
}
function pagination(raw: Record<string, unknown>): Record<string, string> {
  return { offset: String(integer(raw.offset === undefined ? 0 : raw.offset, 'input')),
    limit: String(integer(raw.limit === undefined ? 50 : raw.limit, 'input', 1, 200)) };
}

/** Main-process client. IPC wraps these unwrapped methods in the public Result envelope. */
export class OutreachClient {
  constructor(private readonly request: (input: OutreachRequest) => Promise<unknown>) {}

  private async send<T>(request: OutreachRequest, decode: (value: unknown) => T): Promise<T> {
    const valid = validateOutreachRequest(request), value = await this.request(valid);
    try { return decode(value); } catch (error) { if (valid.method === 'POST') throw outreachOutcomeUnknown(); throw error; }
  }

  async selections(value: Input<'selections'>): Promise<DTO.SelectionPage> {
    const raw = input(value, ['activityId', 'includeCancelled', 'offset', 'limit']), activityId = identifier(raw.activityId, 'input');
    if (Object.hasOwn(raw, 'includeCancelled') && typeof raw.includeCancelled !== 'boolean') fail('input');
    const query = { ...(Object.hasOwn(raw, 'includeCancelled') ? { include_cancelled: String(raw.includeCancelled) } : {}), ...pagination(raw) };
    return this.send({ method: 'GET', path: `/api/v2/activities/${activityId}/selections`, query }, result => decodeSelectionPage(result, activityId));
  }

  async selection(value: Input<'selection'>): Promise<DTO.Preparation> {
    const raw = input(value, ['activityId', 'id']), activityId = identifier(raw.activityId, 'input'), id = identifier(raw.id, 'input');
    return this.send({ method: 'GET', path: `/api/v2/activities/${activityId}/selections/${id}` }, result => decodePreparation(result, id, activityId));
  }

  async add(value: Input<'add'>): Promise<DTO.Preparation> {
    const raw = input(value, ['activityId', 'data', 'idempotencyKey']), activityId = identifier(raw.activityId, 'input');
    const data = object(raw.data, 'input'); identifier(data.candidate_id, 'input');
    return this.send({ method: 'POST', path: `/api/v2/activities/${activityId}/selections`, body: data, idempotencyKey: raw.idempotencyKey as string },
      result => decodePreparation(result, undefined, activityId));
  }

  async bulk(value: Input<'bulk'>): Promise<DTO.SelectionBulkResult> {
    const raw = input(value, ['activityId', 'data', 'idempotencyKey']), activityId = identifier(raw.activityId, 'input');
    return this.send({ method: 'POST', path: `/api/v2/activities/${activityId}/selections/bulk`, body: object(raw.data, 'input'),
      idempotencyKey: raw.idempotencyKey as string }, decodeBulkResult);
  }

  async update(value: Input<'update'>): Promise<DTO.Preparation> {
    const raw = input(value, ['activityId', 'id', 'data', 'idempotencyKey']), activityId = identifier(raw.activityId, 'input'), id = identifier(raw.id, 'input');
    return this.send({ method: 'POST', path: `/api/v2/activities/${activityId}/selections/${id}/update`, body: object(raw.data, 'input'),
      idempotencyKey: raw.idempotencyKey as string }, result => decodePreparation(result, id, activityId));
  }

  async cancel(value: Input<'cancel'>): Promise<DTO.Preparation> {
    const raw = input(value, ['activityId', 'id', 'data', 'idempotencyKey']), activityId = identifier(raw.activityId, 'input'), id = identifier(raw.id, 'input');
    return this.send({ method: 'POST', path: `/api/v2/activities/${activityId}/selections/${id}/cancel`, body: object(raw.data, 'input'),
      idempotencyKey: raw.idempotencyKey as string }, result => decodePreparation(result, id, activityId));
  }

  async batches(value: Input<'batches'>): Promise<DTO.RecipientBatchPage> {
    const raw = input(value, ['activityId', 'offset', 'limit']), activityId = identifier(raw.activityId, 'input');
    return this.send({ method: 'GET', path: `/api/v2/activities/${activityId}/recipient-batches`, query: pagination(raw) }, result => decodeRecipientBatchPage(result, activityId));
  }

  async batch(value: Input<'batch'>): Promise<DTO.RecipientBatchDetail> {
    const raw = input(value, ['activityId', 'id']), activityId = identifier(raw.activityId, 'input'), id = identifier(raw.id, 'input');
    return this.send({ method: 'GET', path: `/api/v2/activities/${activityId}/recipient-batches/${id}` }, result => decodeRecipientBatch(result, id, activityId));
  }

  async freeze(value: Input<'freeze'>): Promise<DTO.RecipientBatchDetail> {
    const raw = input(value, ['activityId', 'data', 'idempotencyKey']), activityId = identifier(raw.activityId, 'input'), data = object(raw.data, 'input');
    const requestId = identifier(data.request_id, 'input');
    return this.send({ method: 'POST', path: `/api/v2/activities/${activityId}/recipient-batches`, body: data, idempotencyKey: raw.idempotencyKey as string }, result => {
      const batch = decodeRecipientBatch(result, undefined, activityId);
      const choices = data.recipients as { selection_id: string; expected_revision: number; context_token: string }[];
      if (!same(batch.request_id, requestId) || batch.recipients.length !== choices.length || batch.recipients.some((recipient, index) =>
        !same(recipient.selection_id, choices[index].selection_id) || recipient.snapshot.revision !== choices[index].expected_revision
        || recipient.snapshot.context_token !== choices[index].context_token)) throw outreachOutcomeUnknown();
      return batch;
    });
  }
}
