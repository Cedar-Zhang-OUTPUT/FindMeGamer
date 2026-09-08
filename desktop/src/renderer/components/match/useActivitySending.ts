import {useCallback,useEffect,useRef,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {CompositionView} from '../../../shared/drafts';
import type {DeliveryResolution,Exclusion,Qualification,SendBatch,SendingAPI} from '../../../shared/sending';
import {useSendingOperation} from './useSendingOperation';
import type {SendingReceipt} from './sendingMutation';

type Mode={kind:'drafts'}|{kind:'review';compositionId:string}|{kind:'deliveries';batchId:string};
type QualificationState={phase:'empty';value:null}|{phase:'checking'|'stale'|'current';value:Qualification|null};
interface Props {api:SendingAPI;activityId:string;composition:CompositionView|null;active:boolean;blocked?:boolean;pollMs?:number}
const scopeError:PublicError={code:'sending_scope_mismatch',message:'This record does not match the original recipients or frozen email. Reload the current record.',retryable:true};
const readError:PublicError={code:'sending_read_failed',message:'Could not load sending status. Try again.',retryable:true};
function canonical(value:unknown):string {if(!value||typeof value!=='object')return JSON.stringify(value);if(Array.isArray(value))return `[${value.map(canonical).join(',')}]`;return `{${Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>`${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;}
function same(a:unknown,b:unknown){return canonical(a)===canonical(b);}
const exclusionsValid=(rows:Exclusion[])=>rows.length<=600&&new Set(rows.map(row=>row.draft_id)).size===rows.length&&rows.every(row=>row.reason.trim().length>0&&row.reason.length<=1000);
export function qualificationMatchesComposition(q:Qualification,c:CompositionView,excluded:Exclusion[]):boolean {
  return q.composition_id===c.id&&q.activity_id===c.activity_id&&q.total_count===c.recipient_count&&q.members.length===c.drafts.length
    &&q.members.every((row,index)=>row.draft_id===c.drafts[index].id&&row.recipient_snapshot_id===c.drafts[index].recipient_snapshot_id)
    &&q.excluded_count===excluded.length&&excluded.every(item=>q.members.some(row=>row.draft_id===item.draft_id&&row.status==='excluded'&&row.exclusion_reason===item.reason.trim()));
}
function sameFrozenBatch(before:SendBatch,next:SendBatch):boolean {
  return before.id===next.id&&before.activity_id===next.activity_id&&before.composition_id===next.composition_id&&before.created_at===next.created_at
    &&same(before.qualification,next.qualification)&&before.deliveries.length===next.deliveries.length&&before.deliveries.every((row,index)=>{
      const other=next.deliveries[index];return row.id===other.id&&row.send_batch_id===other.send_batch_id&&row.draft_id===other.draft_id&&row.recipient_snapshot_id===other.recipient_snapshot_id&&same(row.snapshot,other.snapshot)&&other.attempt>=row.attempt;
    });
}
export function useActivitySending({api,activityId,composition,active,blocked=false,pollMs=4000}:Props){
  const [mode,setMode]=useState<Mode>({kind:'drafts'}),[qualificationState,setQualificationState]=useState<QualificationState>({phase:'empty',value:null});
  const [choices,setChoices]=useState<Record<string,Exclusion[]>>({}),[batch,setBatch]=useState<SendBatch|null>(null),[current,setCurrent]=useState(false);
  const [loading,setLoading]=useState(false),[error,setError]=useState<PublicError|null>(null),[readback,setReadback]=useState<SendBatch|null>(null);
  const [historyEpoch,setHistoryEpoch]=useState(0),[verificationDirty,setVerificationDirty]=useState(false),[verificationEpoch,setVerificationEpoch]=useState(0);
  const operation=useSendingOperation(api);
  const alive=useRef(true),sequence=useRef(0),reading=useRef(false),compositionRef=useRef(composition),batchRef=useRef(batch),modeRef=useRef(mode),choicesRef=useRef(choices);
  const latest=useRef({active,blocked,operation,current,qualificationState});
  compositionRef.current=composition;batchRef.current=batch;modeRef.current=mode;choicesRef.current=choices;latest.current={active,blocked,operation,current,qualificationState};
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;sequence.current++;};},[]);
  const invalidate=useCallback(()=>{
    sequence.current++;reading.current=false;setLoading(false);setCurrent(false);
    latest.current={...latest.current,current:false,qualificationState:{phase:'stale',value:latest.current.qualificationState.value}};
    setQualificationState(previous=>({phase:'stale',value:previous.value}));
  },[]);
  useEffect(()=>{if(!active)invalidate();},[active,invalidate]);
  const signature=composition?`${composition.id}:${composition.drafts.map(row=>`${row.id}/${row.revision}/${row.context_token}/${row.source_changed}/${row.status}`).join(';')}`:'';
  const priorSignature=useRef(signature);
  useEffect(()=>{if(priorSignature.current!==signature){priorSignature.current=signature;invalidate();}},[signature,invalidate]);
  const compositionId=mode.kind==='review'?mode.compositionId:composition?.id;
  const exclusions=compositionId?choices[compositionId]??[]:[];
  const qualification=qualificationState.value;
  const qualificationCurrent=active&&!blocked&&qualificationState.phase==='current'&&!!qualification&&!!composition&&qualificationMatchesComposition(qualification,composition,exclusions);
  const busy=loading||operation.busy,locked=operation.locked;
  const dirty=verificationDirty||(mode.kind!=='deliveries'&&exclusions.length>0);
  function changeExclusions(value:Exclusion[]){
    const state=latest.current,owner=modeRef.current.kind==='review'?modeRef.current.compositionId:compositionRef.current?.id;
    if(!owner||state.operation.busy||state.operation.locked)return;
    invalidate();const next={...choicesRef.current,[owner]:structuredClone(value)};choicesRef.current=next;setChoices(next);
  }
  const checkQualification=useCallback(async()=>{
    const c=compositionRef.current,state=latest.current,view=modeRef.current;
    if(!c||!state.active||state.blocked||state.operation.busy||state.operation.locked||view.kind!=='review'||view.compositionId!==c.id)return false;
    const excluded=structuredClone(choicesRef.current[c.id]??[]);if(!exclusionsValid(excluded)||excluded.some(row=>!c.drafts.some(draft=>draft.id===row.draft_id)))return false;
    const token=++sequence.current;setLoading(true);setError(null);setQualificationState(previous=>({phase:'checking',value:previous.value}));
    try{
      const result=await api.qualify({compositionId:c.id,data:{excluded}});if(!alive.current||token!==sequence.current)return false;
      if(!result.ok){setError(result.error);setQualificationState(previous=>({phase:'stale',value:previous.value}));return false;}
      if(!qualificationMatchesComposition(result.data,c,excluded)){setError(scopeError);setQualificationState(previous=>({phase:'stale',value:previous.value}));return false;}
      setQualificationState({phase:'current',value:result.data});return true;
    }catch{if(alive.current&&token===sequence.current){setError(readError);setQualificationState(previous=>({phase:'stale',value:previous.value}));}return false;}
    finally{if(alive.current&&token===sequence.current)setLoading(false);}
  },[api]);
  async function begin(){
    const c=compositionRef.current,state=latest.current;if(!c||!state.active||state.blocked||state.operation.busy||state.operation.locked)return false;
    invalidate();modeRef.current={kind:'review',compositionId:c.id};setMode(modeRef.current);setReadback(null);
    if(qualificationState.value?.composition_id!==c.id)setQualificationState({phase:'empty',value:null});
    return checkQualification();
  }
  function backToDrafts(){if(operation.busy||operation.locked)return;invalidate();modeRef.current={kind:'drafts'};setMode(modeRef.current);setReadback(null);}
  function adopt(value:SendBatch){batchRef.current=value;setBatch(value);setCurrent(true);}
  const readBatch=useCallback(async(id:string,foreground=false):Promise<SendBatch|null>=>{
    if(reading.current||latest.current.operation.busy||!latest.current.active)return null;
    const token=++sequence.current;reading.current=true;if(foreground)setLoading(true);setError(null);
    try{
      const result=await api.batch(id);if(!alive.current||token!==sequence.current)return null;if(!result.ok){setError(result.error);setCurrent(false);return null;}
      const prior=batchRef.current;if(result.data.id!==id||result.data.activity_id!==activityId||prior?.id===id&&!sameFrozenBatch(prior,result.data)){setError(scopeError);setCurrent(false);return null;}
      adopt(result.data);return result.data;
    }catch{if(alive.current&&token===sequence.current){setError(readError);setCurrent(false);}return null;}
    finally{if(alive.current&&token===sequence.current){reading.current=false;setLoading(false);}}
  },[api,activityId]);
  async function openBatch(id:string){
    if(!active||busy||locked)return;invalidate();setReadback(null);modeRef.current={kind:'deliveries',batchId:id};setMode(modeRef.current);
    if(batchRef.current?.id!==id){batchRef.current=null;setBatch(null);}await readBatch(id,true);
  }
  const refreshBatch=useCallback(async()=>{const view=modeRef.current;if(view.kind==='deliveries')await readBatch(view.batchId,true);},[readBatch]);
  const polling=active&&mode.kind==='deliveries'&&batch?.deliveries.some(row=>row.state==='queued'||row.state==='sending')&&!operation.busy&&!operation.locked;
  useEffect(()=>{if(!polling||mode.kind!=='deliveries')return;const timer=setInterval(()=>void readBatch(mode.batchId),pollMs);return()=>clearInterval(timer);},[polling,mode,readBatch,pollMs]);
  function accept(receipt:SendingReceipt|null):boolean {
    if(!receipt)return false;setReadback(null);setError(null);
    if(receipt.kind==='send'){
      if(receipt.data.activity_id!==activityId)return false;adopt(receipt.data);modeRef.current={kind:'deliveries',batchId:receipt.data.id};setMode(modeRef.current);setHistoryEpoch(value=>value+1);setQualificationState(previous=>({phase:'stale',value:previous.value}));
    }else{
      const previous=batchRef.current;if(!previous||receipt.data.send_batch_id!==previous.id)return false;
      adopt({...previous,deliveries:previous.deliveries.map(row=>row.id===receipt.data.id?receipt.data:row)});
    }return true;
  }
  async function send(){
    const state=latest.current,value=state.qualificationState.value,c=compositionRef.current,view=modeRef.current;
    const excluded=structuredClone(c?choicesRef.current[c.id]??[]:[]);
    if(!state.active||state.blocked||state.qualificationState.phase!=='current'||!value?.send_ready||!c||!exclusionsValid(excluded)||!qualificationMatchesComposition(value,c,excluded)||busy||state.operation.busy||state.operation.locked||view.kind!=='review'||view.compositionId!==c.id)return false;
    const q=structuredClone(value);invalidate();setReadback(null);
    return accept(await operation.execute({kind:'send',compositionId:q.composition_id,data:{qualification_token:q.qualification_token,excluded},observedQualification:q}));
  }
  async function retryDelivery(id:string){
    const row=batchRef.current?.deliveries.find(row=>row.id===id);if(!active||blocked||busy||locked||!current||!row||!(row.state==='queued'||row.state==='failed'&&row.retryable))return false;
    invalidate();return accept(await operation.execute({kind:'retry',id,data:{expected_attempt:row.attempt},observedDelivery:row}));
  }
  async function resolveDelivery(id:string,data:DeliveryResolution){
    const row=batchRef.current?.deliveries.find(row=>row.id===id);if(!active||blocked||busy||locked||!current||!row||row.state!=='unknown'||data.expected_attempt!==row.attempt)return false;
    invalidate();return accept(await operation.execute({kind:'resolve',id,data,observedDelivery:row}));
  }
  async function retryOriginal(){if(!active||operation.busy||loading)return false;invalidate();return accept(await operation.retry());}
  async function checkCurrent(){
    if(operation.state.phase!=='uncertain'||operation.state.attempt.connectionChanged||operation.busy)return;
    const command=operation.state.attempt.command;if(command.kind==='send')return;
    const value=await readBatch(command.observedDelivery.send_batch_id,true);if(!value)return;
    const receipt=command.kind==='resolve'?operation.confirmReadback(value):null;
    if(receipt)accept(receipt);else setReadback(value);
  }
  function reviewCurrent(){if(readback&&operation.reviewReadback(readback)){adopt(readback);setReadback(null);}}
  const credentialsChanged=useCallback(()=>{invalidate();operation.credentialsChanged();setReadback(null);setHistoryEpoch(value=>value+1);},[invalidate,operation.credentialsChanged]);
  function discardEdits(){setChoices({});choicesRef.current={};setVerificationDirty(false);setVerificationEpoch(value=>value+1);invalidate();}
  return {mode,qualification,qualificationCurrent,exclusions,changeExclusions,batch,current,loading,busy,locked,error,dirty,operation,readback,historyEpoch,verificationEpoch,setVerificationDirty,
    begin,backToDrafts,invalidate,checkQualification,send,openBatch,refreshBatch,retryDelivery,resolveDelivery,retryOriginal,checkCurrent,reviewCurrent,credentialsChanged,discardEdits};
}
