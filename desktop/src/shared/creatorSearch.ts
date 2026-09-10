import type { ApiResult, MatchPage, Pagination, PlanCreate } from './match';
export type CreatorSearchStatus = 'queued'|'running'|'stopping'|'stopped'|'completed'|'partial'|'failed';
export type CreatorSearchStage = 'planning'|'discovery'|'profiles'|'emails'|'screening'|'deep_match'|'ranking'|'complete';
export interface CreatorSearch {
  id:string;activity_id:string;plan_id:string;query_id:string|null;evaluation_id:string|null;parent_search_id:string|null;
  status:CreatorSearchStatus;stage:CreatorSearchStage;
  counts:{discovered:number;profile_ready:number;profile_reused:number;profile_failed:number;email_available:number;email_missing:number;email_failed:number;evaluated:number;matched:number};
  stop_requested:boolean;retryable:boolean;outcome_unknown:boolean;error_code:string|null;created_at:string;updated_at:string;
}
export interface CreatorSearchPerson {
  candidate_id:string;creator_id:string;platform:'youtube'|'x'|'twitch'|'instagram';
  profile_status:'pending'|'running'|'ready'|'reused'|'failed';email_status:'pending'|'running'|'available'|'missing'|'failed';
  analysis_job_id:string|null;profile_error_code:string|null;email_error_code:string|null;
}
export interface CreatorSearchAccepted {search_id:string;status:CreatorSearchStatus}
export interface CreatorSearchAPI {
  creatorSearches(input:Pagination&{activityId:string}):Promise<ApiResult<MatchPage<CreatorSearch>>>;
  createCreatorSearch(input:{activityId:string;data:PlanCreate;idempotencyKey:string}):Promise<ApiResult<CreatorSearchAccepted>>;
  creatorSearch(id:string):Promise<ApiResult<CreatorSearch>>;
  creatorSearchPeople(input:Pagination&{id:string}):Promise<ApiResult<MatchPage<CreatorSearchPerson>>>;
  stopCreatorSearch(input:{id:string;idempotencyKey:string}):Promise<ApiResult<CreatorSearchAccepted>>;
  retryCreatorSearch(input:{id:string;data:{acknowledge_unknown?:boolean};idempotencyKey:string}):Promise<ApiResult<CreatorSearchAccepted>>;
  appendCreatorSearch(input:{id:string;idempotencyKey:string}):Promise<ApiResult<CreatorSearchAccepted>>;
}
