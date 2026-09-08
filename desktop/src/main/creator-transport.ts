import { randomUUID } from 'node:crypto';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';
import { body, creatorSort, fail, integer, keys, languageList, object, platform, platformList, text, UUID_PATTERN, UUID_SOURCE, type BodyKind } from './creator-validation';

type CreatorQuery = Record<string, string | string[]>;

export type CreatorRequest =
  | { method: 'GET'; path: string; query?: CreatorQuery }
  | { method: 'POST'; path: string; body: Record<string, unknown>; idempotencyKey: string }
  | { method: 'PATCH' | 'PUT'; path: string; body: Record<string, unknown> };
const collection = '/api/v2/library/creators';
const detail = new RegExp(`^${collection}/${UUID_SOURCE}$`);
const identity = new RegExp(`^${collection}/${UUID_SOURCE}/identity$`);
const contacts = new RegExp(`^${collection}/${UUID_SOURCE}/contacts$`);
const contact = new RegExp(`^${collection}/${UUID_SOURCE}/contacts/${UUID_SOURCE}$`);
const works = new RegExp(`^${collection}/${UUID_SOURCE}/works$`);
const work = new RegExp(`^${collection}/${UUID_SOURCE}/works/${UUID_SOURCE}$`);
const LIMIT = 8 * 1024 * 1024;

