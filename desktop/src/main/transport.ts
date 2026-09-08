import { randomUUID } from 'node:crypto';
import type { PublicError, Result } from '../shared/bridge';
import { normalizeServiceUrl } from './policies';
import { GAME_SORTS, GAME_WEBSITE_STATUSES } from '../shared/games';

export class PublicFailure extends Error implements PublicError {
  constructor(public code: string, message: string, public retryable = false, public correlationId?: string) { super(message); }
}
export type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export interface Connection { serviceUrl: string; key: string }
const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const routePattern = new RegExp(`^/api/v1/(session|profiles/(games|creators)(/${UUID})?)$`);
const gameCollection = '/api/v2/library/games';
const gameDetailPattern = new RegExp(`^${gameCollection}/${UUID}$`);
const LIMIT = 8 * 1024 * 1024;
export type GameRequest =
  | { method: 'GET'; path: string; query?: Record<string, string> }
  | { method: 'POST'; path: string; body: Record<string, unknown>; idempotencyKey: string }
  | { method: 'PATCH'; path: string; body: Record<string, unknown> };

export function saveOutcomeUnknown(): PublicFailure {
  return new PublicFailure('save_outcome_unknown', 'The save result could not be confirmed. Check the game before saving again; do not start a duplicate save.', false);
}

async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const oversize = () => new PublicFailure('response_too_large', 'This response is too large to load. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw oversize(); }
  const reader = response.body?.getReader();
  if (!reader) throw new PublicFailure('invalid_response', 'The service returned an empty response.', true);
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) { await reader.cancel(); throw oversize(); }
    chunks.push(value);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new PublicFailure('invalid_response', 'The service did not return valid JSON. Check the service address or proxy.', true); }
}

export async function authenticatedGet(fetcher: Fetcher, connection: Connection, route: string, query: Record<string, string> = {}): Promise<unknown> {
  if (route === gameCollection || gameDetailPattern.test(route)) {
    return authenticatedGameRequest(fetcher, connection, { method: 'GET', path: route, query });
  }
  if (!routePattern.test(route)) throw new PublicFailure('request_invalid', 'This read operation is not available.');
  const url = requestURL(connection, route, query, ['query', 'only_collection', 'cursor', 'limit']);
  return perform(fetcher, connection, url, { method: 'GET' }, false);
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && [Object.prototype, null].includes(Object.getPrototypeOf(value));
}

function requestURL(connection: Connection, route: string, query: Record<string, string>, allowed: string[]): URL {
  if (!record(query)) throw new PublicFailure('request_invalid', 'Unsupported filter.');
  const url = new URL(route, normalizeServiceUrl(connection.serviceUrl));
  for (const [name, value] of Object.entries(query)) {
    if (!allowed.includes(name) || typeof value !== 'string') throw new PublicFailure('request_invalid', 'Unsupported filter.');
    url.searchParams.set(name, value);
  }
  return url;
}

export async function authenticatedGameRequest(fetcher: Fetcher, connection: Connection, input: GameRequest): Promise<unknown> {
  const invalid = () => new PublicFailure('request_invalid', 'This Game operation is not available.');
  if (!record(input)) throw invalid();
  const get = input.method === 'GET';
  const post = input.method === 'POST';
  const patch = input.method === 'PATCH';
  if ((!get && !post && !patch) || typeof input.path !== 'string') throw invalid();
  const allowed = get ? ['method', 'path', 'query'] : post ? ['method', 'path', 'body', 'idempotencyKey'] : ['method', 'path', 'body'];
  if (Object.keys(input).some(key => !allowed.includes(key))) throw invalid();
  if (get ? input.path !== gameCollection && !gameDetailPattern.test(input.path)
    : post ? input.path !== gameCollection : !gameDetailPattern.test(input.path)) throw invalid();
  const query = get && 'query' in input ? input.query : undefined;
  const url = requestURL(connection, input.path, query ?? {},
    input.path === gameCollection && get ? ['query', 'only_collection', 'website_status', 'sort', 'offset', 'limit'] : []);
  if (query?.website_status !== undefined && !(GAME_WEBSITE_STATUSES as readonly string[]).includes(query.website_status)) throw invalid();
  if (query?.sort !== undefined && !(GAME_SORTS as readonly string[]).includes(query.sort)) throw invalid();
  if (get) return perform(fetcher, connection, url, { method: 'GET' }, true);
  if (!('body' in input) || !record(input.body)) throw invalid();
  let body: string;
  try { body = JSON.stringify(input.body); } catch { throw invalid(); }
  if (Buffer.byteLength(body) > LIMIT) throw invalid();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (post) {
    if (!('idempotencyKey' in input) || typeof input.idempotencyKey !== 'string'
      || !/^[A-Za-z0-9._:-]{8,128}$/.test(input.idempotencyKey)) throw invalid();
    headers['Idempotency-Key'] = input.idempotencyKey;
  }
  return perform(fetcher, connection, url, { method: input.method, body, headers }, true);
}

