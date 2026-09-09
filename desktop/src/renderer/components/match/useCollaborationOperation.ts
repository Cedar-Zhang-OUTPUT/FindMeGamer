import {useCallback,useEffect,useRef,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {ActivityInvitation,CollaborationAPI} from '../../../shared/collaboration';
import {COLLABORATION_RETRY_WINDOW,canRetryCollaboration,collaborationChanged,collaborationMismatch,collaborationUncertain,collaborationUnknown,dispatchCollaboration,fenceCollaboration,freezeCollaborationAttempt,reconcileCollaboration,reviewCollaboration,validCollaborationCommand,type CollaborationAttempt,type CollaborationCommand} from './collaborationMutation';
export type CollaborationOperationState={phase:'idle';error:PublicError|null}|{phase:'running'|'uncertain';attempt:CollaborationAttempt;error:PublicError|null};
export function useCollaborationOperation(api:CollaborationAPI){
 const [state,setState]=useState<CollaborationOperationState>({phase:'idle',error:null});const current=useRef(state),alive=useRef(true),inFlight=useRef(false);const [,tick]=useState(0);
 const update=useCallback((next:CollaborationOperationState)=>{current.current=next;if(alive.current)setState(next);},[]);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{if(state.phase!=='uncertain'||state.attempt.connectionChanged)return;const ms=state.attempt.startedAt+COLLABORATION_RETRY_WINDOW-Date.now();if(ms<0)return;const timer=setTimeout(()=>tick(n=>n+1),ms+1);return()=>clearTimeout(timer);},[state]);
 const dispatch=useCallback(async(attempt:CollaborationAttempt,replay:boolean):Promise<ActivityInvitation|null>=>{
  if(inFlight.current)return null;inFlight.current=true;update({phase:'running',attempt,error:null});
  try{const result=await dispatchCollaboration(api,attempt);if(!alive.current)return null;const visible=current.current.phase==='idle'?attempt:current.current.attempt;
   if(visible.connectionChanged){update({phase:'uncertain',attempt:visible,error:collaborationChanged});return null;}
   if(result.ok){if(reconcileCollaboration(visible,result.data)){update({phase:'idle',error:null});return result.data;}update({phase:'uncertain',attempt:visible,error:collaborationMismatch});return null;}
   if(!replay&&!collaborationUncertain(result.error.code))update({phase:'idle',error:result.error});else update({phase:'uncertain',attempt:result.error.code==='connection_changed'?fenceCollaboration(visible):visible,error:result.error});
  }catch{if(alive.current){const visible=current.current.phase==='idle'?attempt:current.current.attempt;update({phase:'uncertain',attempt:visible,error:visible.connectionChanged?collaborationChanged:collaborationUnknown});}}
  finally{inFlight.current=false;}return null;
 },[api,update]);
 const execute=useCallback((command:CollaborationCommand)=>current.current.phase!=='idle'||inFlight.current||!validCollaborationCommand(command)?Promise.resolve(null):dispatch(freezeCollaborationAttempt(command),false),[dispatch]);
 const retry=useCallback(()=>{const now=current.current;return now.phase==='uncertain'&&canRetryCollaboration(now.attempt)?dispatch(now.attempt,true):Promise.resolve(null);},[dispatch]);
 const credentialsChanged=useCallback(()=>{const now=current.current;if(now.phase!=='idle')update({phase:'uncertain',attempt:fenceCollaboration(now.attempt),error:collaborationChanged});},[update]);
 const finish=useCallback((row:ActivityInvitation,review:boolean)=>{const now=current.current;if(inFlight.current||now.phase!=='uncertain')return false;if(!(review?reviewCollaboration(now.attempt,row):reconcileCollaboration(now.attempt,row))){update({...now,error:collaborationMismatch});return false;}update({phase:'idle',error:null});return true;},[update]);
 const confirmReadback=useCallback((row:ActivityInvitation)=>finish(row,false),[finish]);const reviewReadback=useCallback((row:ActivityInvitation)=>finish(row,true),[finish]);
 return {state,execute,retry,credentialsChanged,confirmReadback,reviewReadback,busy:state.phase==='running',locked:state.phase==='uncertain',retryAllowed:state.phase==='uncertain'&&canRetryCollaboration(state.attempt)};
}
