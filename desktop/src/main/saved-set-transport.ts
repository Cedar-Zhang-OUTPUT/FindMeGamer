import { randomUUID } from 'node:crypto';
import type { SavedSetCreate } from '../shared/savedSets';
import { exactCandidateQueryOptions } from './match-transport';
import { fail, keys, object, UUID_PATTERN, UUID_SOURCE } from './match-validation';
import { normalizeServiceUrl } from './policies';
import { validateSavedSetBody } from './saved-set-validation';
import { PublicFailure, type Connection, type Fetcher } from './transport';

export type SavedSetRequest = { method: 'GET'; path: string; query?: Record<string, string> }
  | { method: 'POST'; path: string; body: SavedSetCreate; idempotencyKey: string };
const createRoute = new RegExp(`^/api/v2/discovery/queries/${UUID_SOURCE}/saved-sets$`);
const listRoute = new RegExp(`^/api/v2/activities/${UUID_SOURCE}/saved-sets$`);
const detailRoute = new RegExp(`^/api/v2/discovery/saved-sets/${UUID_SOURCE}$`);
const resultsRoute = new RegExp(`^/api/v2/discovery/saved-sets/${UUID_SOURCE}/results$`);
const LIMIT = 8 * 1024 * 1024;
export function savedSetOutcomeUnknown(): PublicFailure {
  return new PublicFailure('save_outcome_unknown', 'The named set may already be saved. Check saved sets or retry the same request ID, body, and key.', false);
}
export function validateSavedSetRequest(value: SavedSetRequest): SavedSetRequest {
  const raw = object(value, 'input'), { method, path } = raw;
  if (typeof path !== 'string') fail('input');
  if (method === 'GET') {
    keys(raw, ['method', 'path', 'query'], 'input');
    const list = listRoute.test(path), results = resultsRoute.test(path);
    if (!list && !results && !detailRoute.test(path)) fail('input');
    if (!Object.hasOwn(raw, 'query')) return { method, path };
    const query = object(raw.query, 'input');
    if (!results) keys(query, list ? ['offset', 'limit'] : [], 'input');
    return { method, path, query: exactCandidateQueryOptions(query) };
  }
  if (method !== 'POST' || !createRoute.test(path)) fail('input');
  keys(raw, ['method', 'path', 'body', 'idempotencyKey'], 'input');
  if (typeof raw.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(raw.idempotencyKey)) fail('input');
  return { method, path, body: validateSavedSetBody(raw.body), idempotencyKey: raw.idempotencyKey };
}
async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const oversized = () => new PublicFailure('response_too_large', 'The named-set response is too large. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw oversized(); }
  const reader = response.body?.getReader(); if (!reader) fail('response');
  const chunks: Uint8Array[] = []; let size = 0;
  while (true) {
    const { done, value } = await reader.read(); if (done) break;
    size += value.byteLength; if (size > limit) { await reader.cancel(); throw oversized(); }
    chunks.push(value);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { fail('response'); }
}
const safeErrors: Record<string, string> = {
  saved_set_request_conflict: 'This request ID belongs to different saved-set input. Check the original named set.',
  saved_set_members_invalid: 'Choose only candidates belonging to the original discovery query.',
  idempotency_key_conflict: 'This request key belongs to different input. Check the original save.',
  discovery_not_found: 'This activity, query, or named set is no longer available.',
};
function correlation(value: unknown): string | undefined { return typeof value === 'string' && UUID_PATTERN.test(value) ? value : undefined; }
async function httpFailure(response: Response, mutation: boolean): Promise<PublicFailure> {
  if (mutation && response.status >= 500) { await response.body?.cancel(); return savedSetOutcomeUnknown(); }
  let code: unknown, id = correlation(response.headers.get('x-correlation-id'));
  try {
    const envelope = object(await boundedJSON(response, 64 * 1024), 'response'), error = object(envelope.error, 'response');
    code = error.code; id ??= correlation(error.correlation_id);
  } catch { /* Only allowlisted codes and valid correlation IDs leave the main process. */ }
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if ([404, 409, 422].includes(response.status) && typeof code === 'string' && Object.hasOwn(safeErrors, code)) return new PublicFailure(code, safeErrors[code], false, id);
  if (response.status === 404) return new PublicFailure('saved_set_not_found', 'This named set or API route is not available. Check the service version.', false, id);
  if (response.status === 409) return new PublicFailure('save_conflict', 'Check saved sets before retrying this operation.', false, id);
  if ([400, 422].includes(response.status)) return new PublicFailure('request_invalid', 'Check the named-set name, candidate membership, and limits.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait before continuing.', !mutation, id);
  return new PublicFailure('service_error', 'The service could not complete the named-set request.', !mutation && response.status >= 500, id);
}
export async function authenticatedSavedSetRequest(fetcher: Fetcher, connection: Connection, input: SavedSetRequest): Promise<unknown> {
  const request = validateSavedSetRequest(input); let url: URL;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)); }
  catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  const mutation = request.method === 'POST';
  if (!mutation) for (const [name, value] of Object.entries(request.query ?? {})) url.searchParams.set(name, value);
  try {
    const response = await fetcher(url.href, {
      method: request.method, ...(mutation ? { body: JSON.stringify(request.body) } : {}),
      headers: { Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(),
        ...(mutation ? { 'Content-Type': 'application/json', 'Idempotency-Key': request.idempotencyKey } : {}) },
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) throw await httpFailure(response, mutation);
    try { return await boundedJSON(response); } catch (error) { throw mutation ? savedSetOutcomeUnknown() : error; }
  } catch (error) {
    if (error instanceof PublicFailure) throw error;
    if (mutation) throw savedSetOutcomeUnknown();
    throw new PublicFailure('network_error', 'Could not reach the service. Check the connection, service address, or system proxy.', true);
  }
}
