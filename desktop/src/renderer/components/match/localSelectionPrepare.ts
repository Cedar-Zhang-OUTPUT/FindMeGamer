import type {PublicError} from '../../../shared/bridge';
import type {OutreachAPI,Preparation,RecipientBatchDetail,SelectionIdentity} from '../../../shared/outreach';
import {OUTREACH_RETRY_WINDOW,outreachOutcomeUncertain,outreachWriteUnknown} from './outreachMutation';
import {outreachReadError,readSelections} from './useOutreachSession';

export interface LocalSelectionMember {
  candidateId:string;creatorId:string;name:string|null;identity:SelectionIdentity;queryId:string|null;
  observed?:{selectionId:string;revision:number};
}
export interface LocalSelectionDraft {
  version:1;scope:string;activityId:string;initialized:boolean;
  desired:string[];removed:string[];members:Record<string,LocalSelectionMember>;
}
type Base={draft:LocalSelectionDraft;error?:PublicError};
export type LocalPrepareState =
  | Base & {stage:'ready'}
  | Base & {stage:'bulk_pending';input:Parameters<OutreachAPI['bulk']>[0];startedAt:number}
  | Base & {stage:'readback'}
  | Base & {stage:'freeze_pending';input:Parameters<OutreachAPI['freeze']>[0]}
  | Base & {stage:'conflict';previous?:Exclude<LocalPrepareState,{stage:'conflict'}>}
  | Base & {stage:'done';batch:RecipientBatchDetail};
export interface LocalPreparePorts {
  api:Pick<OutreachAPI,'selections'|'bulk'|'freeze'>;
  persist:(state:LocalPrepareState)=>Promise<void>;
  now?:()=>number;
}
const conflict:PublicError={code:'local_selection_conflict',message:'Selection or account data changed. Review current records before preparing again.',retryable:false};
const diskError:PublicError={code:'local_selection_storage_failed',message:'Could not save preparation recovery data on this Mac. No new request was started.',retryable:true};
const sameIdentity=(a:SelectionIdentity,b:SelectionIdentity)=>a.platform===b.platform&&a.account_id===b.account_id&&a.revision===b.revision;
const memberOf=(p:Preparation):LocalSelectionMember=>({candidateId:p.candidate_id,creatorId:p.creator_id,name:p.name,identity:structuredClone(p.identity),queryId:null,observed:{selectionId:p.id,revision:p.revision}});

export function emptySelectionDraft(scope:string,activityId:string):LocalSelectionDraft {
  return {version:1,scope,activityId,initialized:false,desired:[],removed:[],members:{}};
}
/** Merge all activity selections, never just visible search rows. Explicit removals
 * are durable tombstones; background reads cannot turn them back into selections. */
export function mergeSelectionRead(draft:LocalSelectionDraft,rows:Preparation[]):LocalSelectionDraft {
  const next=structuredClone(draft);
  for(const row of rows){
    if(row.activity_id!==draft.activityId)throw conflict;
    if(!row.active)continue;
    if(!Object.hasOwn(next.members,row.candidate_id))next.members[row.candidate_id]=memberOf(row);
    if(!next.removed.includes(row.candidate_id)&&!next.desired.includes(row.candidate_id))next.desired.push(row.candidate_id);
  }
  next.initialized=true;return next;
}
/** Pure and synchronous: neither this action nor pagination/filter changes write HTTP. */
export function setDesiredSelection(draft:LocalSelectionDraft,member:LocalSelectionMember,selected:boolean):LocalSelectionDraft {
  const next=structuredClone(draft),existing=next.members[member.candidateId];
  if(existing&&!sameIdentity(existing.identity,member.identity))throw conflict;
  next.members[member.candidateId]=existing??structuredClone(member);
  next.desired=next.desired.filter(id=>id!==member.candidateId);
  if(selected){next.desired.push(member.candidateId);next.removed=next.removed.filter(id=>id!==member.candidateId);}
  else if(!next.removed.includes(member.candidateId))next.removed.push(member.candidateId);
  return next;
}
function currentMembers(draft:LocalSelectionDraft,rows:Preparation[],afterBulk:boolean):Map<string,Preparation>{
  const active=new Map<string,Preparation>();
  for(const row of rows){
    if(row.activity_id!==draft.activityId)throw conflict;
    if(!row.active)continue;
    if(active.has(row.candidate_id))throw conflict;
    active.set(row.candidate_id,row);
    // A new, unseen colleague selection is not permission to cancel it.
    if(!draft.desired.includes(row.candidate_id)&&!draft.removed.includes(row.candidate_id))throw conflict;
  }
  for(const id of draft.desired){
    const local=draft.members[id],row=active.get(id);
    if(!local)throw conflict;
    const name=local.name||local.identity.account_id;
    if(!row){if(afterBulk||local.observed)throw {...conflict,message:`${name} is no longer selected on the server. Review or remove this local choice.`};continue;}
    if(row.identity_changed||row.creator_id!==local.creatorId||!sameIdentity(row.identity,local.identity))throw {...conflict,message:`${name}'s account changed. Remove the old choice and select the verified account again.`};
    if(local.observed&&(row.id!==local.observed.selectionId||row.revision!==local.observed.revision))throw {...conflict,message:`${name}'s selection was updated. Review the current record before preparing.`};
    if(!row.freeze_ready)throw conflict;
  }
  for(const id of draft.removed){
    const row=active.get(id),local=draft.members[id];
    if(row&&(!local?.observed||row.id!==local.observed.selectionId||row.revision!==local.observed.revision||row.identity_changed||!sameIdentity(row.identity,local.identity)))throw conflict;
  }
  return active;
}
function failure(state:LocalPrepareState,error:PublicError):LocalPrepareState {
  if(state.stage==='conflict'||state.stage==='done')return state;
  return {stage:'conflict',draft:state.draft,error,previous:state};
}
/** The caller must serialize runs and lock conflicting local edits. Every outbound
 * request has its exact payload/key durably checkpointed before dispatch. A caller
 * may recreate this state after restart; pending stages replay, never recompute. */
