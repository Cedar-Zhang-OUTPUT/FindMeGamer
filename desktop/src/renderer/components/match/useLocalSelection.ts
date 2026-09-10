import {useCallback,useEffect,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {CandidateView} from '../../../shared/match';
import type {Preparation} from '../../../shared/outreach';
import {emptySelectionDraft,findLocalMember,isLocalMemberSelected,mergeSelectionRead,prepareLocalSelection,reconcileLocalBulk,setDesiredSelection,type LocalPrepareState,type LocalSelectionMember} from './localSelectionPrepare';
import {outreachReadError,readSelections} from './useOutreachSession';
import {reconcileOutreachBatch} from './outreachMutation';

export function useLocalSelection(api:Pick<DesktopBridge,'outreach'|'localSelections'>,activityId:string,queryId:string|null,rows:Preparation[],current:boolean){
 const enabled=Boolean(api.localSelections),[state,setState]=useState<LocalPrepareState|null>(null),[loading,setLoading]=useState(enabled),[busy,setBusy]=useState(false),[error,setError]=useState<PublicError|null>(null);
 const live=useRef(state),generation=useRef(0),inFlight=useRef(false),queue=useRef(Promise.resolve());
 const update=useCallback((next:LocalPrepareState)=>{live.current=next;setState(next);},[]);
 const persist=useCallback(async(next:LocalPrepareState)=>{
  const input={activityId,queryId,scope:next.draft.scope,state:structuredClone(next)};
  // Send local IPC immediately; the main-process journal serializes writes. Do
  // not leave later keystrokes waiting in a renderer-only queue during reload.
  const job=api.localSelections!.write(input).then(response=>{if(!response.ok)throw response.error;});
  const pending=Promise.all([queue.current.catch(()=>{}),job]).then(()=>{});queue.current=pending;await pending;
 },[api.localSelections,activityId,queryId]);
 useEffect(()=>{
  const token=++generation.current;live.current=null;setState(null);setLoading(enabled);setBusy(false);setError(null);
  if(enabled)void api.localSelections!.read({activityId,queryId}).then(result=>{
   if(token!==generation.current)return;
   if(!result.ok){setError(result.error);return;}
   update(result.data.state??{stage:'ready',draft:emptySelectionDraft(result.data.scope,activityId)});
  }).catch(cause=>{if(token===generation.current)setError(outreachReadError(cause));}).finally(()=>{if(token===generation.current)setLoading(false);});
  return()=>{generation.current++;};
 },[api.localSelections,enabled,activityId,queryId,update]);
 useEffect(()=>{
  const previous=live.current;if(!enabled||!current||!previous||previous.stage!=='ready'||inFlight.current)return;
  const draft=mergeSelectionRead(previous.draft,rows);if(JSON.stringify(draft)===JSON.stringify(previous.draft))return;
  const next:LocalPrepareState={stage:'ready',draft};update(next);const token=generation.current;
  void persist(next).catch(cause=>{if(token===generation.current)setError(outreachReadError(cause));});
 },[enabled,current,rows,state?.draft.initialized,persist,update]);
 const locked=Boolean(state&&!['ready','done'].includes(state.stage));
 function change(member:LocalSelectionMember,selected:boolean){
  const previous=live.current;if(!previous||inFlight.current||!['ready','done'].includes(previous.stage))return;
  if(!selected){const known=findLocalMember(previous.draft,member);const row=rows.find(row=>row.id===known?.observed?.selectionId)||rows.find(row=>row.candidate_id===known?.candidateId);if(row)member={...member,removal:{selectionId:row.id,revision:row.revision}};}
  try{const next:LocalPrepareState={stage:'ready',draft:setDesiredSelection(previous.draft,member,selected)};update(next);setError(null);const token=generation.current;void persist(next).catch(cause=>{if(token===generation.current)setError(outreachReadError(cause));});}catch(cause){setError(outreachReadError(cause));}
 }
 function toggle(candidate:CandidateView){
  if(candidate.identity_changed||!['youtube','x','twitch','instagram'].includes(candidate.platform))return;
  const member=memberFrom(candidate);change(member,!live.current||!isLocalMemberSelected(live.current.draft,member));
 }
 function memberFrom(candidate:CandidateView):LocalSelectionMember{return {candidateId:candidate.id,creatorId:candidate.creator_id,name:candidate.creator?.name??null,queryId,identity:{platform:candidate.platform as LocalSelectionMember['identity']['platform'],account_id:candidate.account_id,revision:candidate.identity_revision}};}
 async function prepare(){
  const previous=live.current;if(!previous||inFlight.current||loading)return null;
  if(previous.stage==='done')return previous.batch;
  inFlight.current=true;setBusy(true);setError(null);const token=generation.current;
  try{
   await queue.current;
   // Revalidate the original credential/service scope before a pending replay too.
   await persist(previous);if(token!==generation.current)return null;
   const next=await prepareLocalSelection(previous,{api:api.outreach,persist:async value=>{if(token!==generation.current)throw Error('context changed');await persist(value);if(token!==generation.current)throw Error('context changed');update(value);}});
   if(token!==generation.current)return null;
   update(next);await persist(next);return next.stage==='done'?next.batch:null;
  }catch(cause){if(token===generation.current)setError(outreachReadError(cause));return null;}finally{inFlight.current=false;if(token===generation.current)setBusy(false);}
 }
 async function reviewConflict(currentRows:Preparation[]=rows){
  // This is explicit acknowledgement, never a background refresh. Keep desired
  // choices; accept current revisions only for unchanged creator account identity.
  const previous=live.current;if(previous?.stage!=='conflict'||inFlight.current||!current)return;
  const draft=structuredClone(previous.draft);
  for(const row of currentRows){const member=draft.members[row.candidate_id];if(!member)continue;
   if(row.identity_changed||row.identity.platform!==member.identity.platform||row.identity.account_id!==member.identity.account_id||row.identity.revision!==member.identity.revision)continue;
   member.observed=row.active?{selectionId:row.id,revision:row.revision}:member.observed;
  }
  const next:LocalPrepareState={stage:'ready',draft:mergeSelectionRead(draft,currentRows)};update(next);try{await persist(next);}catch(cause){setError(outreachReadError(cause));}
 }
 async function checkSaved(){
  const previous=live.current;if(!previous||inFlight.current||!['bulk_pending','freeze_pending'].includes(previous.stage))return;
  const token=generation.current;inFlight.current=true;setBusy(true);
  try{
   await persist(previous);if(token!==generation.current)return;
   let next:LocalPrepareState|undefined;
   if(previous.stage==='bulk_pending'){
    const all=await readSelections(api.outreach,activityId,true);
    if(reconcileLocalBulk(previous,all))next={stage:'readback',draft:previous.draft};
   }else if(previous.stage==='freeze_pending'){
    for(let offset=0;offset<10000;offset+=200){const response=await api.outreach.batches({activityId,offset,limit:200});if(!response.ok)throw response.error;
     const match=response.data.items.find(row=>row.request_id===previous.input.data.request_id);
     if(match){const detail=await api.outreach.batch({activityId,id:match.id});if(!detail.ok)throw detail.error;
      const attempt={command:{kind:'freeze' as const,activityId,data:{recipients:previous.input.data.recipients}},input:previous.input,startedAt:0,connectionChanged:false};
      if(reconcileOutreachBatch(attempt,detail.data))next={stage:'done',draft:previous.draft,batch:detail.data};break;}
     if(offset+response.data.items.length>=response.data.total)break;if(!response.data.items.length)throw Error('incomplete');
    }
   }
   if(token!==generation.current)return;
   if(next){await persist(next);if(token===generation.current)update(next);setError(null);}
   else setError({code:'local_selection_unconfirmed',message:'The current records do not confirm this exact request. The original recovery data is still retained.',retryable:false});
  }catch(cause){if(token===generation.current)setError(outreachReadError(cause));}finally{inFlight.current=false;if(token===generation.current)setBusy(false);}
 }
 async function retryPersistence(){const value=live.current;if(!value)return;try{await persist(value);setError(null);}catch(cause){setError(outreachReadError(cause));}}
 const credentialsChanged=useCallback(()=>{generation.current++;setLoading(true);setError({code:'connection_changed',message:'These choices belong to the previous workspace. Reopen the activity after reconnecting.',retryable:false});},[]);
 return {enabled,state,loading,busy,locked,error,ready:Boolean(state?.draft.initialized)&&!loading,desired:state?.draft.desired??[],toggle,change,prepare,reviewConflict,checkSaved,retryPersistence,
  isSelected:(candidate:CandidateView)=>Boolean(!candidate.identity_changed&&live.current&&isLocalMemberSelected(live.current.draft,memberFrom(candidate))),
  credentialsChanged,
 };
}
