import type { Result } from './bridge';
import type { CandidatePage, CandidateQueryOptions, MatchPage, Pagination } from './match';

/** Immutable named membership; neither an outreach selection nor a Creator snapshot. */
export interface SavedSetCreate { request_id: string; name: string; candidate_ids: string[] }
export interface SavedSetView {
  id: string; query_id: string; activity_id: string; name: string;
  candidate_ids: string[]; count: number; created_at: string;
}
export type SavedSetPage = MatchPage<SavedSetView>;
export interface SavedSetsAPI {
  list(input: Pagination & { activityId: string }): Promise<Result<SavedSetPage>>;
  detail(id: string): Promise<Result<SavedSetView>>;
  results(input: Pagination & CandidateQueryOptions & { id: string }): Promise<Result<CandidatePage>>;
  create(input: { queryId: string; data: SavedSetCreate; idempotencyKey: string }): Promise<Result<SavedSetView>>;
}
