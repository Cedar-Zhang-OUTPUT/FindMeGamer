import { STEAM_REFERENCES_OPT_IN } from './steam-reference-opt-in';
import { randomUUID } from 'node:crypto';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';
import { draftsBody, exact, fail, identifier, integer, keys, object, type BodyKind } from './drafts-validation';
export type DraftsRequest = { method: 'GET'; path: string; query?: Record<string, string> } | { method: 'POST' | 'PATCH'; path: string; body: Record<string, unknown>; idempotencyKey?: string };
const uuid = '[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}';
const templates = '/api/v2/outreach/template-versions';
const template = new RegExp(`^${templates}/${uuid}$`), compositions = new RegExp(`^/api/v2/activities/${uuid}/compositions$`), composition = new RegExp(`^/api/v2/outreach/compositions/${uuid}$`), draft = new RegExp(`^/api/v2/outreach/drafts/${uuid}$`), revision = new RegExp(`^/api/v2/outreach/drafts/${uuid}/(refresh|retry)$`), facts = new RegExp(`^/api/v2/outreach/compositions/${uuid}/sender-facts$`);
const LIMIT = 8 * 1024 * 1024;
export function draftWriteUnknown(): PublicFailure { return new PublicFailure('draft_write_unknown', 'The draft change may have completed. Read the current result before another revision change; creation may be retried only with its original request and key.', false); }
export const draftsOutcomeUnknown = draftWriteUnknown;
export function validateDraftsRequest(value: DraftsRequest): DraftsRequest {
  const r = object(value, 'input'); if (typeof r.path !== 'string') fail('input');
  if (r.method === 'GET') {
    keys(r, ['method', 'path', 'query'], 'input'); const catalog = r.path === templates, page = compositions.test(r.path);
    if (!catalog && !page && !template.test(r.path) && !composition.test(r.path)) fail('input');
    if (catalog) { const q = exact(r.query, ['game_id'], 'input'); identifier(q.game_id, 'input'); }
    else if (Object.hasOwn(r, 'query')) { if (!page) fail('input'); const q = object(r.query, 'input'); keys(q, ['offset', 'limit'], 'input'); for (const [k, v] of Object.entries(q)) { if (typeof v !== 'string' || !/^(0|[1-9][0-9]*)$/.test(v)) fail('input'); integer(Number(v), 'input', k === 'limit' ? 1 : 0, k === 'limit' ? 100 : Number.MAX_SAFE_INTEGER); } }
    return r as unknown as DraftsRequest;
  }
  if (r.method !== 'POST' && r.method !== 'PATCH') fail('input');
  let kind: BodyKind; const creation = r.method === 'POST' && (r.path === templates || r.path === templates + '/canonical' || compositions.test(r.path));
  keys(r, ['method', 'path', 'body', ...(creation ? ['idempotencyKey'] : [])], 'input');
  if (creation) { if (typeof r.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(r.idempotencyKey)) fail('input'); kind = r.path === templates ? 'template' : r.path.endsWith('/canonical') ? 'canonical' : 'composition'; }
  else if (r.method === 'PATCH' && draft.test(r.path)) kind = 'edit';
  else if (r.method === 'POST' && revision.test(r.path)) kind = 'revision';
  else if (r.method === 'POST' && facts.test(r.path)) kind = 'facts'; else fail('input');
  const body = draftsBody(r.body, kind); if (Buffer.byteLength(JSON.stringify(body)) > LIMIT) fail('input');
  return { method: r.method, path: r.path, body, ...(creation ? { idempotencyKey: r.idempotencyKey as string } : {}) };
}
async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const large = () => new PublicFailure('response_too_large', 'The draft response is too large. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw large(); }
  const reader = response.body?.getReader(); if (!reader) fail('response'); const chunks: Uint8Array[] = []; let size = 0;
  while (true) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) { await reader.cancel(); throw large(); } chunks.push(value); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { fail('response'); }
}
function correlation(v: unknown): string | undefined { try { return identifier(v, 'response'); } catch { return undefined; } }
const safeErrors: Record<string, string> = {
  draft_queue_unavailable: 'The draft change was saved, but generation could not be queued. Read the current draft before deciding how to continue.',
  draft_context_changed: 'Draft sources or revisions changed. Read the current draft and explicitly refresh sources.',
  draft_sources_missing: 'Record and confirm the required source information first.',
  draft_value_not_bound: 'Names and referenced work must match the recorded source.',
  draft_retry_not_failed: 'Only failed drafts can be retried.',
  draft_composition_mismatch: 'Choose drafts belonging to this composition.',
  draft_not_complete: 'Complete personalization before confirming sender facts.',
  composition_source_mismatch: 'Choose a recipient batch and template for this Activity and game.',
  composition_request_conflict: 'This request belongs to another composition.',
  template_version_request_conflict: 'This request belongs to another template version.',
  template_game_mismatch: 'Choose the original template only for its matching game.',
  canonical_game_mismatch: 'The original template belongs to its recorded Steam game.',
  template_fixed_content_invalid: 'Check the subject and five fixed template fragments.',
  idempotency_key_conflict: 'This key belongs to different input. Review the original operation.',
};
async function httpFailure(response: Response, mutation: boolean): Promise<PublicFailure> {
  let id = correlation(response.headers.get('x-correlation-id')), code: unknown;
  try { const envelope = object(await boundedJSON(response, 64 * 1024), 'response'), error = object(envelope.error, 'response'); code = error.code; id ??= correlation(error.correlation_id); } catch { /* Never expose raw service text. */ }
  if (mutation && response.status === 503 && code === 'draft_queue_unavailable') return new PublicFailure(code, safeErrors[code], false, id);
  if (mutation && response.status >= 500) return draftWriteUnknown();
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if ([404, 409, 422].includes(response.status) && typeof code === 'string' && Object.hasOwn(safeErrors, code)) return new PublicFailure(code, safeErrors[code], false, id);
  if (response.status === 404) return new PublicFailure('draft_not_found', 'This draft, composition, template, or route is unavailable.', false, id);
  if (response.status === 409) return new PublicFailure('draft_conflict', 'Read the current record and review the pending change.', false, id);
  if ([400, 422].includes(response.status)) return new PublicFailure('request_invalid', 'Check the template, values, and recorded revisions.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait before continuing.', !mutation, id);
  return new PublicFailure('service_error', 'The service could not complete this draft request.', !mutation && response.status >= 500, id);
}
export async function authenticatedDraftsRequest(fetcher: Fetcher, connection: Connection, input: DraftsRequest): Promise<unknown> {
  const request = validateDraftsRequest(input); let url: URL;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)); } catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  if (request.method === 'GET') for (const [k, v] of Object.entries(request.query ?? {})) url.searchParams.set(k, v);
  const mutation = request.method !== 'GET';
  try { const response = await fetcher(url.href, { method: request.method, ...(mutation ? { body: JSON.stringify(request.body) } : {}), headers: { ...STEAM_REFERENCES_OPT_IN, Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(), ...(mutation ? { 'Content-Type': 'application/json', ...(request.idempotencyKey ? { 'Idempotency-Key': request.idempotencyKey } : {}) } : {}) }, redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw await httpFailure(response, mutation); try { return await boundedJSON(response); } catch (error) { throw mutation ? draftWriteUnknown() : error; }
  } catch (error) { if (error instanceof PublicFailure) throw error; if (mutation) throw draftWriteUnknown(); throw new PublicFailure('network_error', 'Could not reach the service. Check the connection and service address.', true); }
}
