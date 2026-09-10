import { GAME_FIELDS, GAME_SORTS, GAME_WEBSITE_STATUSES } from '../shared/games';
import type { CreateGameInput, GameDetail, GameField, GameFields, GameListInput, GamePage,
  ReferenceWork, UpdateGameInput } from '../shared/games';
import type { JsonObject, JsonValue } from '../shared/library';
import { PublicFailure, saveOutcomeUnknown } from './transport';
import type { GameRequest } from './transport';
import { decodeSteamRecommendations, validateReferenceSource } from './game-provenance-validation';

type Mode = 'input' | 'response';
export type GameRequestHandler = (input: GameRequest) => Promise<unknown>;
const collection = '/api/v2/library/games';
const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
const steamId = /^[1-9][0-9]{0,19}$/;
const fieldNames: readonly string[] = GAME_FIELDS;
const metadata = ['id', 'revision', 'favorite', 'reference_works', 'source_fields', 'manual_overrides',
  'overridden_fields', 'source_identity', 'last_analyzed_at', 'next_analysis_at', 'created_at', 'updated_at', 'steam_recommendations'];

function fail(mode: Mode): never {
  throw new PublicFailure(mode === 'input' ? 'request_invalid' : 'invalid_response', mode === 'input'
    ? 'Check the game fields, required name or website, and source URLs before saving.'
    : 'The service returned an unsupported Game response. Reload or check the service version.', false);
}

function object(value: unknown, mode: Mode): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail(mode);
  return value as Record<string, unknown>;
}

function keys(value: Record<string, unknown>, allowed: readonly string[], mode: Mode) {
  if (Object.keys(value).some(key => !allowed.includes(key))) fail(mode);
}

function integer(value: unknown, min: number, max: number, mode: Mode): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) fail(mode);
  return value;
}

function boolean(value: unknown, mode: Mode): boolean {
  if (typeof value !== 'boolean') fail(mode);
  return value;
}

function identifier(value: unknown, mode: Mode): string {
  if (typeof value !== 'string' || !uuid.test(value)) fail(mode);
  return value;
}

function nullableString(value: unknown, mode: Mode): string | null {
  if (value !== null && typeof value !== 'string') fail(mode);
  return value;
}

