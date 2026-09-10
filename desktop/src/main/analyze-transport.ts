import { STEAM_REFERENCES_OPT_IN } from './steam-reference-opt-in';
import { randomUUID } from 'node:crypto';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';
import { exact, fail, identifier, integer, keys, object, target, text, UUID } from './analyze-validation';
export type AnalysisRequest = { method: 'GET'; path: string; query?: Record<string, string> } | { method: 'POST'; path: string; body?: Record<string, unknown>; idempotencyKey: string };
const detail = new RegExp(`^/api/v1/jobs/${UUID}$`), action = new RegExp(`^/api/v1/jobs/analysis/${UUID}/(retry|resume)$`), binding = new RegExp(`^/api/v2/library/creators/${UUID}/youtube-binding$`);
export function analysisWriteUnknown(): PublicFailure { return new PublicFailure('analysis_write_unknown', 'The request may have completed. Keep the original input and key before checking or retrying.', false); }
export function isAnalysisWrite(r: AnalysisRequest): boolean { return r.method === 'POST'; }
export function validateAnalysisRequest(v: AnalysisRequest): AnalysisRequest {
  const r = object(v, 'input'); if (typeof r.path !== 'string') fail('input');
  if (r.method === 'GET') {
    keys(r, ['method','path','query'], 'input'); if (r.path !== '/api/v1/jobs' && !detail.test(r.path)) fail('input');
    if (Object.hasOwn(r, 'query')) { if (r.path !== '/api/v1/jobs') fail('input'); const q = object(r.query, 'input'); keys(q, ['changed_after','limit'], 'input'); if (Object.hasOwn(q, 'changed_after')) text(q.changed_after, 'input'); if (Object.hasOwn(q, 'limit')) { if (typeof q.limit !== 'string' || !/^[1-9][0-9]*$/.test(q.limit)) fail('input'); integer(Number(q.limit), 'input', 1, 200); } }
    return r as unknown as AnalysisRequest;
  }
  keys(r, ['method','path','body','idempotencyKey'], 'input'); if (r.method !== 'POST' || typeof r.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(r.idempotencyKey)) fail('input');
  if (r.path === '/api/v2/library/games/steam-import') { const b = object(r.body, 'input'); keys(b, ['url','game_id','expected_revision'], 'input'); target('game', b.url, 'input'); if (Object.hasOwn(b, 'game_id') !== Object.hasOwn(b, 'expected_revision')) fail('input'); if (Object.hasOwn(b, 'game_id')) { identifier(b.game_id, 'input'); integer(b.expected_revision, 'input'); } }
  else if (binding.test(r.path)) { const b = exact(r.body, ['url','expected_revision'], 'input'), t = target('creator', b.url, 'input'); if (t.id.startsWith('x:')) fail('input'); integer(b.expected_revision, 'input'); }
  else if (r.path === '/api/v1/jobs/analysis') { const b = exact(r.body, ['url','target_type','mode'], 'input'); target(b.target_type, b.url, 'input'); if (!['create','reanalyze'].includes(b.mode as string)) fail('input'); }
  else if (action.test(r.path)) { if (r.path.endsWith('/retry')) exact(r.body, [], 'input'); else if (Object.hasOwn(r, 'body')) fail('input'); }
  else fail('input');
  return r as unknown as AnalysisRequest;
}
async function json(response: Response, limit = 8 * 1024 * 1024): Promise<unknown> {
  const large = () => new PublicFailure('response_too_large', 'The analysis response is too large.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw large(); } const reader = response.body?.getReader(); if (!reader) fail('response'); let size = 0; const parts: Uint8Array[] = [];
  while (true) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) { await reader.cancel(); throw large(); } parts.push(value); }
  try { return JSON.parse(Buffer.concat(parts).toString('utf8')); } catch { return fail('response'); }
}
async function failure(response: Response, mutation: boolean): Promise<PublicFailure> {
  let code: unknown; try { code = object(object(await json(response, 65536), 'response').error, 'response').code; } catch { /* Never expose upstream text. */ }
  if (mutation && response.status >= 500) return analysisWriteUnknown();
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'Update the workspace key in Settings.', false);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow this action.', false);
  if (response.status === 404) return new PublicFailure('analysis_not_found', 'The requested source or job was not found.', false);
  if (response.status === 409) {
    if (code === 'collection_disabled') return new PublicFailure('collection_disabled', 'Enable this source in Settings before continuing.', false);
    if (code === 'idempotency_key_conflict') return new PublicFailure('idempotency_key_conflict', 'This key belongs to different input. Review the original request.', false);
    return new PublicFailure('analysis_conflict', 'Refresh the record before trying this action again.', false);
  }
  if ([400,422].includes(response.status)) return new PublicFailure('request_invalid', 'Check the source URL, revision and analysis target.', false);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait before retrying.', !mutation);
  return new PublicFailure('service_error', 'The analysis service is unavailable.', !mutation && response.status >= 500);
}
export async function authenticatedAnalysisRequest(fetcher: Fetcher, connection: Connection, input: AnalysisRequest): Promise<unknown> {
  const r = validateAnalysisRequest(input); let url: URL; try { url = new URL(r.path, normalizeServiceUrl(connection.serviceUrl)); } catch { throw new PublicFailure('request_invalid', 'Check the service address.', false); }
  if (r.method === 'GET') for (const [k,v] of Object.entries(r.query ?? {})) url.searchParams.set(k,v); const mutation = isAnalysisWrite(r);
  try {
    const response = await fetcher(url.href, { method: r.method, ...(r.method === 'POST' && r.body !== undefined ? { body: JSON.stringify(r.body) } : {}), headers: { ...STEAM_REFERENCES_OPT_IN, Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(), ...(r.method === 'POST' ? { 'Idempotency-Key': r.idempotencyKey, ...(r.body !== undefined ? { 'Content-Type': 'application/json' } : {}) } : {}) }, credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw await failure(response, mutation); try { return await json(response); } catch (e) { throw mutation ? analysisWriteUnknown() : e; }
  } catch (e) { if (e instanceof PublicFailure) throw e; if (mutation) throw analysisWriteUnknown(); throw new PublicFailure('network_error', 'Could not reach the analysis service.', true); }
}