function correlationID(value: unknown): string | undefined {
  return typeof value === 'string' && new RegExp(`^${UUID}$`).test(value) ? value : undefined;
}

async function httpFailure(response: Response, isWrite: boolean, isGame: boolean): Promise<PublicFailure> {
  let id = correlationID(response.headers.get('x-correlation-id'));
  if (isGame && response.status === 409) {
    let code: unknown;
    try {
      const envelope = await boundedJSON(response, 64 * 1024);
      if (record(envelope) && record(envelope.error)) {
        code = envelope.error.code;
        id ??= correlationID(envelope.error.correlation_id);
      }
    } catch { /* An unreadable conflict still remains a conflict, never a successful save. */ }
    const messages: Record<string, string> = {
      game_revision_conflict: 'This game changed elsewhere. Reload and review your edits before saving.',
      game_identity_conflict: 'Another game already uses this Steam ID. Review the existing game or change the ID.',
      idempotency_key_conflict: 'This save key belongs to different input. Check the previous save before starting a new one.',
    };
    if (typeof code === 'string' && Object.hasOwn(messages, code)) return new PublicFailure(code, messages[code], false, id);
    return new PublicFailure('save_conflict', 'The save conflicts with existing data. Reload and review before saving again.', false, id);
  }
  await response.body?.cancel();
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if (response.status === 404) return new PublicFailure(isGame ? 'game_not_found' : 'not_found', 'This profile or API route is no longer available.', false, id);
  if (response.status === 422) return new PublicFailure('request_invalid', isGame
    ? 'Check the game fields and required values, then save your corrected edits.'
    : 'Check the request and filters, then try again.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait a moment before continuing.', !isWrite, id);
  if (isWrite && response.status >= 500) return saveOutcomeUnknown();
  return new PublicFailure('service_error', `The service could not complete this request (HTTP ${response.status}).`, !isWrite && response.status >= 500, id);
}

async function perform(fetcher: Fetcher, connection: Connection, url: URL, init: RequestInit, isGame: boolean): Promise<unknown> {
  const isWrite = init.method !== 'GET';
  try {
    const response = await fetcher(url.href, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID() },
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) throw await httpFailure(response, isWrite, isGame);
    try { return await boundedJSON(response); }
    catch (error) { throw isWrite ? saveOutcomeUnknown() : error; }
  } catch (error) {
    if (error instanceof PublicFailure) throw error;
    if (isWrite) throw saveOutcomeUnknown();
    throw new PublicFailure('network_error', 'Could not reach the service. Check your connection, service address, or system proxy and retry.', true);
  }
}

export async function publicResult<T>(action: () => Promise<T>): Promise<Result<T>> {
  try { return { ok: true, data: await action() }; }
  catch (error) {
    if (error instanceof PublicFailure) return { ok: false, error: { code: error.code, message: error.message, retryable: error.retryable, ...(error.correlationId ? { correlationId: error.correlationId } : {}) } };
    // IPC errors are deliberately plain DTOs, never serialized Error objects or raw service exceptions.
    return { ok: false, error: { code: 'operation_failed', message: 'Could not complete this operation. Check Settings and try again.', retryable: true } };
  }
}