export function creatorOutcomeUnknown(): PublicFailure {
  return new PublicFailure('save_outcome_unknown', 'The save result could not be confirmed. Reload the Creator and its contacts or works before saving again; do not start a duplicate save.', false);
}
function query(value: unknown, allowed: string[]): CreatorQuery {
  const raw = object(value, 'input'); keys(raw, allowed, 'input');
  return Object.fromEntries(Object.entries(raw).map(([name, value]) => {
    if (name === 'platforms') return [name, platformList(value, 'input')];
    if (name === 'languages') return [name, languageList(value, 'input')];
    const result = text(value, 'input', 255);
    if (['offset', 'limit'].includes(name)) {
      if (!/^(0|[1-9][0-9]*)$/.test(result)) fail('input');
      integer(Number(result), 'input', name === 'limit' ? 1 : 0, name === 'limit' ? 100 : Number.MAX_SAFE_INTEGER);
    } else if (['only_collection', 'include_previous_identity'].includes(name)) {
      if (!['true', 'false'].includes(result)) fail('input');
    } else if (name === 'platform') platform(result, 'input');
    else if (name === 'sort') creatorSort(result, 'input');
    return [name, result];
  }));
}
export function validateCreatorRequest(value: CreatorRequest): CreatorRequest {
  const raw = object(value, 'input'); const { method, path } = raw;
  if (typeof path !== 'string') fail('input');
  if (method === 'GET') {
    keys(raw, ['method', 'path', 'query'], 'input');
    if (path !== collection && !detail.test(path) && !works.test(path)) fail('input');
    const allowed = path === collection ? ['query', 'platform', 'language', 'platforms', 'languages', 'sort', 'only_collection', 'offset', 'limit']
      : works.test(path) ? ['include_previous_identity', 'offset', 'limit'] : [];
    return { method, path, ...(Object.hasOwn(raw, 'query') ? { query: query(raw.query, allowed) } : {}) };
  }
  keys(raw, method === 'POST' ? ['method', 'path', 'body', 'idempotencyKey'] : ['method', 'path', 'body'], 'input');
  let operation: BodyKind;
  if (method === 'POST' && path === collection) operation = 'creatorCreate';
  else if (method === 'PATCH' && detail.test(path)) operation = 'creatorPatch';
  else if (method === 'PUT' && identity.test(path)) operation = 'identity';
  else if (method === 'POST' && contacts.test(path)) operation = 'contactCreate';
  else if (method === 'PATCH' && contact.test(path)) operation = 'contactPatch';
  else if (method === 'POST' && works.test(path)) operation = 'workCreate';
  else if (method === 'PATCH' && work.test(path)) operation = 'workPatch';
  else fail('input');
  const result = body(raw.body, operation);
  if (Buffer.byteLength(JSON.stringify(result)) > LIMIT) fail('input');
  if (method === 'POST') {
    if (typeof raw.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(raw.idempotencyKey)) fail('input');
    return { method, path, body: result, idempotencyKey: raw.idempotencyKey };
  }
  return { method: method as 'PUT' | 'PATCH', path, body: result };
}
async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const tooLarge = () => new PublicFailure('response_too_large', 'The Creator response is too large. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw tooLarge(); }
  const reader = response.body?.getReader(); if (!reader) fail('response');
  const chunks: Uint8Array[] = []; let size = 0;
  while (true) {
    const { done, value } = await reader.read(); if (done) break;
    size += value.byteLength; if (size > limit) { await reader.cancel(); throw tooLarge(); } chunks.push(value);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { fail('response'); }
}
const safeErrors: Record<string, string> = {
  creator_revision_conflict: 'This Creator changed elsewhere. Reload and review your edits before saving.',
  work_revision_conflict: 'This work changed elsewhere. Reload and review your edits before saving.',
  creator_identity_changed: 'The source account changed. Reload and review the current identity before saving.',
  creator_identity_conflict: 'Another Creator already uses this source account. Review the existing Creator.',
  creator_contact_conflict: 'An active contact already uses this email. Review the existing contacts.',
  creator_analysis_in_progress: 'Creator analysis is in progress. Wait for it to finish, then reload.',
  creator_delivery_in_progress: 'A delivery is in progress for this Creator. Wait for it to finish, then reload.',
  creator_not_found: 'This Creator is no longer available.',
  creator_contact_not_found: 'This Creator contact is no longer available.',
  creator_work_not_found: 'This Creator work is no longer available.',
  game_not_found: 'The referenced game is no longer available. Review the selected game.',
  idempotency_key_conflict: 'This save key belongs to different input. Check the previous save before starting another.',
};
function correlation(value: unknown): string | undefined { return typeof value === 'string' && UUID_PATTERN.test(value) ? value : undefined; }
async function httpFailure(response: Response, mutation: boolean): Promise<PublicFailure> {
  let id = correlation(response.headers.get('x-correlation-id'));
  if (mutation && response.status >= 500) { await response.body?.cancel(); return creatorOutcomeUnknown(); }
  let code: unknown;
  try {
    const envelope = object(await boundedJSON(response, 64 * 1024), 'response'); const error = object(envelope.error, 'response');
    code = error.code; id ??= correlation(error.correlation_id);
  } catch { /* Upstream exception messages and payloads never cross IPC. */ }
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if ([404, 409, 422].includes(response.status) && typeof code === 'string' && Object.hasOwn(safeErrors, code)) return new PublicFailure(code, safeErrors[code], false, id);
  if (response.status === 404) return new PublicFailure('creator_not_found', 'This Creator or API route is no longer available.', false, id);
  if (response.status === 409) return new PublicFailure('save_conflict', 'This save conflicts with existing data. Reload and review before saving again.', false, id);
  if (response.status === 422 || response.status === 400) return new PublicFailure('request_invalid', 'Check the Creator fields and required values before saving.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait a moment before continuing.', !mutation, id);
  return new PublicFailure('service_error', 'The service could not complete this Creator request.', !mutation && response.status >= 500, id);
}
export async function authenticatedCreatorRequest(fetcher: Fetcher, connection: Connection, input: CreatorRequest): Promise<unknown> {
  const request = validateCreatorRequest(input);
  let url: URL;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)); }
  catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  if ('query' in request) for (const [name, value] of Object.entries(request.query ?? {})) {
    if (Array.isArray(value)) for (const item of value) url.searchParams.append(name, item);
    else url.searchParams.set(name, value);
  }
  const mutation = request.method !== 'GET';
  try {
    const response = await fetcher(url.href, { method: request.method,
      ...('body' in request ? { body: JSON.stringify(request.body) } : {}),
      headers: { Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(),
        ...(mutation ? { 'Content-Type': 'application/json' } : {}), ...(request.method === 'POST' ? { 'Idempotency-Key': request.idempotencyKey } : {}) },
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw await httpFailure(response, mutation);
    try { return await boundedJSON(response); } catch (error) { throw mutation ? creatorOutcomeUnknown() : error; }
  } catch (error) {
    if (error instanceof PublicFailure) throw error;
    if (mutation) throw creatorOutcomeUnknown();
    throw new PublicFailure('network_error', 'Could not reach the service. Check the connection, service address, or system proxy.', true);
  }
}
