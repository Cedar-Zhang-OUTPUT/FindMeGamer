import type { CandidatePage } from '../shared/match';
import type { SavedSetCreate, SavedSetPage, SavedSetsAPI, SavedSetView } from '../shared/savedSets';
import { decodeCandidate, decodePage, identifier, integer, keys, object } from './match-validation';
import { decodeSavedSet } from './saved-set-validation';
import { savedSetOutcomeUnknown, validateSavedSetRequest, type SavedSetRequest } from './saved-set-transport';
export { savedSetOutcomeUnknown, validateSavedSetRequest } from './saved-set-transport';
export type { SavedSetRequest } from './saved-set-transport';

type Input<K extends keyof SavedSetsAPI> = Parameters<SavedSetsAPI[K]>[0];
const collection = '/api/v2/discovery/saved-sets';
function input(value: unknown, allowed: string[]) {
  const raw = object(value, 'input'); keys(raw, allowed, 'input'); return raw;
}
function pagination(raw: Record<string, unknown>): Record<string, string> {
  return { offset: String(integer(raw.offset === undefined ? 0 : raw.offset, 'input')),
    limit: String(integer(raw.limit === undefined ? 50 : raw.limit, 'input', 1, 100)) };
}

/** Main-only named-set methods; the IPC boundary adds the public Result envelope. */
export class SavedSetClient {
  constructor(private readonly request: (input: SavedSetRequest) => Promise<unknown>) {}
  private async send<T>(request: SavedSetRequest, decode: (value: unknown, request: SavedSetRequest) => T): Promise<T> {
    const valid = validateSavedSetRequest(request), value = await this.request(valid);
    try { return decode(value, valid); }
    catch (error) { throw valid.method === 'POST' ? savedSetOutcomeUnknown() : error; }
  }
  async list(value: Input<'list'>): Promise<SavedSetPage> {
    const raw = input(value, ['activityId', 'offset', 'limit']), activityId = identifier(raw.activityId, 'input');
    return this.send({ method: 'GET', path: `/api/v2/activities/${activityId}/saved-sets`, query: pagination(raw) },
      result => decodePage(result, item => decodeSavedSet(item, { activityId }), 100, item => item.id));
  }
  async detail(id: string): Promise<SavedSetView> {
    identifier(id, 'input');
    return this.send({ method: 'GET', path: `${collection}/${id}` }, result => decodeSavedSet(result, { id }));
  }
  async results(value: Input<'results'>): Promise<CandidatePage> {
    const raw = input(value, ['id', 'offset', 'limit', 'evidence', 'sort']), id = identifier(raw.id, 'input');
    const query = pagination(raw);
    for (const key of ['evidence', 'sort']) if (Object.hasOwn(raw, key)) query[key] = raw[key] as string;
    return this.send({ method: 'GET', path: `${collection}/${id}/results`, query },
      result => decodePage(result, decodeCandidate, 100, item => item.id));
  }
  async create(value: Input<'create'>): Promise<SavedSetView> {
    const raw = input(value, ['queryId', 'data', 'idempotencyKey']), queryId = identifier(raw.queryId, 'input');
    return this.send({ method: 'POST', path: `/api/v2/discovery/queries/${queryId}/saved-sets`, body: raw.data as SavedSetCreate, idempotencyKey: raw.idempotencyKey as string },
      (result, request) => decodeSavedSet(result, { queryId, input: request.method === 'POST' ? request.body : undefined }));
  }
}
