import type { AnalysisJob, AnalysisOutcome, ChangedJobs, ChangedMatchJob } from '../shared/analyze';
import { PublicFailure } from './transport';
import { stamp } from './drafts-validation';
export type Mode = 'input' | 'response';
export function fail(m: Mode): never { throw new PublicFailure(m === 'input' ? 'request_invalid' : 'invalid_response', m === 'input' ? 'Check the analysis target and request.' : 'The service returned unsupported analysis data.', false); }
export function object(v: unknown, m: Mode): Record<string, unknown> { if (!v || typeof v !== 'object' || Array.isArray(v) || ![Object.prototype, null].includes(Object.getPrototypeOf(v))) fail(m); return v as Record<string, unknown>; }
export function keys(r: Record<string, unknown>, allowed: readonly string[], m: Mode) { if (Object.keys(r).some(k => !allowed.includes(k))) fail(m); }
export function exact(v: unknown, names: readonly string[], m: Mode) { const r = object(v, m); keys(r, names, m); if (names.some(k => !Object.hasOwn(r, k))) fail(m); return r; }
export const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
export function identifier(v: unknown, m: Mode): string { if (typeof v !== 'string' || !new RegExp(`^${UUID}$`).test(v)) fail(m); return v; }
export function integer(v: unknown, m: Mode, min = 0, max = Number.MAX_SAFE_INTEGER): number { if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < min || v > max) fail(m); return v; }
export function text(v: unknown, m: Mode, max = 2048): string { if (typeof v !== 'string' || !v.length || v.length > max || /[\p{C}]/u.test(v)) fail(m); return v; }
function choice<T extends string>(v: unknown, options: readonly T[], m: Mode): T { if (!options.includes(v as T)) fail(m); return v as T; }
function bool(v: unknown): boolean { if (typeof v !== 'boolean') fail('response'); return v; }
export function target(type: unknown, raw: unknown, m: Mode): { id: string; url: string; resolved: boolean } {
  choice(type, ['game', 'creator'], m); const s = text(raw, m); if (/\s|%|\\/u.test(s)) fail(m); let u: URL; try { u = new URL(s); } catch { return fail(m); }
  // Explicit authority check also rejects :443, which URL normalizes away.
  if (!/^https:\/\/[a-z0-9.-]+\//i.test(s) || u.protocol !== 'https:' || u.username || u.password || u.port) fail(m);
  let match: RegExpExecArray | null;
  if (type === 'game' && u.hostname === 'store.steampowered.com' && (match = /^\/app\/([0-9]+)(?:\/[A-Za-z0-9_-]+)?\/?$/.exec(u.pathname))) { const id = integer(Number(match[1]), m, 1, 2147483647).toString(); return { id, url: `https://store.steampowered.com/app/${id}`, resolved: true }; }
  if (type === 'creator' && ['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(u.hostname) && (match = /^\/i\/user\/([1-9][0-9]{0,31})\/?$/.exec(u.pathname))) return { id: `x:${match[1]}`, url: `https://x.com/i/user/${match[1]}`, resolved: true };
  if (type === 'creator' && ['youtube.com', 'www.youtube.com'].includes(u.hostname)) {
    if ((match = /^\/channel\/(UC[A-Za-z0-9_-]{6,126})\/?$/.exec(u.pathname))) return { id: match[1], url: `https://www.youtube.com/channel/${match[1]}`, resolved: true };
    if ((match = /^\/(@[A-Za-z0-9._-]{3,30})\/?$/.exec(u.pathname))) return { id: match[1].toLowerCase(), url: `https://www.youtube.com/${match[1].toLowerCase()}`, resolved: false };
  } return fail(m);
}
const retryable = new Set('deepseek_model_contacts_invalid deepseek_model_evidence_invalid deepseek_model_output_invalid deepseek_unavailable public_page_unavailable s3_unavailable steam_unavailable youtube_quota_unavailable youtube_unavailable x_unavailable'.split(' '));
const permanent = new Set('analysis_clock_invalid analysis_cleanup_failed analysis_configuration_invalid analysis_job_identity_changed analysis_job_not_found analysis_job_result_invalid analysis_job_stage_invalid analysis_job_state_invalid analysis_job_target_invalid artifact_job_id_invalid artifact_name_invalid artifact_payload_invalid artifact_payload_too_large creator_interval_invalid deepseek_configuration_invalid deepseek_input_invalid deepseek_request_rejected deepseek_response_invalid deepseek_response_too_large game_interval_invalid public_page_address_rejected public_page_content_type_invalid public_page_redirect_invalid public_page_redirect_limit public_page_request_rejected public_page_response_invalid public_page_too_large public_page_url_invalid s3_configuration_invalid s3_request_rejected shared_settings_missing steam_app_id_invalid steam_game_not_found steam_request_rejected steam_response_invalid steam_response_too_large steam_source_identity_mismatch youtube_channel_id_invalid youtube_channel_not_found youtube_configuration_invalid youtube_request_rejected youtube_response_invalid youtube_response_too_large youtube_source_identity_mismatch youtube_target_invalid youtube_video_limit_invalid x_account_id_invalid x_account_not_found x_request_rejected x_response_invalid x_source_identity_mismatch'.split(' '));
function identity(r: Record<string, unknown>) { const t = target(r.target_type, r.canonical_url, 'response'); if (!t.resolved || t.id !== r.canonical_target_id || t.url !== r.canonical_url) fail('response'); }
export function decodeJob(v: unknown, expectedId?: string): AnalysisJob {
  const r = exact(v, ['outcome','id','target_type','canonical_target_id','canonical_url','mode','status','stage','completed_units','total_units','retryable','error','correlation_id','profile_id','created_at','updated_at','started_at','completed_at','waiting_reason','resume_available'], 'response');
  if (r.outcome !== 'job') fail('response'); const id = identifier(r.id, 'response'); if (expectedId && id.toLowerCase() !== expectedId.toLowerCase()) fail('response'); identity(r); choice(r.mode, ['create','reanalyze'], 'response');
  const status = choice(r.status, ['queued','running','succeeded','failed'], 'response'); if (r.stage !== null) choice(r.stage, ['fetching_data','analyzing','finalizing'], 'response');
  const done = integer(r.completed_units, 'response'), total = integer(r.total_units, 'response'); if (done > total) fail('response'); bool(r.retryable); bool(r.resume_available);
  const created = Date.parse(stamp(r.created_at)), updated = Date.parse(stamp(r.updated_at)), start = r.started_at === null ? null : Date.parse(stamp(r.started_at)), end = r.completed_at === null ? null : Date.parse(stamp(r.completed_at));
  if (updated < created || start !== null && start < created || end !== null && end < (start ?? created)) fail('response');
  if (r.profile_id !== null) identifier(r.profile_id, 'response'); if (r.correlation_id !== null && (typeof r.correlation_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(r.correlation_id))) fail('response');
  if (r.waiting_reason !== null) { choice(r.waiting_reason, ['collection_disabled','explicit_resume_required'], 'response'); if (r.target_type !== 'creator' || !['queued','running'].includes(status)) fail('response'); }
  if (r.resume_available !== (r.waiting_reason === 'explicit_resume_required')) fail('response');
  if (status === 'failed') {
    const error = exact(r.error, ['code','message'], 'response'), code = text(error.code, 'response', 128); let message: string; let retry: boolean;
    if (retryable.has(code)) { message = 'Analysis is temporarily unavailable. Please retry.'; retry = true; }
    else if (permanent.has(code)) { message = 'Analysis could not be completed for this target.'; retry = false; }
    else if (code === 'analysis_internal_error') { message = 'Analysis failed unexpectedly. Please retry.'; retry = true; }
    else if (code === 'analysis_queue_unavailable') { message = 'Analysis could not be queued. Please retry.'; retry = true; } else return fail('response');
    if (error.message !== message || r.retryable !== retry || end === null || r.profile_id !== null || (r.stage === null ? start !== null || done !== 0 || total !== 0 : start === null || total === 0 || done >= total)) fail('response');
  } else {
    if (r.error !== null || r.retryable) fail('response');
    if (status === 'queued' && (r.stage !== null || done || total || r.profile_id !== null || start !== null || end !== null)) fail('response');
    if (status === 'running' && (r.stage === null || total === 0 || done >= total || r.profile_id !== null || start === null || end !== null)) fail('response');
    if (status === 'succeeded' && (r.stage !== 'finalizing' || total === 0 || done !== total || r.profile_id === null || start === null || end === null)) fail('response');
  } return r as unknown as AnalysisJob;
}
export function decodeOutcome(v: unknown): AnalysisOutcome { const r = object(v, 'response'); if (r.outcome === 'job') return decodeJob(r); exact(r, ['outcome','existing_profile_id','target_type','canonical_target_id','canonical_url'], 'response'); if (r.outcome !== 'existing_profile') fail('response'); identifier(r.existing_profile_id, 'response'); identity(r); return r as unknown as AnalysisOutcome; }
export function decodeChanged(v: unknown, limit: number): ChangedJobs {
  const r = exact(v, ['items','cursor','has_more','affected_profile_ids'], 'response'); text(r.cursor, 'response'); bool(r.has_more); if (!Array.isArray(r.items) || r.items.length > limit || !Array.isArray(r.affected_profile_ids) || r.affected_profile_ids.length > limit) fail('response');
  const seen = new Set<string>(); const items = r.items.map(value => {
    const row = object(value, 'response'); identifier(row.resource_id, 'response'); const key = `${row.kind}:${row.resource_id}`; if (seen.has(key)) fail('response'); seen.add(key);
    if (row.kind === 'analysis') { const { kind, resource_id, ...rest } = row; return { ...decodeJob(rest, resource_id as string), kind, resource_id } as AnalysisJob & { kind: 'analysis'; resource_id: string }; }
    exact(row, ['kind','resource_id','status','stage','completed_units','total_units','result_count','retryable','error','correlation_id','game_id','supersedes_id','created_at','updated_at','started_at','completed_at'], 'response'); if (row.kind !== 'match') fail('response'); choice(row.status, ['queued','running','succeeded','failed','superseded'], 'response'); choice(row.stage, ['screening','pairwise','ranking'], 'response'); for (const k of ['completed_units','total_units','result_count']) integer(row[k], 'response'); if ((row.completed_units as number) > (row.total_units as number)) fail('response'); bool(row.retryable); identifier(row.game_id, 'response'); if (row.supersedes_id !== null) identifier(row.supersedes_id, 'response');
    for (const k of ['created_at','updated_at']) stamp(row[k]); for (const k of ['started_at','completed_at']) if (row[k] !== null) stamp(row[k]); if (row.correlation_id !== null) text(row.correlation_id, 'response', 128);
    // The shared change feed includes Match rows; only accepted fixed public messages cross the bridge.
    if (row.error !== null) { const e = exact(row.error, ['code','message'], 'response'); if (!/^[a-z][a-z0-9_]{0,127}$/.test(text(e.code, 'response', 128))) fail('response'); choice(e.message, ['Match is temporarily unavailable. Please retry.', 'Match could not be completed. Please retry.', 'Match failed unexpectedly. Please retry.', 'Match could not be queued. Please retry.'], 'response'); }
    return row as unknown as ChangedMatchJob;
  });
  const affected = r.affected_profile_ids.map(id => identifier(id, 'response')); if (new Set(affected).size !== affected.length) fail('response'); return { items, cursor: r.cursor as string, has_more: r.has_more as boolean, affected_profile_ids: affected };
}
