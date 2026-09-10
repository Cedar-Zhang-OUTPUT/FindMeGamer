import type {PublicError} from '../../../shared/bridge';
import type {OutreachAPI,Preparation,RecipientBatchDetail,SelectionIdentity} from '../../../shared/outreach';
import {OUTREACH_RETRY_WINDOW,outreachOutcomeUncertain,outreachWriteUnknown} from './outreachMutation';
import {outreachReadError,readSelections} from './useOutreachSession';

export interface LocalSelectionMember {
  candidateId:string;creatorId:string;name:string|null;identity:SelectionIdentity;queryId:string|null;
  observed?:{selectionId:string;revision:number};
  removal?:{selectionId:string;revision:number};
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
const samePerson=(a:LocalSelectionMember,b:LocalSelectionMember)=>a.creatorId===b.creatorId&&sameIdentity(a.identity,b.identity);
export function findLocalMember(draft:LocalSelectionDraft,member:LocalSelectionMember){return draft.members[member.candidateId]??Object.values(draft.members).find(value=>samePerson(value,member));}
export function isLocalMemberSelected(draft:LocalSelectionDraft,member:LocalSelectionMember){return draft.desired.some(id=>draft.members[id]&&samePerson(draft.members[id],member));}
function uniqueDesired(draft:LocalSelectionDraft){const seen:LocalSelectionMember[]=[];return draft.desired.filter(id=>{const member=draft.members[id];if(!member||seen.some(other=>samePerson(other,member)))return false;seen.push(member);return true;});}
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
    const incoming=memberOf(row),known=Object.values(next.members).find(member=>member.observed?.selectionId===row.id||samePerson(member,incoming));
    const id=known?.candidateId??row.candidate_id;if(!known)next.members[id]=incoming;
    const removed=next.removed.some(id=>{const member=next.members[id];return member&&(member.observed?.selectionId===row.id||member.removal?.selectionId===row.id||samePerson(member,incoming));});
    if(!removed&&!isLocalMemberSelected(next,next.members[id]))next.desired.push(id);
  }
  next.desired=uniqueDesired(next);next.initialized=true;return next;
}
/** Pure and synchronous: neither this action nor pagination/filter changes write HTTP. */
export function setDesiredSelection(draft:LocalSelectionDraft,member:LocalSelectionMember,selected:boolean):LocalSelectionDraft {
  const next=structuredClone(draft),existing=findLocalMember(next,member);
  if(existing&&!samePerson(existing,member))throw conflict;
  const id=existing?.candidateId??member.candidateId;
  next.members[id]=existing??structuredClone(member);
  if(!selected&&member.removal)next.members[id].removal=structuredClone(member.removal);
  next.desired=next.desired.filter(key=>key!==id&&!samePerson(next.members[key],member));
  if(selected){delete next.members[id].removal;next.desired.push(id);next.removed=next.removed.filter(key=>key!==id&&!samePerson(next.members[key],member));}
  else if(!next.removed.includes(id))next.removed.push(id);
  return next;
}
function currentMembers(draft:LocalSelectionDraft,rows:Preparation[],afterBulk:boolean):Map<string,Preparation>{
  const active=new Map<string,Preparation>(),server:Preparation[]=[];
  for(const row of rows){
    if(row.activity_id!==draft.activityId)throw conflict;
    if(!row.active)continue;
    if(server.some(other=>other.id===row.id||sameIdentity(other.identity,row.identity)))throw conflict;
    server.push(row);
  }
  for(const id of new Set([...draft.desired,...draft.removed])){
    const member=draft.members[id];if(!member)throw conflict;
    const knownId=draft.removed.includes(id)?member.removal?.selectionId??member.observed?.selectionId:member.observed?.selectionId;
    const row=server.find(value=>value.id===knownId)??server.find(value=>value.candidate_id===member.candidateId)??server.find(value=>samePerson(member,memberOf(value)));
    if(row)active.set(id,row);
  }
  // Unrepresented colleagues' selections are never implicit cancellations.
  if(server.some(row=>![...active.values()].some(known=>known.id===row.id)))throw conflict;
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
    const explicitlyAcknowledged=local?.removal?.selectionId===row?.id&&local?.removal?.revision===row?.revision;
    if(row&&!explicitlyAcknowledged&&(!local?.observed||row.id!==local.observed.selectionId||row.revision!==local.observed.revision||row.identity_changed||!sameIdentity(row.identity,local.identity)))throw conflict;
  }
  return active;
}
function failure(state:LocalPrepareState,error:PublicError):LocalPrepareState {
  if(state.stage==='conflict'||state.stage==='done')return state;
  return {stage:'conflict',draft:state.draft,error,previous:state};
}
export function reconcileLocalBulk(state:Extract<LocalPrepareState,{stage:'bulk_pending'}>,rows:Preparation[]):boolean{
  const {data}=state.input;
  return (data.add_candidate_ids??[]).every(id=>{const member=state.draft.members[id];return member&&rows.filter(row=>row.activity_id===state.draft.activityId&&row.active&&!row.identity_changed&&samePerson(member,memberOf(row))).length===1;})
    &&(data.cancel_selections??[]).every(choice=>rows.filter(row=>row.activity_id===state.draft.activityId&&row.id===choice.selection_id&&!row.active&&row.revision===choice.expected_revision+1).length===1);
}
/** The caller must serialize runs and lock conflicting local edits. Every outbound
 * request has its exact payload/key durably checkpointed before dispatch. A caller
 * may recreate this state after restart; pending stages replay, never recompute. */
export async function prepareLocalSelection(initial:LocalPrepareState,ports:LocalPreparePorts):Promise<LocalPrepareState>{
  let state=structuredClone(initial);
  if(state.stage==='ready')state.draft.desired=uniqueDesired(state.draft);
  const persist=async(next:LocalPrepareState)=>{await ports.persist(structuredClone(next));state=next;};
  if(state.stage==='done'||state.stage==='conflict')return state;
  if(!state.draft.initialized||!state.draft.desired.length||state.draft.desired.length>600||new Set(state.draft.desired).size!==state.draft.desired.length)return failure(state,conflict);
  try{
    if(state.stage==='ready'){
      const rows=await readSelections(ports.api,state.draft.activityId,true);
      const active=currentMembers(state.draft,rows,false);
      const add=state.draft.desired.filter(id=>!active.has(id));
      const desiredIds=new Set(state.draft.desired.map(id=>active.get(id)?.id));
      const cancelRows=new Map(state.draft.removed.map(id=>active.get(id)).filter((row):row is Preparation=>Boolean(row)&&!desiredIds.has(row!.id)).map(row=>[row.id,row]));
      const cancel=[...cancelRows.values()].map(row=>({selection_id:row.id,expected_revision:row.revision}));
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
      for(const id of draft.removed)if(!active.has(id)&&draft.members[id]){delete draft.members[id].observed;delete draft.members[id].removal;}
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