export async function prepareLocalSelection(initial:LocalPrepareState,ports:LocalPreparePorts):Promise<LocalPrepareState>{
  let state=structuredClone(initial);
  const persist=async(next:LocalPrepareState)=>{await ports.persist(structuredClone(next));state=next;};
  if(state.stage==='done'||state.stage==='conflict')return state;
  if(!state.draft.initialized||!state.draft.desired.length||state.draft.desired.length>600||new Set(state.draft.desired).size!==state.draft.desired.length)return failure(state,conflict);
  try{
    if(state.stage==='ready'){
      const rows=await readSelections(ports.api,state.draft.activityId,true);
      const active=currentMembers(state.draft,rows,false);
      const add=state.draft.desired.filter(id=>!active.has(id));
      const cancel=[...active.values()].filter(row=>!state.draft.desired.includes(row.candidate_id)).map(row=>({selection_id:row.id,expected_revision:row.revision}));
      if(add.length>600||cancel.length>600)throw conflict;
      const next:LocalPrepareState=add.length||cancel.length?{stage:'bulk_pending',draft:state.draft,startedAt:(ports.now??Date.now)(),input:{activityId:state.draft.activityId,idempotencyKey:crypto.randomUUID(),data:{add_candidate_ids:add,cancel_selections:cancel}}}:{stage:'readback',draft:state.draft};
      try{await persist(next);}catch{return {...state,error:diskError};}
    }
    if(state.stage==='bulk_pending'){
      const age=(ports.now??Date.now)()-state.startedAt;
      if(age<0||age>=OUTREACH_RETRY_WINDOW)return {...state,error:{code:'local_selection_retry_expired',message:'The original selection request expired. Check saved selections before resolving this preparation.',retryable:false}};
      let result;
      try{result=await ports.api.bulk(structuredClone(state.input));}catch{return {...state,error:outreachWriteUnknown};}
      if(!result.ok)return outreachOutcomeUncertain(result.error.code)?{...state,error:result.error}:failure(state,result.error);
      try{await persist({stage:'readback',draft:state.draft});}catch{return {...state,error:{...diskError,message:'The selection may be saved. Recovery checkpoint failed; retry the original request.'}};}
    }
    if(state.stage==='readback'){
      const rows=await readSelections(ports.api,state.draft.activityId,true),active=currentMembers(state.draft,rows,true);
      const recipients=state.draft.desired.map(id=>{const p=active.get(id)!;return {selection_id:p.id,expected_revision:p.revision,context_token:p.context_token};});
      const draft=structuredClone(state.draft);
      for(const id of draft.desired){const row=active.get(id)!;draft.members[id].observed={selectionId:row.id,revision:row.revision};}
      // An acknowledged local cancellation must be selectable again later;
      // retain its tombstone, but no longer claim it is server-active.
      for(const id of draft.removed)if(!active.has(id)&&draft.members[id])delete draft.members[id].observed;
      try{await persist({stage:'freeze_pending',draft,input:{activityId:state.draft.activityId,idempotencyKey:crypto.randomUUID(),data:{request_id:crypto.randomUUID(),recipients}}});}catch{return {...state,error:diskError};}
    }
    if(state.stage==='freeze_pending'){
      let result;
      try{result=await ports.api.freeze(structuredClone(state.input));}catch{return {...state,error:outreachWriteUnknown};}
      if(!result.ok)return outreachOutcomeUncertain(result.error.code)?{...state,error:result.error}:failure(state,result.error);
      const batch=result.data,choices=state.input.data.recipients;
      if(batch.activity_id!==state.draft.activityId||batch.request_id!==state.input.data.request_id||batch.recipient_count!==choices.length||batch.recipients.length!==choices.length||choices.some((choice,index)=>{const r=batch.recipients[index];return r.selection_id!==choice.selection_id||r.snapshot.id!==choice.selection_id||r.snapshot.activity_id!==state.draft.activityId||r.snapshot.revision!==choice.expected_revision||r.snapshot.context_token!==choice.context_token;}))return {...state,error:outreachWriteUnknown};
      try{await persist({stage:'done',draft:state.draft,batch});}catch{return {...state,error:{...diskError,message:'Preparation may already exist. Retry the original request to recover it.'}};}
    }
    return state;
  }catch(error){
    const problem=outreachReadError(error);
    return problem.code===conflict.code?failure(state,problem):{...state,error:problem};
  }
}
