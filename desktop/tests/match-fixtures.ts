import type { ActivityDetail, ActivityView, CandidateView, EvaluationResult, EvaluationView, MatchPage, PlanCreate, PlanView, QueryView } from '../src/shared/match';
import { creatorFixture, CREATOR_ID, WORK_ID } from './creator-fixtures';
import { gameFixture } from './game-fixtures';
export const ACTIVITY_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const GAME_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
export const PLAN_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
export const QUERY_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
export const BATCH_ID = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
export const CANDIDATE_ID = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
export const EVALUATION_ID = '12345678-1234-4234-8234-123456789abc';
export const STEP_ID = '23456789-2345-4345-8345-23456789abcd';
export const MATCH_TIME = '2026-09-08T00:00:00Z';
export function matchPage<T>(item: T, limit = 50): MatchPage<T> { return { items: [item], total: 1, offset: 0, limit }; }
export function planCreateFixture(): PlanCreate {
  return { mode: 'discover', platforms: ['youtube', 'x'], keywords: ['gameplay'], filters: {
    countries: ['US'], languages: ['en'], follower_ranges: [{ minimum: 1000, maximum: null }],
    pending_country_labels: ['Unconfirmed label'], contact: 'any', include_unknown_country: false,
    include_unknown_language: true, include_unknown_followers: false,
  }, batch_target: 100, result_limit: 600, batch_request_budget: 20, batch_scan_budget: 1000,
  total_request_budget: 120, total_scan_budget: 6000 };
}
export function activityFixture(): ActivityView {
  return { id: ACTIVITY_ID, game_id: GAME_ID, name: 'Match fixture', created_at: MATCH_TIME,
    source_snapshot: { game: gameFixture('Game fixture', GAME_ID) as never, references: [] } };
}
export function activityDetailFixture(): ActivityDetail { return { ...activityFixture(), queries: [queryFixture()] }; }
export function planFixture(): PlanView {
  return { id: PLAN_ID, activity_id: ACTIVITY_ID, status: 'ready', conditions: planCreateFixture(),
    source_snapshot: activityFixture().source_snapshot, output: { summary: 'A game-led discovery plan.',
      rationale: 'Find relevant gameplay accounts.', queries: [{ platform: 'youtube', terms: ['Game fixture gameplay'] }, { platform: 'x', terms: ['Game fixture'] }],
      provider_queries: { youtube: '"Game fixture gameplay"', x: '"Game fixture" -is:retweet' } },
    error_code: null, retryable: false, attempt: 1, model: 'deepseek-v4-flash', query_id: QUERY_ID, created_at: MATCH_TIME };
}
export function queryFixture(): QueryView {
  const { mode: _mode, platforms: _platforms, keywords: _keywords, ...options } = planCreateFixture();
  return { id: QUERY_ID, activity_id: ACTIVITY_ID, conditions: { ...options, providers: [{ platform: 'youtube', query: '"Game fixture gameplay"', search_mode: 'video', page_size: 25, max_requests: 2, language_hint: null, region_hint: null, cursor: null }] },
    source_snapshot: activityFixture().source_snapshot, status: 'outcome_unknown', stop_requested: false,
    requires_acknowledgement: true, result_count: 1, requests_reserved: 2, scanned_reserved: 50,
    sources: { youtube: { status: 'outcome_unknown', coverage: 'partial', issues: [] } },
    batches: [{ id: BATCH_ID, query_id: QUERY_ID, ordinal: 1, status: 'paused', target_count: 100,
      initial_result_count: 0, requests_reserved: 2, scanned_reserved: 50, reason: 'outcome_unknown', created_at: MATCH_TIME }],
    usage: { requests_used: 1, provider_items_received: 25, unknown_requests_reserved: 1 }, created_at: MATCH_TIME };
}
export function candidateFixture(): CandidateView {
  return { id: CANDIDATE_ID, creator_id: CREATOR_ID, platform: 'youtube', account_id: 'UCfixture',
    account: { platform: 'youtube', account_id: 'UCfixture', profile_url: 'https://www.youtube.com/channel/UCfixture',
      display_name: 'Acquired name', handle: null, description: null, follower_count: null, country: null,
      location_text: null, avatar_url: null, collected_at: MATCH_TIME, metadata_complete: true }, creator: creatorFixture(),
    filter_notes: { evidence_status: 'unverified' }, identity_revision: 1, identity_changed: false,
    added_at: MATCH_TIME, selected: false };
}
export function evaluationFixture(): EvaluationView {
  return { id: EVALUATION_ID, query_id: QUERY_ID, status: 'partial', stage: 'ranking', method_version: 'discovery-evaluation-v1-chunk20-absolute',
    models: { screening: 'deepseek-v4-flash', deep_match: 'deepseek-v4-pro', ranking: 'deepseek-v4-pro' },
    conditions: queryFixture().conditions as never, source_snapshot: activityFixture().source_snapshot,
    candidate_count: 1, matched_count: 1, retryable: true,
    usage: { model_operations_started: 3, succeeded_steps: 2, failed_steps: 1, pending_steps: 0, running_steps: 0 },
    steps: [{ id: STEP_ID, kind: 'ranking', status: 'failed', error_code: 'evaluation_outcome_unknown', attempt: 1 }], created_at: MATCH_TIME };
}
export function evaluationResultFixture(): EvaluationResult {
  return { candidate_id: CANDIDATE_ID, creator_id: CREATOR_ID, platform: 'youtube', account_id: 'UCfixture',
    name: 'Acquired name', status: 'ranking_failed', fit_group: 'unranked', match_brief: { candidate_id: CANDIDATE_ID,
      summary: 'Potential gameplay fit.', content_fit: 'Recorded gameplay metadata.', audience_fit: 'Audience is not verified.',
      limitations: ['No viewing confirmation.'], cited_work_ids: [WORK_ID], confidence: 'limited' },
    evidence_status: 'metadata_only', evidence: [{ work_id: WORK_ID, source_url: 'https://example.com/watch', content_title: 'Game fixture gameplay', timestamp_seconds: null, relation: 'current_game', status: 'metadata_only' }],
    needs_enrichment: true, stale: false, identity_changed: false, selected: false, sender_watched: false };
}
