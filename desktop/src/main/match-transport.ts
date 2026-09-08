import { randomUUID } from 'node:crypto';
import { CANDIDATE_EVIDENCE_FILTERS, CANDIDATE_SORTS } from '../shared/match';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';
import { body, fail, integer, keys, object, text, UUID_PATTERN, UUID_SOURCE, type BodyKind } from './match-validation';
export type MatchRequest = { method: 'GET'; path: string; query?: Record<string, string> } | { method: 'POST'; path: string; body?: Record<string, unknown>; idempotencyKey: string };
const activities = '/api/v2/activities', discovery = '/api/v2/discovery';
const route = (prefix: string, suffix = '') => new RegExp(`^${prefix}/${UUID_SOURCE}${suffix}$`);
const activity = route(activities), plans = route(activities, '/discovery-plans');
const plan = route(`${discovery}/plans`), retryPlan = route(`${discovery}/plans`, '/retry');
const query = route(`${discovery}/queries`), candidates = route(`${discovery}/queries`, '/results');
const stop = route(`${discovery}/queries`, '/stop'), resume = route(`${discovery}/queries`, '/continue');
const evaluations = route(`${discovery}/queries`, '/evaluations'), evaluation = route(`${discovery}/evaluations`);
const evaluationResults = route(`${discovery}/evaluations`, '/results'), retryEvaluation = route(`${discovery}/evaluations`, '/retry');
const LIMIT = 8 * 1024 * 1024;
export function matchOutcomeUnknown(): PublicFailure {
  return new PublicFailure('save_outcome_unknown', 'The Match request may have completed. Check its records or explicitly retry the same request and key; do not start a duplicate operation.', false);
}
function pagination(value: unknown, max: number): Record<string, string> {
  const raw = object(value, 'input'); keys(raw, max ? ['offset', 'limit'] : [], 'input');
  return Object.fromEntries(Object.entries(raw).map(([key, value]) => {
    const result = text(value, 'input', 20);
    if (!/^(0|[1-9][0-9]*)$/.test(result)) fail('input');
    integer(Number(result), 'input', key === 'limit' ? 1 : 0, key === 'limit' ? max : Number.MAX_SAFE_INTEGER);
    return [key, result];
  }));
}
export function exactCandidateQueryOptions(value: unknown): Record<string, string> {
  const raw = object(value, 'input');
  keys(raw, ['offset', 'limit', 'evidence', 'sort'], 'input');
  const result = pagination(Object.fromEntries(Object.entries(raw).filter(([key]) => key === 'offset' || key === 'limit')), 100);
  if (Object.hasOwn(raw, 'evidence')) {
    const evidence = text(raw.evidence, 'input', 32, 1);
    if (!(CANDIDATE_EVIDENCE_FILTERS as readonly string[]).includes(evidence)) fail('input');
    result.evidence = evidence;
  }
  if (Object.hasOwn(raw, 'sort')) {
    const sort = text(raw.sort, 'input', 32, 1);
    if (!(CANDIDATE_SORTS as readonly string[]).includes(sort)) fail('input');
    result.sort = sort;
  }
  return result;
}
export function validateMatchRequest(input: MatchRequest): MatchRequest {
  const raw = object(input, 'input'); const { method, path } = raw; if (typeof path !== 'string') fail('input');
  if (method === 'GET') {
    keys(raw, ['method', 'path', 'query'], 'input');
    const max = path === activities || candidates.test(path) ? 100 : plans.test(path) || evaluations.test(path) || evaluationResults.test(path) ? 200 : 0;
    if (!max && !activity.test(path) && !plan.test(path) && !query.test(path) && !evaluation.test(path)) fail('input');
    return { method, path, ...(Object.hasOwn(raw, 'query') ? { query: candidates.test(path) ? exactCandidateQueryOptions(raw.query) : pagination(raw.query, max) } : {}) };
  }
  if (method !== 'POST') fail('input');
  const bodyless = retryPlan.test(path) || stop.test(path);
  keys(raw, bodyless ? ['method', 'path', 'idempotencyKey'] : ['method', 'path', 'body', 'idempotencyKey'], 'input');
  if (typeof raw.idempotencyKey !== 'string' || !/^[A-Za-z0-9._:-]{8,128}$/.test(raw.idempotencyKey)) fail('input');
  if (bodyless) return { method, path, idempotencyKey: raw.idempotencyKey };
  let kind: BodyKind;
  if (path === activities) kind = 'activityCreate';
  else if (plans.test(path)) kind = 'planCreate';
  else if (resume.test(path)) kind = 'continueDiscovery';
  else if (evaluations.test(path)) kind = 'evaluationCreate';
  else if (retryEvaluation.test(path)) kind = 'evaluationRetry';
  else fail('input');
  const result = body(raw.body, kind);
  if (Buffer.byteLength(JSON.stringify(result)) > LIMIT) fail('input');
  return { method, path, body: result, idempotencyKey: raw.idempotencyKey };
}
async function boundedJSON(response: Response, limit = LIMIT): Promise<unknown> {
  const tooLarge = () => new PublicFailure('response_too_large', 'The Match response is too large. Try a smaller page.', true);
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
  discovery_not_found: 'This Activity, plan, or discovery query is no longer available.',
  evaluation_not_found: 'This evaluation is no longer available.',
  game_not_found: 'The chosen game is no longer available. Choose a current game.',
  activity_reference_invalid: 'Choose reference works belonging to this game.',
  game_context_required: 'Add a game name, description, or tags before planning.',
  discovery_not_runnable: 'Check the current discovery state. It may be active, exhausted, or awaiting acknowledgement.',
  planning_not_retryable: 'Wait for the active plan or create a new plan with corrected input.',
  evaluation_running: 'Wait for the active evaluation steps to finish.',
  evaluation_not_retryable: 'Create a new evaluation with current source identities.',
  evaluation_candidates_invalid: 'Choose existing candidates from this query, up to 600.',
  evaluation_retry_invalid: 'Choose failed or expired steps from this evaluation.',
  idempotency_key_conflict: 'This request key belongs to different input. Check the original operation before starting another.',
};
function correlation(value: unknown): string | undefined { return typeof value === 'string' && UUID_PATTERN.test(value) ? value : undefined; }
async function httpFailure(response: Response, mutation: boolean): Promise<PublicFailure> {
  let id = correlation(response.headers.get('x-correlation-id'));
  if (mutation && response.status >= 500) { await response.body?.cancel(); return matchOutcomeUnknown(); }
  let code: unknown;
  try { const envelope = object(await boundedJSON(response, 64 * 1024), 'response'); const error = object(envelope.error, 'response'); code = error.code; id ??= correlation(error.correlation_id); }
  catch { /* Never return server messages, credentials, or raw exception details. */ }
  if (response.status === 401) return new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false, id);
  if (response.status === 403) return new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false, id);
  if ([404, 409, 422].includes(response.status) && typeof code === 'string' && Object.hasOwn(safeErrors, code)) return new PublicFailure(code, safeErrors[code], false, id);
  if (response.status === 404) return new PublicFailure('match_not_found', 'This Match record or API route is not available. Check the service version.', false, id);
  if (response.status === 409) return new PublicFailure('save_conflict', 'Check the current Match state before retrying this operation.', false, id);
  if ([400, 422].includes(response.status)) return new PublicFailure('request_invalid', 'Check the Match inputs, chosen records, and limits.', false, id);
  if (response.status === 429) return new PublicFailure('rate_limited', 'The service is busy. Wait before continuing.', !mutation, id);
  return new PublicFailure('service_error', 'The service could not complete this Match request.', !mutation && response.status >= 500, id);
}
export async function authenticatedMatchRequest(fetcher: Fetcher, connection: Connection, input: MatchRequest): Promise<unknown> {
  const request = validateMatchRequest(input); let url: URL;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)); }
  catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  if (request.method === 'GET') for (const [key, value] of Object.entries(request.query ?? {})) url.searchParams.set(key, value);
  const mutation = request.method === 'POST';
  try {
    const response = await fetcher(url.href, { method: request.method,
      ...('body' in request ? { body: JSON.stringify(request.body) } : {}),
      headers: { Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(),
        ...('body' in request ? { 'Content-Type': 'application/json' } : {}), ...(mutation ? { 'Idempotency-Key': request.idempotencyKey } : {}) },
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw await httpFailure(response, mutation);
    try { return await boundedJSON(response); } catch (error) { throw mutation ? matchOutcomeUnknown() : error; }
  } catch (error) {
    if (error instanceof PublicFailure) throw error;
    if (mutation) throw matchOutcomeUnknown();
    throw new PublicFailure('network_error', 'Could not reach the service. Check the connection, service address, or system proxy.', true);
  }
}
