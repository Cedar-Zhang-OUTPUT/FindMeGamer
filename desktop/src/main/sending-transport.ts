import { STEAM_REFERENCES_OPT_IN } from './steam-reference-opt-in';
import { randomUUID } from 'node:crypto';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';
import { fail, identifier, integer, keys, object, sendingBody } from './sending-validation';
export type SendingRequest = { method: 'GET'; path: string; query?: Record<string, string> } | { method: 'POST'; path: string; body: Record<string, unknown>; idempotencyKey?: string };
const uuid = '[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}';
const qualify = new RegExp(`^/api/v2/outreach/compositions/${uuid}/qualification$`), send = new RegExp(`^/api/v2/outreach/compositions/${uuid}/send-batches$`), batch = new RegExp(`^/api/v2/outreach/send-batches/${uuid}$`), batches = new RegExp(`^/api/v2/activities/${uuid}/send-batches$`), retry = new RegExp(`^/api/v2/outreach/deliveries/${uuid}/retry$`), resolve = new RegExp(`^/api/v2/outreach/deliveries/${uuid}/resolve$`);
const LIMIT = 8 * 1024 * 1024;
export function sendingWriteUnknown(): PublicFailure { return new PublicFailure('sending_write_unknown', 'This sending change may have completed. Check the original record. Retry final sending only with the original request, qualification, exclusions and key.', false); }
export function isSendingWrite(request: SendingRequest): boolean { return request.method !== 'GET' && !qualify.test(request.path); }
export function validateSendingRequest(v: SendingRequest): SendingRequest {
  const r = object(v, 'input'); if (typeof r.path !== 'string') fail('input');
  if (r.method === 'GET') { keys(r, ['method', 'path', 'query'], 'input'); if (!batch.test(r.path) && !batches.test(r.path)) fail('input'); if (Object.hasOwn(r, 'query')) { if (!batches.test(r.path)) fail('input'); const q = object(r.query, 'input'); keys(q, ['limit', 'offset'], 'input'); for (const [k, v] of Object.entries(q)) { if (typeof v !== 'string' || !/^(0|[1-9][0-9]*)$/.test(v)) fail('input'); integer(Number(v), 'input', k === 'limit' ? 1 : 0, k === 'limit' ? 100 : Number.MAX_SAFE_INTEGER); } } return r as unknown as SendingRequest; }
  if (r.method !== 'POST') fail('input'); const creation = send.test(r.path); keys(r, ['method', 'path', 'body', ...(creation ? ['idempotencyKey'] : [])], 'input');
  if (creation && (typeof r.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(r.idempotencyKey))) fail('input');
  const kind = creation ? 'send' : qualify.test(r.path) ? 'qualify' : retry.test(r.path) ? 'retry' : resolve.test(r.path) ? 'resolve' : fail('input');
  const body = sendingBody(r.body, kind); if (Buffer.byteLength(JSON.stringify(body)) > LIMIT) fail('input');
  return { method: 'POST', path: r.path, body, ...(creation ? { idempotencyKey: r.idempotencyKey as string } : {}) };
}
async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const large = () => new PublicFailure('response_too_large', 'The sending response is too large. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw large(); }
  const reader = response.body?.getReader(); if (!reader) fail('response'); const chunks: Uint8Array[] = []; let size = 0;
  while (true) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) { await reader.cancel(); throw large(); } chunks.push(value); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { fail('response'); }
}
function correlation(v: unknown): string | undefined { try { return identifier(v, 'response'); } catch { return undefined; } }
const safeErrors: Record<string, string> = {
  qualification_changed: 'Sources or sending choices changed. Check the current qualification.',
  qualification_not_ready: 'Repair or explicitly exclude incomplete members and keep at least one eligible recipient.',
  qualification_exclusion_unknown: 'Exclude only members of this composition.',
  account_already_invited: 'This account already has an invitation record. Review it before further action.',
  final_send_request_conflict: 'This request belongs to another final confirmation.',
  delivery_retry_not_allowed: 'Read the current delivery. Only a definite failure or pending dispatch can be retried.',
  delivery_not_unknown: 'Only an unresolved unknown submission can be verified.',
  send_queue_unavailable: 'The sending record was saved, but dispatch was unavailable. Read the existing record before continuing.',
  idempotency_key_conflict: 'This key belongs to different input. Keep and review the original request.',
};
async function httpFailure(response: Response, mutation: boolean): Promise<PublicFailure> {
  let code: unknown, id = correlation(response.headers.get('x-correlation-id'));
  try { const error = object(object(await boundedJSON(response, 64 * 1024), 'response').error, 'response'); code = error.code; id ??= correlation(error.correlation_id); } catch { /* Never forward service messages or addresses. */ }
  if (mutation && response.status === 503 && code === 'send_queue_unavailable') return new PublicFailure(code, safeErrors[code], false, id);
  if (mutation && response.status >= 500) return sendingWriteUnknown();
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if ([404, 409, 422].includes(response.status) && typeof code === 'string' && Object.hasOwn(safeErrors, code)) return new PublicFailure(code, safeErrors[code], false, id);
  if (response.status === 404) return new PublicFailure('sending_not_found', 'This sending record or route is unavailable.', false, id);
  if (response.status === 409) return new PublicFailure('sending_conflict', 'Read the current sending record and review the requested action.', false, id);
  if ([400, 422].includes(response.status)) return new PublicFailure('request_invalid', 'Check the qualification, exclusions and delivery attempt.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait before continuing.', !mutation, id);
  return new PublicFailure('service_error', 'The service could not complete this sending request.', !mutation && response.status >= 500, id);
}
export async function authenticatedSendingRequest(fetcher: Fetcher, connection: Connection, input: SendingRequest): Promise<unknown> {
  const request = validateSendingRequest(input); let url: URL;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)); } catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  if (request.method === 'GET') for (const [k, v] of Object.entries(request.query ?? {})) url.searchParams.set(k, v);
  const mutation = isSendingWrite(request);
  try { const response = await fetcher(url.href, { method: request.method, ...(request.method === 'POST' ? { body: JSON.stringify(request.body) } : {}), headers: { ...STEAM_REFERENCES_OPT_IN, Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(), ...(request.method === 'POST' ? { 'Content-Type': 'application/json', ...(request.idempotencyKey ? { 'Idempotency-Key': request.idempotencyKey } : {}) } : {}) }, credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw await httpFailure(response, mutation); try { return await boundedJSON(response); } catch (error) { throw mutation ? sendingWriteUnknown() : error; }
  } catch (error) { if (error instanceof PublicFailure) throw error; if (mutation) throw sendingWriteUnknown(); throw new PublicFailure('network_error', 'Could not reach the service. Check the connection and service address.', true); }
}
