import type * as DTO from '../shared/match';
import { decodeCreator, timestamp as creatorTimestamp, UUID_PATTERN, UUID_SOURCE } from './creator-validation';
import { PublicFailure } from './transport';
export { UUID_PATTERN, UUID_SOURCE };
export type Mode = 'input' | 'response';
type Rule = (value: unknown, mode: Mode) => unknown;
export function fail(mode: Mode): never {
  throw new PublicFailure(mode === 'input' ? 'request_invalid' : 'invalid_response', mode === 'input'
    ? 'Check the Match inputs, chosen records, and limits.'
    : 'The service returned an unsupported Match response. Reload or check the service version.', false);
}
export function object(value: unknown, mode: Mode): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail(mode);
  return value as Record<string, unknown>;
}
export function keys(value: Record<string, unknown>, allowed: readonly string[], mode: Mode) {
  if (Object.keys(value).some(key => !allowed.includes(key))) fail(mode);
}
export function integer(value: unknown, mode: Mode, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) fail(mode); return value;
}
export function text(value: unknown, mode: Mode, max = 100_000, min = 0): string {
  if (typeof value !== 'string' || [...value].length < min || [...value].length > max) fail(mode); return value;
}
export function identifier(value: unknown, mode: Mode): string {
  if (typeof value !== 'string' || !UUID_PATTERN.test(value)) fail(mode); return value;
}
const boolean: Rule = (value, mode) => { if (typeof value !== 'boolean') fail(mode); return value; };
const nullable = (rule: Rule): Rule => (value, mode) => value === null ? null : rule(value, mode);
const string = (max = 100_000, min = 0): Rule => (value, mode) => text(value, mode, max, min);
const count = (max = Number.MAX_SAFE_INTEGER, min = 0): Rule => (value, mode) => integer(value, mode, min, max);
const enumeration = (...values: readonly unknown[]): Rule => (value, mode) => { if (!values.includes(value)) fail(mode); return value; };
const time: Rule = (value, mode) => { if (value === null) fail(mode); try { return creatorTimestamp(value, mode); } catch { fail(mode); } };
const list = (rule: Rule, max = 10_000, min = 0, unique?: (value: any) => unknown): Rule => (value, mode) => {
  if (!Array.isArray(value) || value.length > max || value.length < min) fail(mode);
  const result = value.map(item => rule(item, mode));
  if (unique && new Set(result.map(unique)).size !== result.length) fail(mode); return result;
};
const record = (required: Record<string, Rule>, optional: Record<string, Rule> = {}): Rule => (value, mode) => {
  const raw = object(value, mode); keys(raw, [...Object.keys(required), ...Object.keys(optional)], mode);
  const result: Record<string, unknown> = {};
  for (const [key, rule] of Object.entries(required)) result[key] = rule(raw[key], mode);
  for (const [key, rule] of Object.entries(optional)) if (Object.hasOwn(raw, key)) result[key] = rule(raw[key], mode);
  return Object.fromEntries(Object.keys(raw).map(key => [key, result[key]]));
};
const narrative = (max: number): Rule => (value, mode) => {
  const result = text(value, mode, max, 1);
  if (result !== result.trim() || /[\x00-\x1f]/.test(result)) fail(mode); return result;
};
const keyword: Rule = (value, mode) => {
  const result = text(value, mode, 100, 1); if (!result.trim() || /[\x00-\x1f]/.test(result)) fail(mode); return result;
};
const pattern = (regex: RegExp, max: number): Rule => (value, mode) => { const result = text(value, mode, max); if (!regex.test(result)) fail(mode); return result; };
const json = (value: unknown, mode: Mode, depth = 0): unknown => {
  if (depth > 20) fail(mode);
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'string') return text(value, mode, 1_000_000);
  if (typeof value === 'number') { if (!Number.isFinite(value)) fail(mode); return value; }
  if (Array.isArray(value)) { if (value.length > 20_000) fail(mode); return value.map(item => json(item, mode, depth + 1)); }
  const raw = object(value, mode); if (Object.keys(raw).length > 10_000) fail(mode);
  return Object.fromEntries(Object.entries(raw).map(([key, item]) => {
    if (['__proto__', 'prototype', 'constructor'].includes(key)) fail(mode);
    text(key, mode, 1000); return [key, json(item, mode, depth + 1)];
  }));
};
const jsonObject: Rule = (value, mode) => { object(value, mode); return json(value, mode); };
const sourceStates: Rule = (value, mode) => {
  const sources=object(jsonObject(value,mode),mode);
  for(const source of Object.values(sources)){
    const state=object(source,mode);
    if(Object.hasOwn(state,'blocked_reason')&&state.blocked_reason!=='collection_disabled')fail(mode);
  }
  return sources;
};
const dictionary = (rule: Rule): Rule => (value, mode) => {
  const raw = object(value, mode); if (Object.keys(raw).length > 100) fail(mode);
  return Object.fromEntries(Object.entries(raw).map(([key, item]) => { text(key, mode, 100); if (['__proto__', 'constructor', 'prototype'].includes(key)) fail(mode); return [key, rule(item, mode)]; }));
};
const ids = (max: number, min = 0, unique = false) => list(identifier, max, min, unique ? id => id.toLowerCase() : undefined);
const platform = enumeration('youtube', 'x', 'twitch', 'instagram');
const planningPlatform = enumeration('youtube', 'x');
const followerRange: Rule = (value, mode) => {
  const result = record({}, { minimum: nullable(count()), maximum: nullable(count()) })(value, mode) as DTO.FollowerRange;
  if (result.minimum == null && result.maximum == null) fail(mode);
  if (result.maximum != null && (result.minimum ?? 0) > result.maximum) fail(mode); return result;
};
const filters = record({}, {
  countries: list(pattern(/^[A-Z]{2}$/, 2), 30), languages: list(string(64, 1), 30),
  pending_country_labels: list(string(100, 1), 30), follower_ranges: list(followerRange, 7),
  contact: enumeration('any', 'available', 'missing'), include_unknown_country: boolean,
  include_unknown_language: boolean, include_unknown_followers: boolean,
});
const options = { filters, batch_target: count(100, 1), result_limit: count(600, 1), batch_request_budget: count(40, 1),
  batch_scan_budget: count(2000, 1), total_request_budget: count(240, 1), total_scan_budget: count(12000, 1) };
