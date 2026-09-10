import { STEAM_REFERENCES_OPT_IN } from './steam-reference-opt-in';
import { randomUUID } from 'node:crypto';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';
import { fail, identifier, integer, keys, object, outreachBody, type OutreachBodyKind } from './outreach-validation';

export type OutreachRequest =
  | { method: 'GET'; path: string; query?: Record<string, string> }
  | { method: 'POST'; path: string; body: Record<string, unknown>; idempotencyKey: string };

const UUID_SOURCE = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const base = `/api/v2/activities/${UUID_SOURCE}`;
const selections = new RegExp(`^${base}/selections$`);
const selection = new RegExp(`^${base}/selections/${UUID_SOURCE}$`);
const bulk = new RegExp(`^${base}/selections/bulk$`);
const update = new RegExp(`^${base}/selections/${UUID_SOURCE}/update$`);
const cancel = new RegExp(`^${base}/selections/${UUID_SOURCE}/cancel$`);
const batches = new RegExp(`^${base}/recipient-batches$`);
const batch = new RegExp(`^${base}/recipient-batches/${UUID_SOURCE}$`);
const LIMIT = 8 * 1024 * 1024;

export function outreachOutcomeUnknown(): PublicFailure {
  return new PublicFailure('outreach_outcome_unknown', 'The outreach change may have completed. Read the current preparation or explicitly retry the same path, body, and key.', false);
}

function pagination(value: unknown, allowCancelled: boolean): Record<string, string> {
  const raw = object(value, 'input'); keys(raw, allowCancelled ? ['include_cancelled', 'offset', 'limit'] : ['offset', 'limit'], 'input');
  for (const [name, value] of Object.entries(raw)) {
    if (typeof value !== 'string') fail('input');
    if (name === 'include_cancelled') { if (!['true', 'false'].includes(value)) fail('input'); continue; }
    if (!/^(0|[1-9][0-9]*)$/.test(value)) fail('input');
    integer(Number(value), 'input', name === 'limit' ? 1 : 0, name === 'limit' ? 200 : Number.MAX_SAFE_INTEGER);
  }
  return raw as Record<string, string>;
}

export function validateOutreachRequest(value: OutreachRequest): OutreachRequest {
  const raw = object(value, 'input');
  if (typeof raw.path !== 'string' || !raw.path.startsWith('/api/v2/activities/')) fail('input');
  if (raw.method === 'GET') {
    keys(raw, ['method', 'path', 'query'], 'input');
    const paged = selections.test(raw.path) || batches.test(raw.path);
    if (!paged && !selection.test(raw.path) && !batch.test(raw.path)) fail('input');
    if (!paged && Object.hasOwn(raw, 'query')) fail('input');
    return { method: 'GET', path: raw.path, ...(Object.hasOwn(raw, 'query') ? { query: pagination(raw.query, selections.test(raw.path)) } : {}) };
  }
  if (raw.method !== 'POST') fail('input');
  keys(raw, ['method', 'path', 'body', 'idempotencyKey'], 'input');
  if (typeof raw.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(raw.idempotencyKey)) fail('input');
  let kind: OutreachBodyKind;
  if (selections.test(raw.path)) kind = 'selectionCreate';
  else if (bulk.test(raw.path)) kind = 'bulk';
  else if (update.test(raw.path)) kind = 'update';
  else if (cancel.test(raw.path)) kind = 'cancel';
  else if (batches.test(raw.path)) kind = 'freeze';
  else fail('input');
  const body = outreachBody(raw.body, kind);
  let encoded: string; try { encoded = JSON.stringify(body); } catch { fail('input'); }
  if (Buffer.byteLength(encoded) > LIMIT) fail('input');
  return { method: 'POST', path: raw.path, body, idempotencyKey: raw.idempotencyKey };
}

