import {useCallback,useEffect,useRef,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {MatchAPI} from '../../../shared/match';
import {canRetryMatch,dispatchMatch,freezeMatchAttempt,matchRejected,matchWriteError,MATCH_RETRY_WINDOW,type MatchAttempt,type MatchCommand,type MatchReceipt} from './matchMutation';

export type OperationState={phase:'idle';error:PublicError|null}|{phase:'running'|'uncertain';attempt:MatchAttempt;error:PublicError|null};
export type OperationReceipt={command:MatchCommand;data:MatchReceipt};
export function useMatchOperation(api:MatchAPI){
  const [state,setState]=useState<OperationState>({phase:'idle',error:null});
  const current=useRef(state),alive=useRef(true),inFlight=useRef(false);
  const rejectedAttempt=useRef<MatchAttempt|null>(null);
  const [,tick]=useState(0);
  const update=useCallback((next:OperationState)=>{current.current=next;if(alive.current)setState(next);},[]);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    const attempt=state.phase==='uncertain'?state.attempt:state.phase==='idle'?rejectedAttempt.current:null;
    if(!attempt)return;
    const remaining=attempt.startedAt+MATCH_RETRY_WINDOW-Date.now();
    if(remaining<0)return;
    const timer=setTimeout(()=>tick(value=>value+1),remaining+1);return()=>clearTimeout(timer);
  },[state]);
  const dispatch=useCallback(async(attempt:MatchAttempt,replay:boolean):Promise<OperationReceipt|null>=>{
    if(inFlight.current)return null;
    inFlight.current=true;rejectedAttempt.current=null;update({phase:'running',attempt,error:null});
    try{
      const response=await dispatchMatch(api,attempt);
      if(!alive.current)return null;
      const latest=current.current.phase==='idle'?attempt:current.current.attempt;
      if(latest.connectionChanged){update({phase:'uncertain',attempt:latest,error:{code:'connection_changed',message:'Credentials changed. Check saved activity and task history before starting another request.',retryable:false}});return null;}
      if(response.ok){update({phase:'idle',error:null});return {command:attempt.command,data:response.data};}
      if(!replay&&matchRejected(response.error.code)){rejectedAttempt.current=attempt;update({phase:'idle',error:response.error});}
      else update({phase:'uncertain',attempt:{...latest,connectionChanged:response.error.code==='connection_changed'},error:response.error});
      return null;
    }catch{if(alive.current){const latest=current.current.phase==='idle'?attempt:current.current.attempt;update({phase:'uncertain',attempt:latest,error:matchWriteError});}return null;}
    finally{inFlight.current=false;}
  },[api,update]);
  const execute=useCallback((command:MatchCommand)=>current.current.phase==='idle'?dispatch(freezeMatchAttempt(command),false):Promise.resolve(null),[dispatch]);
  const retry=useCallback(()=>current.current.phase==='uncertain'&&canRetryMatch(current.current.attempt)?dispatch(current.current.attempt,true):Promise.resolve(null),[dispatch]);
  const retryRejected=useCallback(()=>{const attempt=rejectedAttempt.current;return current.current.phase==='idle'&&attempt&&canRetryMatch(attempt)?dispatch(attempt,false):Promise.resolve(null);},[dispatch]);
  const credentialsChanged=useCallback(()=>{rejectedAttempt.current=null;const latest=current.current;if(latest.phase!=='idle')update({...latest,attempt:{...latest.attempt,connectionChanged:true}});},[update]);
  const confirmSaved=useCallback(()=>{if(!inFlight.current)update({phase:'idle',error:null});},[update]);
  return {state,execute,retry,retryRejected,retryRejectedAllowed:state.phase==='idle'&&Boolean(rejectedAttempt.current&&canRetryMatch(rejectedAttempt.current)),credentialsChanged,confirmSaved,busy:state.phase==='running',locked:state.phase==='uncertain',retryAllowed:state.phase==='uncertain'&&canRetryMatch(state.attempt)};
}
