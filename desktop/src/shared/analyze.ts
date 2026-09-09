import type { Result } from './bridge';
import type { GameDetail } from './games';
import type { CreatorDetail } from './creators';
export interface AnalysisJob {
  outcome: 'job'; id: string; target_type: 'game' | 'creator'; canonical_target_id: string; canonical_url: string; mode: 'create' | 'reanalyze';
  status: 'queued' | 'running' | 'succeeded' | 'failed'; stage: 'fetching_data' | 'analyzing' | 'finalizing' | null;
  completed_units: number; total_units: number; retryable: boolean; error: { code: string; message: string } | null;
  correlation_id: string | null; profile_id: string | null; created_at: string; updated_at: string; started_at: string | null; completed_at: string | null;
  waiting_reason: 'collection_disabled' | 'explicit_resume_required' | null; resume_available: boolean;
}
export interface ExistingProfile { outcome: 'existing_profile'; existing_profile_id: string; target_type: 'game' | 'creator'; canonical_target_id: string; canonical_url: string }
export type AnalysisOutcome = AnalysisJob | ExistingProfile;
export interface ChangedMatchJob {
  kind: 'match'; resource_id: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'superseded'; stage: 'screening' | 'pairwise' | 'ranking';
  completed_units: number; total_units: number; result_count: number; retryable: boolean; error: { code: string; message: string } | null;
  correlation_id: string | null; game_id: string; supersedes_id: string | null; created_at: string; updated_at: string; started_at: string | null; completed_at: string | null;
}
export interface ChangedJobs { items: ((AnalysisJob & { kind: 'analysis'; resource_id: string }) | ChangedMatchJob)[]; cursor: string; has_more: boolean; affected_profile_ids: string[] }
export interface AnalysisAPI {
  steamImport(input: { url: string; gameId?: string; expectedRevision?: number; idempotencyKey: string }): Promise<Result<GameDetail>>;
  bindYouTube(input: { creatorId: string; url: string; expectedRevision: number; idempotencyKey: string }): Promise<Result<CreatorDetail>>;
  create(input: { target_type: 'game' | 'creator'; url: string; mode: 'create' | 'reanalyze'; idempotencyKey: string }): Promise<Result<AnalysisOutcome>>;
  detail(input: { jobId: string }): Promise<Result<AnalysisJob>>;
  changed(input: { cursor?: string; limit?: number }): Promise<Result<ChangedJobs>>;
  retry(input: { jobId: string; idempotencyKey: string }): Promise<Result<AnalysisJob>>;
  resume(input: { jobId: string; idempotencyKey: string }): Promise<Result<AnalysisJob>>;
}
