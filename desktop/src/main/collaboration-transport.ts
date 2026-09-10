import { STEAM_REFERENCES_OPT_IN } from './steam-reference-opt-in';
import { randomUUID } from 'node:crypto';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';
import { choice, collaborationBody, fail, followUp, identifier, integer, invitationStates, keys, object, sendingStates } from './collaboration-validation';
export type CollaborationRequest = { method: 'GET'; path: string; query?: Record<string, string> } | { method: 'POST'; path: string; body: Record<string, unknown>; idempotencyKey: string };
const uuid = '[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}';
const list = new RegExp(`^/api/v2/activities/${uuid}/invitations$`), detail = new RegExp(`^/api/v2/activities/${uuid}/invitations/${uuid}$`), creator = new RegExp(`^/api/v2/library/creators/${uuid}/invitations$`), write = new RegExp(`^/api/v2/activities/${uuid}/invitations/${uuid}/(update|responses)$`);
const LIMIT = 8 * 1024 * 1024;
export function collaborationWriteUnknown(): PublicFailure { return new PublicFailure('collaboration_write_unknown', 'This relationship change may have completed. Keep the original revision, input and key while checking the saved record.', false); }
export function isCollaborationWrite(input: CollaborationRequest): boolean { return input.method === 'POST'; }
export function validateCollaborationRequest(input: CollaborationRequest): CollaborationRequest {
  const r = object(input, 'input'); if (typeof r.path !== 'string') fail('input');
  if (r.method === 'GET') {
    keys(r, ['method', 'path', 'query'], 'input'); if (!list.test(r.path) && !detail.test(r.path) && !creator.test(r.path)) fail('input');
    if (Object.hasOwn(r, 'query')) {
      if (detail.test(r.path)) fail('input'); const q = object(r.query, 'input'); keys(q, ['limit', 'offset', ...(creator.test(r.path) ? ['activity_id'] : ['sending_state', 'invitation_state', 'follow_up_state'])], 'input');
      for (const [k, v] of Object.entries(q)) {
        if (k === 'limit' || k === 'offset') { if (typeof v !== 'string' || !/^(0|[1-9][0-9]*)$/.test(v)) fail('input'); integer(Number(v), 'input', k === 'limit' ? 1 : 0, k === 'limit' ? 200 : Number.MAX_SAFE_INTEGER); }
        else if (k === 'activity_id') identifier(v, 'input'); else choice(v, k === 'sending_state' ? sendingStates : k === 'invitation_state' ? invitationStates : followUp, 'input');
      }
    } return r as unknown as CollaborationRequest;
  }
  if (r.method !== 'POST' || !write.test(r.path)) fail('input'); keys(r, ['method', 'path', 'body', 'idempotencyKey'], 'input');
  if (typeof r.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(r.idempotencyKey)) fail('input');
  const body = collaborationBody(r.body, r.path.endsWith('/responses')); if (Buffer.byteLength(JSON.stringify(body)) > LIMIT) fail('input');
  return { method: 'POST', path: r.path, body, idempotencyKey: r.idempotencyKey };
}
async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const large = () => new PublicFailure('response_too_large', 'The collaboration response is too large. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw large(); }
  const reader = response.body?.getReader(); if (!reader) fail('response'); const chunks: Uint8Array[] = []; let size = 0;
  while (true) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) { await reader.cancel(); throw large(); } chunks.push(value); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { fail('response'); }
}
function correlation(value: unknown): string | undefined { try { return identifier(value, 'response'); } catch { return undefined; } }
const safeErrors: Record<string, string> = { collaboration_revision_conflict: 'This relationship changed. Read the current record before editing.', idempotency_key_conflict: 'This key belongs to different input. Keep and review the original request.' };
async function httpFailure(response: Response, mutation: boolean): Promise<PublicFailure> {
  let code: unknown, id = correlation(response.headers.get('x-correlation-id'));
  try { const error = object(object(await boundedJSON(response, 64 * 1024), 'response').error, 'response'); code = error.code; id ??= correlation(error.correlation_id); } catch { /* Never forward service text or recorded evidence. */ }
  if (mutation && response.status >= 500) return collaborationWriteUnknown();
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if (response.status === 409 && typeof code === 'string' && Object.hasOwn(safeErrors, code)) return new PublicFailure(code, safeErrors[code], false, id);
  if (response.status === 404) return new PublicFailure('collaboration_not_found', 'This relationship or route is unavailable.', false, id);
  if (response.status === 409) return new PublicFailure('collaboration_conflict', 'Read the current relationship and review the requested change.', false, id);
  if ([400, 422].includes(response.status)) return new PublicFailure('request_invalid', 'Check the relationship, progress and response evidence.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait before continuing.', !mutation, id);
  return new PublicFailure('service_error', 'The service could not complete this collaboration request.', !mutation && response.status >= 500, id);
}
export async function authenticatedCollaborationRequest(fetcher: Fetcher, connection: Connection, input: CollaborationRequest): Promise<unknown> {
  const request = validateCollaborationRequest(input); let url: URL;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)); } catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  if (request.method === 'GET') for (const [k, v] of Object.entries(request.query ?? {})) url.searchParams.set(k, v);
  const mutation = isCollaborationWrite(request);
  try {
    const response = await fetcher(url.href, { method: request.method, ...(request.method === 'POST' ? { body: JSON.stringify(request.body) } : {}), headers: { ...STEAM_REFERENCES_OPT_IN, Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(), ...(request.method === 'POST' ? { 'Content-Type': 'application/json', 'Idempotency-Key': request.idempotencyKey } : {}) }, credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw await httpFailure(response, mutation); try { return await boundedJSON(response); } catch (error) { throw mutation ? collaborationWriteUnknown() : error; }
  } catch (error) { if (error instanceof PublicFailure) throw error; if (mutation) throw collaborationWriteUnknown(); throw new PublicFailure('network_error', 'Could not reach the service. Check the connection and service address.', true); }
}
