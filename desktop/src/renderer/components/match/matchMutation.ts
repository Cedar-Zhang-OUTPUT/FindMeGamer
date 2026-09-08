import type {PublicError,Result} from '../../../shared/bridge';
import type {ActivityCreate,ActivityView,PlanCreate,PlanAccepted,ContinueDiscovery,DiscoveryAccepted,DiscoveryStopped,EvaluationCreate,EvaluationRetry,EvaluationAccepted,MatchAPI} from '../../../shared/match';

export type MatchCommand=
  | {kind:'createActivity';data:ActivityCreate}
  | {kind:'createPlan';activityId:string;data:PlanCreate}
  | {kind:'retryPlan';id:string}
  | {kind:'stop';queryId:string}
  | {kind:'continueDiscovery';queryId:string;data:ContinueDiscovery}
  | {kind:'evaluate';queryId:string;data:EvaluationCreate}
  | {kind:'retryEvaluation';id:string;data:EvaluationRetry};
export type MatchReceipt=ActivityView|PlanAccepted|DiscoveryAccepted|DiscoveryStopped|EvaluationAccepted;
export interface MatchAttempt {command:MatchCommand;key:string;startedAt:number;connectionChanged:boolean}
export const MATCH_RETRY_WINDOW=86_400_000;
export const matchReadError:PublicError={code:'network_error',message:'Could not refresh. Your current results are still here.',retryable:true};
export const matchWriteError:PublicError={code:'save_outcome_unknown',message:'The request may already be running. Check status or retry the same request.',retryable:false};
export const matchAuthErrors=new Set(['workspace_key_invalid','access_denied','not_connected','secure_storage_unavailable']);
const rejected=new Set([...matchAuthErrors,'request_invalid','invalid_request','rate_limited','activity_not_found','game_not_found','game_context_required','reference_work_not_found','discovery_query_not_found','discovery_conflict','planning_conflict','evaluation_conflict','discovery_plan_not_found','evaluation_not_found','invalid_candidates','identity_changed','activity_reference_invalid','discovery_not_found','discovery_not_runnable','planning_not_retryable','evaluation_running','evaluation_not_retryable','evaluation_candidates_invalid','evaluation_retry_invalid','match_not_found']);
export function matchRejected(code:string){return rejected.has(code);}
function freeze<T>(value:T):T {if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;}
export function freezeMatchAttempt(command:MatchCommand,startedAt=Date.now(),key:string=crypto.randomUUID()):MatchAttempt {
  return {command:freeze(structuredClone(command)),key,startedAt,connectionChanged:false};
}
export function canRetryMatch(attempt:MatchAttempt,now=Date.now()){
  const age=now-attempt.startedAt;return !attempt.connectionChanged&&age>=0&&age<MATCH_RETRY_WINDOW;
}
export function dispatchMatch(api:MatchAPI,attempt:MatchAttempt):Promise<Result<MatchReceipt>> {
  const {command,key:idempotencyKey}=attempt;
  switch(command.kind){
    case 'createActivity':return api.createActivity({data:command.data,idempotencyKey});
    case 'createPlan':return api.createPlan({activityId:command.activityId,data:command.data,idempotencyKey});
    case 'retryPlan':return api.retryPlan({id:command.id,idempotencyKey});
    case 'stop':return api.stop({queryId:command.queryId,idempotencyKey});
    case 'continueDiscovery':return api.continueDiscovery({queryId:command.queryId,data:command.data,idempotencyKey});
    case 'evaluate':return api.evaluate({queryId:command.queryId,data:command.data,idempotencyKey});
    case 'retryEvaluation':return api.retryEvaluation({id:command.id,data:command.data,idempotencyKey});
  }
}