function scalar(value: unknown, field: string, mode: Mode): string | null {
  const raw = nullableString(value, mode);
  if (raw === null) return null;
  const result = raw.trim() || null;
  if (result === null) return null;
  const limit = field === 'description' || field === 'reason' ? 20_000
    : ['website_url', 'cover_url', 'url'].includes(field) ? 2048 : 255;
  if ([...result].length > limit) fail(mode);
  if (field === 'steam_app_id' && !steamId.test(result)) fail(mode);
  if (['website_url', 'cover_url', 'url'].includes(field)) {
    try {
      const url = new URL(result);
      const authority = result.match(/^https?:\/\/([^/?#]*)/i)?.[1];
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password
        || authority?.includes('@')) fail(mode);
    } catch { fail(mode); }
  }
  return result;
}

function labels(value: unknown, mode: Mode): string[] {
  if (!Array.isArray(value) || value.length > 100) fail(mode);
  // Server owns its Unicode case-folding/deduplication. Never replace these with inferred tags.
  return Array.from(value, item => {
    if (typeof item !== 'string' || [...item].length < 1 || [...item].length > 255) fail(mode);
    return item;
  });
}

function fieldValue(value: unknown, field: string, mode: Mode): string | null | string[] {
  return field === 'tags' || field === 'languages' ? labels(value, mode) : scalar(value, field, mode);
}

function fields(raw: Record<string, unknown>): GameFields {
  return Object.fromEntries(GAME_FIELDS.map(field => [field, Object.hasOwn(raw, field)
    ? fieldValue(raw[field], field, 'response') : field === 'tags' || field === 'languages' ? [] : null])) as unknown as GameFields;
}

function reference(value: unknown, mode: Mode): ReferenceWork {
  const raw = object(value, mode);
  keys(raw, ['id', 'name', 'url', 'similarities', 'reason', ...(mode === 'response' ? ['source', 'source_url'] : [])], mode);
  const output: Record<string, unknown> = {};
  if (mode === 'response') { validateReferenceSource(raw); for (const key of ['source', 'source_url']) if (Object.hasOwn(raw, key)) output[key] = raw[key]; }
  for (const field of ['name', 'url', 'reason']) {
    if (Object.hasOwn(raw, field)) output[field] = scalar(raw[field], field, mode);
    else if (mode === 'response') output[field] = null;
  }
  if (!output.name && !output.url) fail(mode);
  if (Object.hasOwn(raw, 'id')) output.id = raw.id === null ? null : identifier(raw.id, mode);
  else if (mode === 'response') output.id = null;
  if (Object.hasOwn(raw, 'similarities')) output.similarities = labels(raw.similarities, mode);
  else if (mode === 'response') output.similarities = [];
  return output as unknown as ReferenceWork;
}

function references(value: unknown, mode: Mode): ReferenceWork[] {
  // The server limits replacement input to 100, but GameDetail's source list is unbounded.
  if (!Array.isArray(value) || (mode === 'input' && value.length > 100)) fail(mode);
  return Array.from(value, item => reference(item, mode));
}

function jsonObject(value: unknown): JsonObject {
  object(value, 'response');
  const active = new WeakSet<object>();
  let nodes = 0;
  function clone(item: unknown, depth: number): JsonValue {
    if (++nodes > 10_000 || depth > 32) fail('response');
    if (item === null || typeof item === 'string' || typeof item === 'boolean') return item;
    if (typeof item === 'number') return Number.isFinite(item) ? item : fail('response');
    if (typeof item !== 'object' || item === null || active.has(item)) fail('response');
    active.add(item);
    const result: JsonValue = Array.isArray(item) ? Array.from(item, child => clone(child, depth + 1))
      : Object.fromEntries(Object.entries(object(item, 'response')).map(([key, child]) => {
        if ([...key].length > 512) fail('response');
        return [key, clone(child, depth + 1)];
      }));
    active.delete(item);
    return result;
  }
  return clone(value, 0) as JsonObject;
}

function timestamp(value: unknown): string | null {
  const result = nullableString(value, 'response');
  if (result !== null && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(result)
    || !Number.isFinite(Date.parse(result)))) fail('response');
  if (result !== null) {
    const [year, month, day, hour, minute, second] = result.slice(0,19).split(/[-T:]/i).map(Number);
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (month < 1 || month > 12 || day < 1 || day > days[month-1] || hour > 23 || minute > 59 || second > 59) fail('response');
  }
  return result;
}

export function decodeDetail(value: unknown, expectedId?: string): GameDetail {
  const raw = object(value, 'response');
  keys(raw, [...fieldNames, ...metadata], 'response');
  const id = identifier(raw.id, 'response');
  if (expectedId && id.toLowerCase() !== expectedId.toLowerCase()) fail('response');
  const source = object(raw.source_fields, 'response');
  keys(source, fieldNames, 'response');
  const identity = object(raw.source_identity, 'response');
  keys(identity, ['steam_app_id', 'canonical_url'], 'response');
  if (!Array.isArray(raw.overridden_fields) || raw.overridden_fields.some(field => !fieldNames.includes(field))) fail('response');
  return { ...fields(raw), id, revision: integer(raw.revision, 0, Number.MAX_SAFE_INTEGER, 'response'),
    favorite: boolean(raw.favorite, 'response'), reference_works: references(raw.reference_works, 'response'),
    ...(Object.hasOwn(raw, 'steam_recommendations') ? { steam_recommendations: decodeSteamRecommendations(raw.steam_recommendations) } : {}),
    source_fields: fields(source), manual_overrides: jsonObject(raw.manual_overrides),
    overridden_fields: [...raw.overridden_fields] as GameField[],
    // Acquisition binding must not be reconstructed from editable website/Steam values.
    source_identity: { steam_app_id: nullableString(identity.steam_app_id, 'response'),
      canonical_url: nullableString(identity.canonical_url, 'response') },
    last_analyzed_at: timestamp(raw.last_analyzed_at), next_analysis_at: timestamp(raw.next_analysis_at),
    ...(Object.hasOwn(raw,'created_at') ? {created_at:timestamp(raw.created_at)} : {}),
    ...(Object.hasOwn(raw,'updated_at') ? {updated_at:timestamp(raw.updated_at)} : {}) };
}

function body(value: unknown, patch: boolean): Record<string, unknown> {
  const raw = object(value, 'input');
  keys(raw, [...fieldNames, 'favorite', 'reference_works', ...(patch ? ['expected_revision', 'reset_fields'] : [])], 'input');
  const result: Record<string, unknown> = {};
  for (const field of GAME_FIELDS) {
    if (Object.hasOwn(raw, field)) result[field] = fieldValue(raw[field], field, 'input');
  }
  if (Object.hasOwn(raw, 'favorite')) result.favorite = boolean(raw.favorite, 'input');
  if (Object.hasOwn(raw, 'reference_works')) result.reference_works = references(raw.reference_works, 'input');
  if (!patch && !result.name && !result.website_url) fail('input');
  if (patch) {
    result.expected_revision = integer(raw.expected_revision, 0, Number.MAX_SAFE_INTEGER, 'input');
    if (Object.hasOwn(raw, 'reset_fields')) {
      if (!Array.isArray(raw.reset_fields) || raw.reset_fields.length > 9
        || raw.reset_fields.some(field => typeof field !== 'string' || !fieldNames.includes(field) || Object.hasOwn(raw, field))) fail('input');
      result.reset_fields = [...raw.reset_fields];
    }
    // Partial edits may legitimately depend on the current/source identity. Only an explicit
    // clear of both effective identity fields is knowably invalid without another request.
    if (Object.hasOwn(result, 'name') && Object.hasOwn(result, 'website_url') && !result.name && !result.website_url) fail('input');
  }
  return result;
}

export class GameClient {
  constructor(private readonly request: GameRequestHandler) {}

  async list(input: GameListInput): Promise<GamePage> {
    const raw = object(input, 'input');
    keys(raw, ['query', 'onlyCollection', 'websiteStatus', 'sort', 'offset', 'limit'], 'input');
    if (raw.websiteStatus !== undefined && !(GAME_WEBSITE_STATUSES as readonly unknown[]).includes(raw.websiteStatus)) fail('input');
    if (raw.sort !== undefined && !(GAME_SORTS as readonly unknown[]).includes(raw.sort)) fail('input');
    const query = raw.query === undefined ? '' : raw.query;
    if (typeof query !== 'string' || [...query].length > 255) fail('input');
    const offset = integer(raw.offset === undefined ? 0 : raw.offset, 0, Number.MAX_SAFE_INTEGER, 'input');
    const limit = integer(raw.limit === undefined ? 50 : raw.limit, 1, 100, 'input');
    const onlyCollection = raw.onlyCollection === undefined ? false : boolean(raw.onlyCollection, 'input');
    const page = object(await this.request({ method: 'GET', path: collection,
      query: { query, only_collection: String(onlyCollection), offset: String(offset), limit: String(limit),
        ...(raw.websiteStatus === undefined ? {} : {website_status:raw.websiteStatus as string}),
        ...(raw.sort === undefined ? {} : {sort:raw.sort as string}) } }), 'response');
    keys(page, ['items', 'total', 'offset', 'limit'], 'response');
    if (!Array.isArray(page.items)) fail('response');
    return { items: Array.from(page.items, item => decodeDetail(item)),
      total: integer(page.total, 0, Number.MAX_SAFE_INTEGER, 'response'),
      offset: integer(page.offset, 0, Number.MAX_SAFE_INTEGER, 'response'), limit: integer(page.limit, 1, 100, 'response') };
  }

  async detail(id: string): Promise<GameDetail> {
    identifier(id, 'input');
    return decodeDetail(await this.request({ method: 'GET', path: `${collection}/${id}` }), id);
  }

  async create(input: CreateGameInput): Promise<GameDetail> {
    const raw = object(input, 'input'); keys(raw, ['data', 'idempotencyKey'], 'input');
    if (typeof raw.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(raw.idempotencyKey)) fail('input');
    const data = body(raw.data, false);
    const result = await this.request({ method: 'POST', path: collection, body: data, idempotencyKey: raw.idempotencyKey });
    try { return decodeDetail(result); } catch { throw saveOutcomeUnknown(); }
  }

  async update(input: UpdateGameInput): Promise<GameDetail> {
    const raw = object(input, 'input'); keys(raw, ['id', 'data'], 'input');
    const id = identifier(raw.id, 'input');
    const data = body(raw.data, true);
    const result = await this.request({ method: 'PATCH', path: `${collection}/${id}`, body: data });
    try { return decodeDetail(result, id); } catch { throw saveOutcomeUnknown(); }
  }
}