const planCreate = record({ mode: enumeration('preview', 'discover'), platforms: list(planningPlatform, 2, 1, value => value) }, { keywords: list(keyword, 20), ...options });
const activityCreate = record({ game_id: identifier, name: string(255, 1) }, { reference_work_ids: ids(100) });
const continueDiscovery = record({}, { acknowledge_unknown: boolean });
const evaluationCreate = record({}, { candidate_ids: nullable(ids(600, 1, true)) });
const evaluationRetry = record({}, { step_ids: nullable(ids(1000, 1)) });
export type BodyKind = 'activityCreate' | 'planCreate' | 'continueDiscovery' | 'evaluationCreate' | 'evaluationRetry';
const bodies: Record<BodyKind, Rule> = { activityCreate, planCreate, continueDiscovery, evaluationCreate, evaluationRetry };
export function body(value: unknown, kind: BodyKind): Record<string, unknown> { return bodies[kind](value, 'input') as Record<string, unknown>; }

const providerShape = record({ platform, query: string(512, 1) }, {
  search_mode: enumeration('video', 'channel'), region_hint: nullable(pattern(/^[A-Z]{2}$/, 2)),
  language_hint: nullable(pattern(/^[a-zA-Z-]{2,12}$/, 12)), page_size: count(100, 1), max_requests: count(2), cursor: enumeration(null),
});
const provider: Rule = (value, mode) => {
  const result = providerShape(value, mode) as DTO.DiscoveryRequest;
  const pageSize = result.page_size ?? 25;
  if (!result.query.trim() || (result.platform === 'youtube' && pageSize > 50) || (result.platform === 'x' && pageSize < 10)) fail(mode);
  if (result.platform !== 'youtube' && (result.region_hint || result.language_hint || (result.search_mode ?? 'video') !== 'video')) fail(mode);
  return result;
};
const queryCreate = record({ providers: list(provider, 4, 1, value => value.platform) }, options);
const activityFields = { id: identifier, game_id: identifier, name: string(255, 1), source_snapshot: jsonObject, created_at: time };
const usage = record({ requests_used: count(), provider_items_received: count(), unknown_requests_reserved: count() });
const batch = record({ id: identifier, query_id: identifier, ordinal: count(), status: string(100, 1), target_count: count(100),
  initial_result_count: count(600), requests_reserved: count(), scanned_reserved: count(), reason: nullable(string(255)), created_at: time });
