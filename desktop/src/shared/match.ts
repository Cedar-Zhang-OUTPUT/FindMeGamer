import type { Result } from './bridge';
import type { CreatorDetail, CreatorPlatform } from './creators';
import type { JsonObject } from './library';
import type { CreatorSearchAPI } from './creatorSearch';

/** Accepted v2 Activity / Discovery / Evaluation DTOs; never the v1 score schema. */
export type ApiResult<T> = Result<T>;
export interface Pagination { offset?: number; limit?: number }
export interface MatchPage<T> { items: T[]; total: number; offset: number; limit: number }
export interface ActivityCreate { game_id: string; name: string; reference_work_ids?: string[]; campaign_brief?: string|null }
export interface ActivityView { id: string; game_id: string; name: string; source_snapshot: JsonObject; created_at: string; campaign_brief?: string|null; revision?: number; initial_selection_initialized?:boolean }
export interface ActivityDetail extends ActivityView { queries: QueryView[] }
export type ActivityPage = MatchPage<ActivityView>;
export interface FollowerRange { minimum?: number | null; maximum?: number | null }
export interface CandidateFilters {
  countries?: string[]; pending_country_labels?: string[]; languages?: string[];
  follower_ranges?: FollowerRange[]; contact?: 'any' | 'available' | 'missing';
  include_unknown_country?: boolean; include_unknown_language?: boolean; include_unknown_followers?: boolean;
}
export interface DiscoveryBudgets {
  batch_target?: number; result_limit?: number; batch_request_budget?: number;
  batch_scan_budget?: number; total_request_budget?: number; total_scan_budget?: number;
}
export type PlanningPlatform = 'youtube' | 'x' | 'twitch' | 'instagram';
export interface PlanCreate extends DiscoveryBudgets {
  mode: 'preview' | 'discover'; platforms: PlanningPlatform[]; keywords?: string[]; filters?: CandidateFilters;
}
export interface SearchPlanQuery { platform: PlanningPlatform; terms: string[] }
export interface PublishedPlanOutput {
  summary: string; rationale: string; queries: SearchPlanQuery[];
  provider_queries: Partial<Record<PlanningPlatform, string>>;
}
export interface PlanView {
  id: string; activity_id: string; status: 'queued' | 'running' | 'ready' | 'failed';
  conditions: PlanCreate; source_snapshot: JsonObject; output: PublishedPlanOutput | null;
  error_code: string | null; retryable: boolean; attempt: number; model: string;
  query_id: string | null; created_at: string;
}
export type PlanPage = MatchPage<PlanView>;
export interface PlanAccepted { plan_id: string; status: string }
/** Read-only frozen provider conditions. No API exposes native-query creation. */
export interface DiscoveryCursor { token: string; query_fingerprint: string }
export interface DiscoveryRequest {
  platform: CreatorPlatform; query: string; search_mode?: 'video' | 'channel';
  region_hint?: string | null; language_hint?: string | null; page_size?: number;
  max_requests?: number; cursor?: DiscoveryCursor | null;
}
export interface QueryCreate extends DiscoveryBudgets { providers: DiscoveryRequest[]; filters?: CandidateFilters }
export interface QueryUsage { requests_used: number; provider_items_received: number; unknown_requests_reserved: number }
export interface BatchView {
  id: string; query_id: string; ordinal: number; status: string; target_count: number;
  initial_result_count: number; requests_reserved: number; scanned_reserved: number;
  reason: string | null; created_at: string;
}
export interface QueryView {
  id: string; activity_id: string; conditions: QueryCreate; source_snapshot: JsonObject; status: string;
  stop_requested: boolean; requires_acknowledgement: boolean; result_count: number;
  requests_reserved: number; scanned_reserved: number; sources: JsonObject;
  batches: BatchView[]; usage: QueryUsage; created_at: string;
}
export const CANDIDATE_EVIDENCE_FILTERS = ['all', 'current_game', 'reference_game', 'related_content', 'none'] as const;
export type CandidateEvidenceFilter = typeof CANDIDATE_EVIDENCE_FILTERS[number];
export const CANDIDATE_SORTS = ['added', 'relevance', 'followers', 'recent_publish', 'recent_added'] as const;
export type CandidateSort = typeof CANDIDATE_SORTS[number];
export interface CandidateQueryOptions { evidence?: CandidateEvidenceFilter; sort?: CandidateSort }
export type CandidateListInput = Pagination & CandidateQueryOptions & { queryId: string };
export interface CandidateView {
  id: string; creator_id: string; platform: string; account_id: string; account: JsonObject;
  creator: CreatorDetail | null; filter_notes: JsonObject; identity_revision: number;
  identity_changed: boolean; added_at: string; selected: false;
  evidence_groups?: ('current_game' | 'reference_game' | 'related_content')[];
  relevance_status?: 'available' | 'stale' | 'not_evaluated';
}
export type CandidatePage = MatchPage<CandidateView>;
export interface ContinueDiscovery { acknowledge_unknown?: boolean }
export interface DiscoveryAccepted { query_id: string; batch_id: string; status: string }
export interface DiscoveryStopped { query_id: string; status: string; stop_requested: boolean }
export interface EvaluationCreate { candidate_ids?: string[] | null }
export interface EvaluationRetry { step_ids?: string[] | null }
export interface EvaluationAccepted { evaluation_id: string; status: string }
export interface EvaluationUsage {
  model_operations_started: number; succeeded_steps: number; failed_steps: number;
  pending_steps: number; running_steps: number;
}
export interface EvaluationStepView { id: string; kind: string; status: string; error_code: string | null; attempt: number }
export interface EvaluationView {
  id: string; query_id: string; status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'no_matches';
  stage: string; method_version: string; models: Record<string, string>; conditions: JsonObject;
  source_snapshot: JsonObject; candidate_count: number; matched_count: number; retryable: boolean;
  usage: EvaluationUsage; steps: EvaluationStepView[]; created_at: string;
}
export type EvaluationPage = MatchPage<EvaluationView>;
export interface EvaluationMatchBrief {
  candidate_id: string; summary: string; content_fit: string; audience_fit: string;
  limitations: string[]; cited_work_ids: string[]; confidence: 'limited' | 'supported';
}
export interface KnownEvaluationEvidence {
  work_id: string; source_url: string | null; content_title: string | null; timestamp_seconds: number | null;
  relation: 'current_game' | 'reference_game' | 'related_content'; status: 'metadata_only' | 'recorded_evidence';
}
export interface EvaluationResult {
  candidate_id: string; creator_id: string; platform: string; account_id: string; name: string | null; status: string;
  fit_group: 'strong_fit' | 'potential_fit' | 'limited_fit' | 'unranked'; match_brief: EvaluationMatchBrief | null;
  evidence_status: 'unknown' | 'metadata_only' | 'recorded_evidence'; evidence: KnownEvaluationEvidence[];
  needs_enrichment: boolean; stale: boolean; identity_changed: boolean; selected: false; sender_watched: false;
}
export type EvaluationResultPage = MatchPage<EvaluationResult>;
export interface MatchAPI extends CreatorSearchAPI {
  activities(input: Pagination): Promise<ApiResult<ActivityPage>>;
  createActivity(input: { data: ActivityCreate; idempotencyKey: string }): Promise<ApiResult<ActivityView>>;
  updateBrief(input: { id:string; data:{campaign_brief:string|null;expected_revision:number} }):Promise<ApiResult<ActivityView>>;
  activity(id: string): Promise<ApiResult<ActivityDetail>>;
  plans(input: Pagination & { activityId: string }): Promise<ApiResult<PlanPage>>;
  createPlan(input: { activityId: string; data: PlanCreate; idempotencyKey: string }): Promise<ApiResult<PlanAccepted>>;
  plan(id: string): Promise<ApiResult<PlanView>>;
  retryPlan(input: { id: string; idempotencyKey: string }): Promise<ApiResult<PlanAccepted>>;
  query(id: string): Promise<ApiResult<QueryView>>;
  candidates(input: CandidateListInput): Promise<ApiResult<CandidatePage>>;
  stop(input: { queryId: string; idempotencyKey: string }): Promise<ApiResult<DiscoveryStopped>>;
  continueDiscovery(input: { queryId: string; data: ContinueDiscovery; idempotencyKey: string }): Promise<ApiResult<DiscoveryAccepted>>;
  evaluations(input: Pagination & { queryId: string }): Promise<ApiResult<EvaluationPage>>;
  evaluate(input: { queryId: string; data: EvaluationCreate; idempotencyKey: string }): Promise<ApiResult<EvaluationAccepted>>;
  evaluation(id: string): Promise<ApiResult<EvaluationView>>;
  evaluationResults(input: Pagination & { id: string }): Promise<ApiResult<EvaluationResultPage>>;
  retryEvaluation(input: { id: string; data: EvaluationRetry; idempotencyKey: string }): Promise<ApiResult<EvaluationAccepted>>;
}
