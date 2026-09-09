import {createContext,useCallback,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {AnalysisJob,AnalysisOutcome} from '../../../shared/analyze';
import type {NavigationGuard} from '../../../shared/games';
import {AnalyzeDrawer} from './AnalyzeDrawer';
import './analyze.css';

export interface AnalyzeTarget {target_type:'game'|'creator';url:string;mode:'create'|'reanalyze';profileId?:string;title:string}
type Command={kind:'create';input:{target_type:'game'|'creator';url:string;mode:'create'|'reanalyze';idempotencyKey:string}}|{kind:'retry'|'resume';input:{jobId:string;idempotencyKey:string}};
export interface AnalyzeAttempt {command:Command;startedAt:number;fenced:boolean;profile?:{kind:'games'|'creators';id:string};expected?:Pick<AnalysisJob,'target_type'|'canonical_target_id'|'canonical_url'>}
export interface AnalyzeOperation {phase:'running'|'uncertain';attempt:AnalyzeAttempt;error:PublicError|null}
export interface AnalyzeTask {job:AnalysisJob;title:string}
export interface UnconfirmedAnalysisRequest {title:string;request:unknown;startedAt:number;profile?:{kind:'games'|'creators';id:string};originalWorkspace?:boolean}
export interface RetainedAnalysisRequest extends UnconfirmedAnalysisRequest {id:string;requestText:string;workspaceGeneration:number}
interface AnalyzeContextValue {request:(target:AnalyzeTarget)=>void;showTasks:()=>void;credentialsChanged:()=>void;retainUnconfirmed:(record:UnconfirmedAnalysisRequest)=>void;activeCount:number;completionVersion:number}
const noop=()=>{};
const AnalyzeContext=createContext<AnalyzeContextValue>({request:noop,showTasks:noop,credentialsChanged:noop,retainUnconfirmed:noop,activeCount:0,completionVersion:0});
export const useAnalyze=()=>useContext(AnalyzeContext);
const unknown:PublicError={code:'analysis_write_unknown',message:'Request not confirmed. Retry the original request.',retryable:false};
const changed:PublicError={code:'connection_changed',message:'Check this task in the original workspace.',retryable:false};
const retryWindow=86_400_000;
export function canReplayAnalysis(attempt:AnalyzeAttempt){const age=Date.now()-attempt.startedAt;return !attempt.fenced&&age>=0&&age<retryWindow;}
const uncertain=(code:string)=>['analysis_write_unknown','network_error','connection_changed','analysis_queue_unavailable','invalid_response'].includes(code);
const active=(job:AnalysisJob)=>job.status==='queued'||job.status==='running';

export function AnalyzeProvider({api,children,onConnectionRepair,onCollectionSettings,onOpenProfile,onNavigationGuardChange}:{api:DesktopBridge;children:ReactNode;onConnectionRepair?:()=>void;onCollectionSettings?:()=>void;onOpenProfile?:(profile:{kind:'games'|'creators';id:string})=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void}){
 const [visible,setVisible]=useState(false),[target,setTarget]=useState<AnalyzeTarget|null>(null),[tasks,setTasks]=useState<AnalyzeTask[]>([]),[existing,setExisting]=useState<Extract<AnalysisOutcome,{outcome:'existing_profile'}>|null>(null);
 const [operation,setOperation]=useState<AnalyzeOperation|null>(null),[retained,setRetained]=useState<RetainedAnalysisRequest[]>([]),[error,setError]=useState<PublicError|null>(null),[readErrors,setReadErrors]=useState<Record<string,string>>({}),[historyBusy,setHistoryBusy]=useState(false),[historyError,setHistoryError]=useState<string|null>(null),[hasMore,setHasMore]=useState(false),[completionVersion,setCompletionVersion]=useState(0);
 const alive=useRef(true),generation=useRef(0),operationRef=useRef(operation),tasksRef=useRef(tasks),busy=useRef(false),readBusy=useRef(false),historyInFlight=useRef(false),cursor=useRef<string|undefined>(undefined),historyLoaded=useRef(false),versions=useRef(new Map<string,number>()),polls=useRef(new Map<string,number>()),opener=useRef<HTMLElement|null>(null),titleRef=useRef('Analysis');
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;generation.current++;};},[]);
 const updateOperation=useCallback((value:AnalyzeOperation|null)=>{operationRef.current=value;if(alive.current)setOperation(value);},[]);
 const accept=useCallback((job:AnalysisJob,title?:string,write=false)=>{
  if(write)versions.current.set(job.id,(versions.current.get(job.id)??0)+1);
  const previous=tasksRef.current.find(t=>t.job.id===job.id);
  if(previous&&Date.parse(previous.job.updated_at)>Date.parse(job.updated_at))return;
  if(job.status==='succeeded'&&previous?.job.status!=='succeeded')setCompletionVersion(n=>n+1);
  const row={job,title:title??previous?.title??job.canonical_url};const next=previous?tasksRef.current.map(t=>t.job.id===job.id?row:t):[row,...tasksRef.current];tasksRef.current=next;setTasks(next);
  setReadErrors(old=>{const next={...old};delete next[job.id];return next;});
 },[]);
 const credentialsChanged=useCallback(()=>{
  generation.current++;historyLoaded.current=false;cursor.current=undefined;versions.current.clear();polls.current.clear();tasksRef.current=[];setTasks([]);setExisting(null);setTarget(null);setReadErrors({});setHistoryError(null);setHasMore(false);
  const current=operationRef.current;if(current)updateOperation({...current,phase:'uncertain',attempt:{...current.attempt,fenced:true},error:changed});
 },[updateOperation]);
 const retainUnconfirmed=useCallback((record:UnconfirmedAnalysisRequest)=>{
  // Only renderer-owned public command data; no IPC call or success inference.
  // The serialized copy is immutable even if its caller later edits the source form.
  const requestText=JSON.stringify(record.request,null,2);const snapshot=Object.freeze({...record,profile:record.profile?Object.freeze({...record.profile}):undefined,request:requestText,id:crypto.randomUUID(),requestText,workspaceGeneration:record.originalWorkspace?-1:generation.current});
  setRetained(rows=>[snapshot,...rows]);
 },[]);
 const keepUnresolved=useCallback(()=>{
  const current=operationRef.current;if(busy.current||current?.phase!=='uncertain'||canReplayAnalysis(current.attempt))return;
  retainUnconfirmed({title:titleRef.current,request:current.attempt.command,startedAt:current.attempt.startedAt,profile:current.attempt.profile,originalWorkspace:current.attempt.fenced});
  setTarget(null);setError(null);updateOperation(null);
 },[retainUnconfirmed,updateOperation]);
 // Saved jobs/history can be re-read in their workspace. Only local intent or an
 // unresolved write needs a credential-repair detour; history must not lock Settings.
 const hasRetainedState=!!target||!!operation||retained.length>0;
 useEffect(()=>{if(!hasRetainedState){onNavigationGuardChange?.(null);return;}const guard:NavigationGuard=proceed=>proceed();guard.recovery={credentialsChanged};onNavigationGuardChange?.(guard);return()=>onNavigationGuardChange?.(null);},[credentialsChanged,hasRetainedState,onNavigationGuardChange]);
 useEffect(()=>{if(!operation&&!retained.length)return;const unload=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',unload);return()=>window.removeEventListener('beforeunload',unload);},[operation,retained.length]);
 // Expiry changes the available action even if nothing else renders the drawer.
 const [,tick]=useState(0);useEffect(()=>{if(operation?.phase!=='uncertain'||operation.attempt.fenced)return;const delay=operation.attempt.startedAt+retryWindow-Date.now();if(delay<0)return;const timer=setTimeout(()=>tick(n=>n+1),delay+1);return()=>clearTimeout(timer);},[operation]);
 const dispatch=useCallback(async(attempt:AnalyzeAttempt,replay=false)=>{
  if(busy.current)return;busy.current=true;const epoch=generation.current;setError(null);updateOperation({phase:'running',attempt,error:null});
  try{
   const command=attempt.command;const result=command.kind==='create'?await api.analysis.create(command.input):command.kind==='retry'?await api.analysis.retry(command.input):await api.analysis.resume(command.input);
   if(!alive.current)return;const current=operationRef.current?.attempt??attempt;
   if(epoch!==generation.current||current.fenced){updateOperation({phase:'uncertain',attempt:{...current,fenced:true},error:changed});return;}
   if(!result.ok){if(replay||uncertain(result.error.code))updateOperation({phase:'uncertain',attempt:{...attempt,fenced:result.error.code==='connection_changed'},error:result.error});else{setError(result.error);updateOperation(null);}return;}
   if(attempt.expected&&(result.data.target_type!==attempt.expected.target_type||result.data.canonical_target_id!==attempt.expected.canonical_target_id||result.data.canonical_url!==attempt.expected.canonical_url)){updateOperation({phase:'uncertain',attempt,error:{code:'analysis_write_unknown',message:'Returned task does not match this request. Check task history.',retryable:false}});return;}
   if(result.data.outcome==='existing_profile')setExisting(result.data);else accept(result.data,titleRef.current,true);
   setTarget(null);updateOperation(null);
  }catch{if(alive.current){const current=operationRef.current?.attempt??attempt;updateOperation({phase:'uncertain',attempt:current,error:current.fenced?changed:unknown});}}
  finally{busy.current=false;}
 },[api,accept,updateOperation]);
 const start=useCallback((kind:'create'|'retry'|'resume',value:AnalyzeTarget|AnalysisJob)=>{
  if(operationRef.current||busy.current)return;
  const idempotencyKey=crypto.randomUUID();let command:Command;let expected:AnalyzeAttempt['expected'];let profile:AnalyzeAttempt['profile'];
  if(kind==='create'){const t=value as AnalyzeTarget;titleRef.current=t.title;command={kind,input:Object.freeze({target_type:t.target_type,url:t.url,mode:t.mode,idempotencyKey})};if(t.profileId)profile=Object.freeze({kind:t.target_type==='game'?'games':'creators',id:t.profileId});}
  else{const job=value as AnalysisJob;if(kind==='retry'&&!(job.status==='failed'&&job.retryable)||kind==='resume'&&!job.resume_available)return;titleRef.current=tasksRef.current.find(t=>t.job.id===job.id)?.title??job.canonical_url;command={kind,input:Object.freeze({jobId:job.id,idempotencyKey})};expected=Object.freeze({target_type:job.target_type,canonical_target_id:job.canonical_target_id,canonical_url:job.canonical_url});}
  void dispatch(Object.freeze({command:Object.freeze(command),startedAt:Date.now(),fenced:false,expected,profile}));
 },[dispatch]);
 const refresh=useCallback(async(jobId:string)=>{
  if(readBusy.current||busy.current)return;readBusy.current=true;const epoch=generation.current,version=versions.current.get(jobId)??0;
  try{const result=await api.analysis.detail({jobId});if(!alive.current||generation.current!==epoch||(versions.current.get(jobId)??0)!==version)return;
   if(result.ok&&result.data.id===jobId)accept(result.data);else setReadErrors(old=>({...old,[jobId]:result.ok?'Task identity could not be verified.':result.error.message}));
  }catch{if(alive.current&&generation.current===epoch)setReadErrors(old=>({...old,[jobId]:'Status unavailable. Refresh to try again.'}));}finally{readBusy.current=false;}
 },[api,accept]);
 useEffect(()=>{let cancelled=false;const timer=setInterval(()=>{
  if(cancelled||busy.current||readBusy.current||operationRef.current?.attempt.fenced)return;
  const row=tasksRef.current.find(t=>active(t.job)&&!t.job.waiting_reason&&!readErrors[t.job.id]&&(polls.current.get(t.job.id)??0)<15);
  if(row){polls.current.set(row.job.id,(polls.current.get(row.job.id)??0)+1);void refresh(row.job.id);}
 },2000);return()=>{cancelled=true;clearInterval(timer);};},[refresh,readErrors]);
 const loadHistory=useCallback(async()=>{
  if(historyInFlight.current)return;historyInFlight.current=true;setHistoryBusy(true);setHistoryError(null);const epoch=generation.current,readVersions=new Map(versions.current);
  try{const result=await api.analysis.changed({...(cursor.current?{cursor:cursor.current}:{}),limit:100});if(!alive.current||epoch!==generation.current)return;
   if(!result.ok){setHistoryError(result.error.message);return;}for(const row of result.data.items)if(row.kind==='analysis'&&(versions.current.get(row.id)??0)===(readVersions.get(row.id)??0))accept(row);
   cursor.current=result.data.cursor;setHasMore(result.data.has_more);historyLoaded.current=true;
  }catch{if(alive.current&&epoch===generation.current)setHistoryError('Task history unavailable.');}finally{historyInFlight.current=false;if(alive.current)setHistoryBusy(false);}
 },[api,accept]);
 const open=useCallback(()=>{opener.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setVisible(true);},[]);
 const request=useCallback((value:AnalyzeTarget)=>{if(!operationRef.current&&!busy.current){setTarget({...value});setExisting(null);setError(null);}open();},[open]);
 const showTasks=useCallback(()=>{open();if(!historyLoaded.current)void loadHistory();},[open,loadHistory]);
 const close=useCallback(()=>{setVisible(false);const element=opener.current;if(element?.isConnected&&!element.closest('[hidden]'))element.focus();},[]);
 return <AnalyzeContext.Provider value={{request,showTasks,credentialsChanged,retainUnconfirmed,activeCount:tasks.filter(t=>active(t.job)).length+(operation?1:0),completionVersion}}>{children}
  <AnalyzeDrawer visible={visible} target={target} tasks={tasks} retained={retained} workspaceGeneration={generation.current} existing={existing} operation={operation} error={error} readErrors={readErrors} historyBusy={historyBusy} historyError={historyError} hasMore={hasMore} onKeepUnresolved={keepUnresolved} onClose={close} onAnalyze={()=>target&&start('create',target)} onDismissTarget={()=>setTarget(null)} onReplay={()=>{const current=operationRef.current;if(current?.phase==='uncertain'&&canReplayAnalysis(current.attempt))void dispatch(current.attempt,true);}} onRetry={job=>start('retry',job)} onResume={job=>start('resume',job)} onRefresh={id=>{polls.current.set(id,0);void refresh(id);}} onHistory={()=>void loadHistory()} onConnectionRepair={onConnectionRepair} onCollectionSettings={onCollectionSettings} onOpenProfile={onOpenProfile?profile=>{close();onOpenProfile(profile);}:undefined}/>
 </AnalyzeContext.Provider>;
}
