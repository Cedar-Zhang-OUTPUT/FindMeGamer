import type { CreatorAPI, CreatorDetail, CreatorListInput, CreatorPage, WorkDetail, WorkListInput, WorkPage } from '../shared/creators';
import { bool, decodeCreator, decodePage, decodeWork, fail, identifier, integer, keys, object, platform, text } from './creator-validation';
import { creatorOutcomeUnknown, validateCreatorRequest, type CreatorRequest } from './creator-transport';
export type { CreatorRequest } from './creator-transport';
export { creatorOutcomeUnknown, validateCreatorRequest } from './creator-transport';

type Input<K extends keyof CreatorAPI> = Parameters<CreatorAPI[K]>[0];
const collection = '/api/v2/library/creators';
function pagination(raw: Record<string, unknown>): Record<string, string> {
  return { offset: String(integer(raw.offset === undefined ? 0 : raw.offset, 'input')), limit: String(integer(raw.limit === undefined ? 50 : raw.limit, 'input', 1, 100)) };
}
export class CreatorClient {
  constructor(private readonly request: (input: CreatorRequest) => Promise<unknown>) {}
  private send(input: CreatorRequest): Promise<unknown> { return this.request(validateCreatorRequest(input)); }
  private async mutate<T>(input: CreatorRequest, decode: (value: unknown) => T): Promise<T> {
    const value = await this.send(input);
    try { return decode(value); } catch { throw creatorOutcomeUnknown(); }
  }
  async list(input: CreatorListInput): Promise<CreatorPage> {
    const raw = object(input, 'input'); keys(raw, ['query', 'platform', 'language', 'onlyCollection', 'offset', 'limit'], 'input');
    const query = { query: raw.query === undefined ? '' : text(raw.query, 'input', 255),
      language: raw.language === undefined ? '' : text(raw.language, 'input', 255),
      only_collection: String(raw.onlyCollection === undefined ? false : bool(raw.onlyCollection, 'input')),
      ...(raw.platform === undefined ? {} : { platform: platform(raw.platform, 'input') }), ...pagination(raw) };
    return decodePage(await this.send({ method: 'GET', path: collection, query }), item => decodeCreator(item));
  }
  async detail(id: string): Promise<CreatorDetail> {
    identifier(id, 'input'); return decodeCreator(await this.send({ method: 'GET', path: `${collection}/${id}` }), id);
  }
  async create(input: Input<'create'>): Promise<CreatorDetail> {
    const raw = object(input, 'input'); keys(raw, ['data', 'idempotencyKey'], 'input');
    return this.mutate({ method: 'POST', path: collection, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, decodeCreator);
  }
  async update(input: Input<'update'>): Promise<CreatorDetail> { return this.creatorWrite(input, false); }
  async rebind(input: Input<'rebind'>): Promise<CreatorDetail> { return this.creatorWrite(input, true); }
  private async creatorWrite(input: Input<'update'> | Input<'rebind'>, rebind: boolean): Promise<CreatorDetail> {
    const raw = object(input, 'input'); keys(raw, ['id', 'data'], 'input'); const id = identifier(raw.id, 'input');
    return this.mutate({ method: rebind ? 'PUT' : 'PATCH', path: `${collection}/${id}${rebind ? '/identity' : ''}`, body: raw.data as Record<string, unknown> }, value => decodeCreator(value, id));
  }
  async createContact(input: Input<'createContact'>): Promise<CreatorDetail> {
    const raw = object(input, 'input'); keys(raw, ['creatorId', 'data', 'idempotencyKey'], 'input'); const id = identifier(raw.creatorId, 'input');
    return this.mutate({ method: 'POST', path: `${collection}/${id}/contacts`, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, value => decodeCreator(value, id));
  }
  async updateContact(input: Input<'updateContact'>): Promise<CreatorDetail> {
    const raw = object(input, 'input'); keys(raw, ['creatorId', 'contactId', 'data'], 'input'); const id = identifier(raw.creatorId, 'input'), contactId = identifier(raw.contactId, 'input');
    return this.mutate({ method: 'PATCH', path: `${collection}/${id}/contacts/${contactId}`, body: raw.data as Record<string, unknown> }, value => decodeCreator(value, id));
  }
  async works(input: WorkListInput): Promise<WorkPage> {
    const raw = object(input, 'input'); keys(raw, ['creatorId', 'includePreviousIdentity', 'offset', 'limit'], 'input');
    const id = identifier(raw.creatorId, 'input'); const history = raw.includePreviousIdentity === undefined ? false : bool(raw.includePreviousIdentity, 'input');
    return decodePage(await this.send({ method: 'GET', path: `${collection}/${id}/works`, query: { include_previous_identity: String(history), ...pagination(raw) } }), value => {
      const work = decodeWork(value, id); if (!history && !work.is_current_identity) fail('response'); return work;
    });
  }
  async createWork(input: Input<'createWork'>): Promise<WorkDetail> {
    const raw = object(input, 'input'); keys(raw, ['creatorId', 'data', 'idempotencyKey'], 'input'); const id = identifier(raw.creatorId, 'input');
    return this.mutate({ method: 'POST', path: `${collection}/${id}/works`, body: raw.data as Record<string, unknown>, idempotencyKey: raw.idempotencyKey as string }, value => decodeWork(value, id));
  }
  async updateWork(input: Input<'updateWork'>): Promise<WorkDetail> {
    const raw = object(input, 'input'); keys(raw, ['creatorId', 'workId', 'data'], 'input'); const id = identifier(raw.creatorId, 'input'), workId = identifier(raw.workId, 'input');
    return this.mutate({ method: 'PATCH', path: `${collection}/${id}/works/${workId}`, body: raw.data as Record<string, unknown> }, value => decodeWork(value, id, workId));
  }
}
