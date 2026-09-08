import {ErrorNotice} from '../Primitives';
import type {useMatchOperation} from './useMatchOperation';

export function MatchOperationNotice({operation,onRetry,onCheck,onRepair}:{operation:ReturnType<typeof useMatchOperation>;onRetry:()=>void;onCheck?:()=>void;onRepair?:()=>void}){
  const {state}=operation;
  return <>{state.phase==='running'&&<p className="match-operation-status" role="status">Submitting…</p>}{state.phase==='uncertain'&&<section className="match-uncertain" aria-label="Unconfirmed request"><h3>Request not confirmed</h3><p>{state.attempt.connectionChanged?'Credentials changed. Locate the saved task in its original workspace before starting another request.':!operation.retryAllowed?'The safe retry window has ended. Locate the saved task before starting another request.':'This operation may already be saved or running. A retry uses the same request, not a new task.'}</p><div className="button-row"><button className="button primary" disabled={!operation.retryAllowed} onClick={onRetry}>Retry same request</button>{onCheck&&<button className="button secondary" onClick={onCheck}>Check saved tasks</button>}</div></section>}{state.error&&<ErrorNotice error={state.error}/>} {onRepair&&state.error&&<button className="button secondary" onClick={onRepair}>Open Settings</button>}</>;
}