const query = record({ id: identifier, activity_id: identifier, conditions: queryCreate, source_snapshot: jsonObject,
  status: string(100, 1), stop_requested: boolean, requires_acknowledgement: boolean, result_count: count(600),
  requests_reserved: count(), scanned_reserved: count(), sources: sourceStates,
  batches: list(batch, 10_000, 0, value => value.id.toLowerCase()), usage, created_at: time });
const planOutput = record({ summary: narrative(1500), rationale: narrative(1500),
  queries: list(record({ platform: planningPlatform, terms: list(narrative(100), 3, 1) }), 2, 1),
  provider_queries: record({}, { youtube: string(512, 1), x: string(512, 1) }) });
const plan = record({ id: identifier, activity_id: identifier, status: enumeration('queued', 'running', 'ready', 'failed'),
  conditions: planCreate, source_snapshot: jsonObject, output: nullable(planOutput), error_code: nullable(string(255)),
  retryable: boolean, attempt: count(), model: string(255), query_id: nullable(identifier), created_at: time });
const candidateEvidenceGroup = enumeration('current_game', 'reference_game', 'related_content');
const candidate = record({ id: identifier, creator_id: identifier, platform: string(100, 1), account_id: string(512, 1),
  account: jsonObject, creator: nullable((value, mode) => { try { return decodeCreator(value); } catch { fail(mode); } }),
  filter_notes: jsonObject, identity_revision: count(), identity_changed: boolean, added_at: time }, {
  selected: enumeration(false), evidence_groups: list(candidateEvidenceGroup, 3),
  relevance_status: enumeration('available', 'stale', 'not_evaluated'),
});
const evaluationUsage = record({ model_operations_started: count(), succeeded_steps: count(), failed_steps: count(), pending_steps: count(), running_steps: count() });
const evaluationStep = record({ id: identifier, kind: string(100, 1), status: string(100, 1), error_code: nullable(string(255)), attempt: count() });
const evaluation = record({ id: identifier, query_id: identifier, status: enumeration('queued', 'running', 'completed', 'partial', 'failed', 'no_matches'),
  stage: string(100, 1), method_version: string(255, 1), models: dictionary(string(255)), conditions: jsonObject,
  source_snapshot: jsonObject, candidate_count: count(600), matched_count: count(600), retryable: boolean,
  usage: evaluationUsage, steps: list(evaluationStep, 10_000, 0, value => value.id.toLowerCase()), created_at: time });
const brief = record({ candidate_id: identifier, summary: narrative(1200), content_fit: narrative(1200), audience_fit: narrative(1200),
  limitations: list(narrative(500), 6, 1), cited_work_ids: ids(20), confidence: enumeration('limited', 'supported') });
const sourceURL: Rule = (value, mode) => {
  const result = text(value, mode, 8192, 1);
  try { const url = new URL(result); if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) fail(mode); } catch { fail(mode); }
  return result;
};
const seconds: Rule = (value, mode) => { if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) fail(mode); return value; };
const evidence = record({ work_id: identifier, source_url: nullable(sourceURL), content_title: nullable(string()), timestamp_seconds: nullable(seconds),
  relation: enumeration('current_game', 'reference_game', 'related_content'), status: enumeration('metadata_only', 'recorded_evidence') });
const evaluationResult = record({ candidate_id: identifier, creator_id: identifier, platform: string(100, 1), account_id: string(512, 1),
  name: nullable(string()), status: string(100, 1), fit_group: enumeration('strong_fit', 'potential_fit', 'limited_fit', 'unranked'),
  match_brief: nullable(brief), evidence_status: enumeration('unknown', 'metadata_only', 'recorded_evidence'), evidence: list(evidence, 20),
  needs_enrichment: boolean, stale: boolean, identity_changed: boolean }, { selected: enumeration(false), sender_watched: enumeration(false) });
