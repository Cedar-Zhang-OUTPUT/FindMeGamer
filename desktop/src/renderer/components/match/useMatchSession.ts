import {useCallback,useEffect,useRef,useState} from 'react';
import type {PublicError,Result} from '../../../shared/bridge';
import type {ActivityDetail,PlanView,QueryView,CandidateView,EvaluationView,EvaluationResult,MatchAPI,MatchPage} from '../../../shared/match';
import {matchReadError} from './matchMutation';

type Scope={planId:string|null;queryId:string|null};
type ReadErrors=Partial<Record<'activity'|'plans'|'plan'|'query'|'candidates'|'evaluation',PublicError>>;
async function read<T>(action:()=>Promise<Result<T>>):Promise<Result<T>>{try{return await action();}catch{return {ok:false,error:matchReadError};}}
async function prefix<T>(capacity:number,pageSize:number,request:(offset:number)=>Promise<Result<MatchPage<T>>>):Promise<Result<MatchPage<T>>>{
  const pages=await Promise.all(Array.from({length:Math.max(1,Math.ceil(capacity/pageSize))},(_,index)=>read(()=>request(index*pageSize))));
  const failure=pages.find(page=>!page.ok);if(failure&&!failure.ok)return failure;
  const values=pages.flatMap(page=>page.ok?[page.data]:[]),first=values[0];
  return {ok:true,data:{...first,items:values.flatMap(page=>page.items)}};
}
const busyStatus=(status:string|undefined)=>status==='queued'||status==='running';
export function queryIsRunning(query:QueryView|null){return Boolean(query&&(busyStatus(query.status)||query.batches.some(batch=>busyStatus(batch.status))));}
export function useMatchSession(api:MatchAPI,activityId:string,active:boolean){
  const [activity,setActivity]=useState<ActivityDetail|null>(null),[plans,setPlans]=useState<PlanView[]>([]),[plansTotal,setPlansTotal]=useState(0);
  const [scope,setScope]=useState<Scope|null>(null),[plan,setPlan]=useState<PlanView|null>(null),[query,setQuery]=useState<QueryView|null>(null);
  const [candidates,setCandidates]=useState<CandidateView[]>([]),[candidateTotal,setCandidateTotal]=useState(0),[candidateCapacity,setCandidateCapacity]=useState(100);
  const [runs,setRuns]=useState<EvaluationView[]>([]),[runTotal,setRunTotal]=useState(0),[runCapacity,setRunCapacity]=useState(50);
  const [evaluationId,setEvaluationId]=useState<string|null|undefined>(undefined),[evaluation,setEvaluation]=useState<EvaluationView|null>(null);
  const [results,setResults]=useState<EvaluationResult[]>([]),[resultTotal,setResultTotal]=useState(0),[resultCapacity,setResultCapacity]=useState(100);
  const [errors,setErrors]=useState<ReadErrors>({}),[loading,setLoading]=useState(false),[refreshToken,setRefreshToken]=useState(0),[planCapacity,setPlanCapacity]=useState(50);
  const initialized=useRef(false),scopeVersion=useRef(0),lastQuery=useRef<string|null>(null);
  const refresh=useCallback(()=>setRefreshToken(value=>value+1),[]);
  const selectScope=useCallback((next:Scope)=>{
    scopeVersion.current++;lastQuery.current=null;setScope(next);setPlan(null);setQuery(null);setCandidates([]);setCandidateTotal(0);setCandidateCapacity(100);setRuns([]);setEvaluationId(undefined);setEvaluation(null);setResults([]);setResultTotal(0);setResultCapacity(100);setErrors({});
  },[]);
  useEffect(()=>{
    if(!active)return;let alive=true;const version=scopeVersion.current;
    void Promise.all([read(()=>api.activity(activityId)),prefix(planCapacity,50,offset=>api.plans({activityId,offset,limit:50}))]).then(([detail,history])=>{
      if(!alive)return;
      if(detail.ok)setActivity(detail.data);
      if(history.ok){setPlans(history.data.items);setPlansTotal(history.data.total);}
      setErrors(previous=>({...previous,activity:detail.ok?undefined:detail.error,plans:history.ok?undefined:history.error}));
      if(!initialized.current&&detail.ok&&history.ok&&version===scopeVersion.current){
        initialized.current=true;
        setScope(history.data.items.length?{planId:history.data.items[0].id,queryId:null}:{planId:null,queryId:detail.data.queries[0]?.id??null});
      }
    });return()=>{alive=false;};
  },[active,activityId,api,planCapacity,refreshToken]);
  useEffect(()=>{
    if(!active||!scope)return;
    let alive=true,timer:ReturnType<typeof setTimeout>|undefined;
    const current=()=>alive;
    async function poll(){
      if(!current())return;setLoading(true);let running=false;
      let queryId=scope!.queryId;
      const nextErrors:ReadErrors={};
      if(scope!.planId){
        const response=await read(()=>api.plan(scope!.planId!));if(!current())return;
        if(response.ok){setPlan(response.data);queryId=response.data.query_id;running=busyStatus(response.data.status);setPlans(previous=>previous.some(item=>item.id===response.data.id)?previous.map(item=>item.id===response.data.id?response.data:item):[response.data,...previous]);}
        else{nextErrors.plan=response.error;setErrors(previous=>({...previous,...nextErrors}));setLoading(false);return;}
      }
      if(queryId){
        // IDs change only on an explicit history choice or the selected plan resolving.
        if(lastQuery.current!==queryId){lastQuery.current=queryId;setCandidates([]);setCandidateTotal(0);setResults([]);setResultTotal(0);setEvaluation(null);}
        const id=queryId;
        const [queryResponse,candidateResponse,history]=await Promise.all([
          read(()=>api.query(id)),prefix(candidateCapacity,100,offset=>api.candidates({queryId:id,offset,limit:100})),
          prefix(runCapacity,50,offset=>api.evaluations({queryId:id,offset,limit:50})),
        ]);
        if(!current())return;
        if(queryResponse.ok){setQuery(queryResponse.data);running=running||queryIsRunning(queryResponse.data);}else nextErrors.query=queryResponse.error;
        if(candidateResponse.ok){setCandidates(candidateResponse.data.items);setCandidateTotal(candidateResponse.data.total);}else nextErrors.candidates=candidateResponse.error;
        if(history.ok){setRuns(history.data.items);setRunTotal(history.data.total);}else nextErrors.evaluation=history.error;
        const runId=evaluationId===undefined?(history.ok?history.data.items[0]?.id??null:null):evaluationId;
        if(evaluationId===undefined&&history.ok)setEvaluationId(runId);
        if(runId){
          const [run,briefs]=await Promise.all([read(()=>api.evaluation(runId)),prefix(resultCapacity,100,offset=>api.evaluationResults({id:runId,offset,limit:100}))]);
          if(!current())return;
          if(run.ok){setEvaluation(run.data);running=running||busyStatus(run.data.status);}else nextErrors.evaluation=run.error;
          if(briefs.ok){setResults(briefs.data.items);setResultTotal(briefs.data.total);}else nextErrors.evaluation=briefs.error;
        }
      }
      if(!current())return;
      setErrors(previous=>({activity:previous.activity,plans:previous.plans,...nextErrors}));setLoading(false);
      if(running)timer=setTimeout(()=>void poll(),2500);
    }
    void poll();return()=>{alive=false;if(timer)clearTimeout(timer);};
  },[api,active,scope,candidateCapacity,runCapacity,evaluationId,resultCapacity,refreshToken]);
  const selectEvaluation=useCallback((id:string)=>{setEvaluationId(id);setEvaluation(null);setResults([]);setResultTotal(0);setResultCapacity(100);refresh();},[refresh]);
  return {activity,plans,plansTotal,scope,plan,query,candidates,candidateTotal,evaluation,runs,runTotal,results,resultTotal,errors,loading,ready:Boolean(scope),refresh,selectScope,selectEvaluation,
    loadMoreCandidates:()=>setCandidateCapacity(value=>Math.min(600,value+100)),loadMoreResults:()=>setResultCapacity(value=>value+100),loadMorePlans:()=>setPlanCapacity(value=>value+50),loadMoreRuns:()=>setRunCapacity(value=>value+50)};
}