async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const tooLarge = () => new PublicFailure('response_too_large', 'The outreach response is too large. Try a smaller page.', true);
  if (Number(response.headers.get('content-length')) > limit) { await response.body?.cancel(); throw tooLarge(); }
  const reader = response.body?.getReader(); if (!reader) fail('response');
  const chunks: Uint8Array[] = []; let size = 0;
  while (true) {
    const { done, value } = await reader.read(); if (done) break;
    size += value.byteLength; if (size > limit) { await reader.cancel(); throw tooLarge(); } chunks.push(value);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { fail('response'); }
}
function correlation(value: unknown): string | undefined {
  try { return identifier(value, 'response'); } catch { return undefined; }
}
const safeErrors: Record<string, string> = {
  selection_not_found: 'This selection is no longer available in the Activity.',
  recipient_batch_not_found: 'This recipient batch is no longer available in the Activity.',
  candidate_activity_mismatch: 'Choose a candidate discovered in this Activity.',
  selection_identity_changed: 'The selected account identity changed. Review the current account before continuing.',
  selection_revision_conflict: 'This selection changed elsewhere. Reload it and review your edits.',
  preparation_context_changed: 'The preparation context changed. Reload it and review your edits.',
  selection_not_current: 'Choose a current active account before preparing outreach.',
  contact_not_eligible: 'Choose one current active valid email from this account.',
  evaluation_activity_mismatch: 'Choose an evaluation from this Activity.',
  evaluation_identity_mismatch: 'Choose an evaluation for this selected account identity.',
  work_not_current: 'Choose unique current works from this account identity.',
  public_name_missing: 'Add a public name in Library before confirming it.',
  selection_change_ambiguous: 'Do not add and cancel the same account in one request.',
  recipient_not_ready: 'Only active selected members can enter a preparation batch.',
  recipient_batch_request_conflict: 'This request ID belongs to another frozen recipient list.',
  idempotency_key_conflict: 'This request key belongs to different input. Check the original operation before retrying.',
};
async function httpFailure(response: Response, mutation: boolean): Promise<PublicFailure> {
  let id = correlation(response.headers.get('x-correlation-id'));
  if (mutation && response.status >= 500) { await response.body?.cancel(); return outreachOutcomeUnknown(); }
  let code: unknown;
  try {
    const envelope = object(await boundedJSON(response, 64 * 1024), 'response'); const error = object(envelope.error, 'response');
    code = error.code; id ??= correlation(error.correlation_id);
  } catch { /* Raw server errors and messages never cross the adapter. */ }
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if ([404, 409, 422].includes(response.status) && typeof code === 'string' && Object.hasOwn(safeErrors, code)) return new PublicFailure(code, safeErrors[code], false, id);
  if (response.status === 404) return new PublicFailure('outreach_not_found', 'This outreach record or API route is no longer available.', false, id);
  if (response.status === 409) return new PublicFailure('outreach_conflict', 'Reload the current preparation and review the pending change.', false, id);
  if ([400, 422].includes(response.status)) return new PublicFailure('request_invalid', 'Check the selected people, revisions, and preparation fields.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait before continuing.', !mutation, id);
  return new PublicFailure('service_error', 'The service could not complete this outreach request.', !mutation && response.status >= 500, id);
}

export async function authenticatedOutreachRequest(fetcher: Fetcher, connection: Connection, input: OutreachRequest): Promise<unknown> {
  const request = validateOutreachRequest(input); let url: URL;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)); }
  catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  if (request.method === 'GET') for (const [name, value] of Object.entries(request.query ?? {})) url.searchParams.set(name, value);
  const mutation = request.method === 'POST';
  try {
    const response = await fetcher(url.href, { method: request.method,
      ...(mutation ? { body: JSON.stringify(request.body) } : {}),
      headers: { ...STEAM_REFERENCES_OPT_IN, Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(),
        ...(mutation ? { 'Content-Type': 'application/json', 'Idempotency-Key': request.idempotencyKey } : {}) },
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw await httpFailure(response, mutation);
    try { return await boundedJSON(response); } catch (error) { throw mutation ? outreachOutcomeUnknown() : error; }
  } catch (error) {
    if (error instanceof PublicFailure) throw error;
    if (mutation) throw outreachOutcomeUnknown();
    throw new PublicFailure('network_error', 'Could not reach the service. Check the connection, service address, or system proxy.', true);
  }
}
