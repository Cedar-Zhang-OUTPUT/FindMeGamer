import type { PublicError, Result } from '../../../shared/bridge';
import type { CreatorAPI, CreatorCreate, CreatorDetail, CreatorPatch, ContactCreate, ContactPatch, WorkCreate, WorkPatch, WorkDetail, IdentityUpdate } from '../../../shared/creators';

export type MutationCommand =
  | {kind:'creator';id:string|null;data:CreatorCreate|CreatorPatch}
  | {kind:'contact';creatorId:string;id:string|null;data:ContactCreate|ContactPatch}
  | {kind:'work';creatorId:string;id:string|null;data:WorkCreate|WorkPatch}
  | {kind:'identity';id:string;data:IdentityUpdate};
export interface MutationAttempt {command:MutationCommand;key:string;startedAt:number;credentialsChanged:boolean;workspaceChanged:boolean}
export const RETRY_WINDOW=86_400_000;
export const mutationNetworkError:PublicError={code:'save_outcome_unknown',message:'The save result is unconfirmed. Check the current record before saving again.',retryable:false};
export const readNetworkError:PublicError={code:'network_error',message:'Could not load the current record. Your changes are still here.',retryable:true};
export const authErrors=new Set(['workspace_key_invalid','access_denied','not_connected','secure_storage_unavailable']);
const rejected=new Set(['request_invalid','invalid_request','workspace_key_invalid','access_denied','not_connected','secure_storage_unavailable','creator_identity_conflict','creator_contact_conflict','creator_revision_conflict','work_revision_conflict','creator_identity_changed','creator_not_found','creator_contact_not_found','creator_work_not_found','game_not_found','creator_analysis_in_progress','creator_delivery_in_progress','rate_limited']);
export function certainlyRejected(code:string){return rejected.has(code);}
function frozen<T>(value:T):T {
  if(value&&typeof value==='object'){Object.values(value).forEach(frozen);Object.freeze(value);}return value;
}
export function freezeAttempt(command:MutationCommand,startedAt=Date.now(),key:string=crypto.randomUUID()):MutationAttempt {
  return {command:frozen(structuredClone(command)),key,startedAt,credentialsChanged:false,workspaceChanged:false};
}
export function isCreation(command:MutationCommand){return command.kind!=='identity'&&command.id===null;}
export function canReplay(attempt:MutationAttempt,now=Date.now()) {
  const age=now-attempt.startedAt;
  return isCreation(attempt.command)&&!attempt.credentialsChanged&&!attempt.workspaceChanged&&age>=0&&age<RETRY_WINDOW;
}
export function dispatchMutation(api:CreatorAPI,attempt:MutationAttempt):Promise<Result<CreatorDetail|WorkDetail>> {
  const command=attempt.command;
  switch(command.kind){
    case 'creator':return command.id?api.update({id:command.id,data:command.data as CreatorPatch}):api.create({data:command.data as CreatorCreate,idempotencyKey:attempt.key});
    case 'contact':return command.id?api.updateContact({creatorId:command.creatorId,contactId:command.id,data:command.data as ContactPatch}):api.createContact({creatorId:command.creatorId,data:command.data as ContactCreate,idempotencyKey:attempt.key});
    case 'work':return command.id?api.updateWork({creatorId:command.creatorId,workId:command.id,data:command.data as WorkPatch}):api.createWork({creatorId:command.creatorId,data:command.data as WorkCreate,idempotencyKey:attempt.key});
    case 'identity':return api.rebind({id:command.id,data:command.data});
  }
}