export function sameID(actual: string, expected?: string) { if (expected !== undefined && actual.toLowerCase() !== expected.toLowerCase()) fail('response'); }
export function decodeActivity(value: unknown, expectedId?: string): DTO.ActivityView {
  const result = record(activityFields)(value, 'response') as DTO.ActivityView; sameID(result.id, expectedId); return result;
}
export function decodeQuery(value: unknown, expectedId?: string, activityId?: string): DTO.QueryView {
  const result = query(value, 'response') as DTO.QueryView; sameID(result.id, expectedId); sameID(result.activity_id, activityId);
  result.batches.forEach(item => sameID(item.query_id, result.id)); return result;
}
export function decodeActivityDetail(value: unknown, expectedId: string): DTO.ActivityDetail {
  const result = record({ ...activityFields, queries: list((item) => decodeQuery(item, undefined, expectedId), 10_000, 0, item => item.id.toLowerCase()) })(value, 'response') as DTO.ActivityDetail;
  sameID(result.id, expectedId); return result;
}
export function decodePlan(value: unknown, expectedId?: string, activityId?: string): DTO.PlanView {
  const result = plan(value, 'response') as DTO.PlanView; sameID(result.id, expectedId); sameID(result.activity_id, activityId); return result;
}
export function decodeCandidate(value: unknown): DTO.CandidateView {
  const result = candidate(value, 'response') as DTO.CandidateView;
  if (result.creator) sameID(result.creator.id, result.creator_id);
  if (result.identity_changed !== (!result.creator || result.creator.source_identity.revision !== result.identity_revision)) fail('response');
  return { ...result, selected: false };
}
export function decodeEvaluation(value: unknown, expectedId?: string, queryId?: string): DTO.EvaluationView {
  const result = evaluation(value, 'response') as DTO.EvaluationView; sameID(result.id, expectedId); sameID(result.query_id, queryId);
  if (result.matched_count > result.candidate_count) fail('response'); return result;
}
export function decodeEvaluationResult(value: unknown): DTO.EvaluationResult {
  const result = evaluationResult(value, 'response') as DTO.EvaluationResult;
  if (result.match_brief) sameID(result.match_brief.candidate_id, result.candidate_id);
  if (result.identity_changed && !result.stale) fail('response');
  if (result.evidence_status === 'recorded_evidence' && !result.evidence.some(item => item.status === 'recorded_evidence')) fail('response');
  const evidenceIds = new Set(result.evidence.map(item => item.work_id.toLowerCase()));
  if (result.match_brief?.cited_work_ids.some(id => !evidenceIds.has(id.toLowerCase()))) fail('response');
  return { ...result, selected: false, sender_watched: false };
}
export function decodePage<T>(value: unknown, decode: (item: unknown) => T, max: number, id: (item: T) => string): DTO.MatchPage<T> {
  const raw = object(value, 'response'); keys(raw, ['items', 'total', 'limit', 'offset'], 'response');
  const total = integer(raw.total, 'response'), offset = integer(raw.offset, 'response'), limit = integer(raw.limit, 'response', 1, max);
  const items = list(item => decode(item), limit, 0, item => id(item).toLowerCase())(raw.items, 'response') as T[];
  if (items.length > total) fail('response'); return { items, total, limit, offset };
}
export function decodePlanAccepted(value: unknown, expectedId?: string): DTO.PlanAccepted {
  const result = record({ plan_id: identifier, status: string(100, 1) })(value, 'response') as DTO.PlanAccepted; sameID(result.plan_id, expectedId); return result;
}
export function decodeDiscoveryAccepted(value: unknown, expectedId: string): DTO.DiscoveryAccepted {
  const result = record({ query_id: identifier, batch_id: identifier, status: string(100, 1) })(value, 'response') as DTO.DiscoveryAccepted; sameID(result.query_id, expectedId); return result;
}
export function decodeStopped(value: unknown, expectedId: string): DTO.DiscoveryStopped {
  const result = record({ query_id: identifier, status: string(100, 1), stop_requested: boolean })(value, 'response') as DTO.DiscoveryStopped; sameID(result.query_id, expectedId); return result;
}
export function decodeEvaluationAccepted(value: unknown, expectedId?: string): DTO.EvaluationAccepted {
  const result = record({ evaluation_id: identifier, status: string(100, 1) })(value, 'response') as DTO.EvaluationAccepted; sameID(result.evaluation_id, expectedId); return result;
}
