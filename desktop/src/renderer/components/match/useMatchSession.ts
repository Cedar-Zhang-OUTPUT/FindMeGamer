import {useCallback,useEffect,useRef,useState} from 'react';
import type {PublicError,Result} from '../../../shared/bridge';
import type {ActivityDetail,PlanView,QueryView,CandidateView,CandidateQueryOptions,EvaluationView,EvaluationResult,MatchAPI,MatchPage} from '../../../shared/match';
import {matchReadError} from './matchMutation';

type Scope={planId:string|null;queryId:string|null};
type ReadErrors=Partial<Record<'activity'|'plans'|'plan'|'query'|'candidates'|'evaluation',PublicError>>;
type RequiredCandidateOptions=Required<CandidateQueryOptions>;
type CandidatePreference={options:RequiredCandidateOptions;capacity:number};
const DEFAULT_CANDIDATE_OPTIONS:RequiredCandidateOptions={evidence:'all',sort:'relevance'};
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
  const [candidates,setCandidates]=useState<CandidateView[]>([]),[candidateTotal,setCandidateTotal]=useState(0);
  const [candidateOptions,setCandidateOptionsState]=useState<RequiredCandidateOptions>(DEFAULT_CANDIDATE_OPTIONS);
  const [candidateMembershipCurrent,setCandidateMembershipCurrent]=useState(false),[candidateLoading,setCandidateLoading]=useState(false);
  const [runs,setRuns]=useState<EvaluationView[]>([]),[runTotal,setRunTotal]=useState(0),[runCapacity,setRunCapacity]=useState(50);
  const [evaluationId,setEvaluationId]=useState<string|null|undefined>(undefined),[evaluation,setEvaluation]=useState<EvaluationView|null>(null);
  const [results,setResults]=useState<EvaluationResult[]>([]),[resultTotal,setResultTotal]=useState(0),[resultCapacity,setResultCapacity]=useState(100);
  const [errors,setErrors]=useState<ReadErrors>({}),[loading,setLoading]=useState(false),[refreshToken,setRefreshToken]=useState(0),[planCapacity,setPlanCapacity]=useState(50);
  const initialized=useRef(false),scopeVersion=useRef(0),lastQuery=useRef<string|null>(null);
  const candidateOptionsRef=useRef<RequiredCandidateOptions>(DEFAULT_CANDIDATE_OPTIONS),candidateCapacity=useRef(100),candidateReadVersion=useRef(0);
  const candidatePreferences=useRef(new Map<string,CandidatePreference>());
  const refresh=useCallback(()=>setRefreshToken(value=>value+1),[]);
  const selectScope=useCallback((next:Scope)=>{
    scopeVersion.current++;candidateReadVersion.current++;lastQuery.current=null;setScope(next);setPlan(null);setQuery(null);setCandidates([]);setCandidateTotal(0);setCandidateMembershipCurrent(false);setCandidateLoading(false);setRuns([]);setEvaluationId(undefined);setEvaluation(null);setResults([]);setResultTotal(0);setResultCapacity(100);setErrors({});
  },[]);
  const readCandidates=useCallback(async(id:string,capacity:number,options:RequiredCandidateOptions)=>{
    const version=++candidateReadVersion.current;
    setCandidateLoading(true);
    const response=await prefix(capacity,100,offset=>api.candidates({queryId:id,offset,limit:100,...options}));
    if(version!==candidateReadVersion.current||lastQuery.current!==id)return;
    if(response.ok){setCandidates(response.data.items);setCandidateTotal(response.data.total);setCandidateMembershipCurrent(true);}
    else setCandidateMembershipCurrent(false);
    setErrors(previous=>({...previous,candidates:response.ok?undefined:response.error}));
    setCandidateLoading(false);
  },[api]);
  useEffect(()=>()=>{candidateReadVersion.current++;},[]);
  useEffect(()=>{if(!active){candidateReadVersion.current++;setCandidateLoading(false);}},[active]);
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
        if(lastQuery.current!==queryId){
          candidateReadVersion.current++;lastQuery.current=queryId;
          const preference=candidatePreferences.current.get(queryId)??{options:DEFAULT_CANDIDATE_OPTIONS,capacity:100};
          candidateOptionsRef.current=preference.options;candidateCapacity.current=preference.capacity;
          setCandidateOptionsState(preference.options);setCandidates([]);setCandidateTotal(0);setCandidateMembershipCurrent(false);
          setResults([]);setResultTotal(0);setEvaluation(null);
        }
        const id=queryId;
        const [queryResponse,,history]=await Promise.all([
          read(()=>api.query(id)),readCandidates(id,candidateCapacity.current,candidateOptionsRef.current),
          prefix(runCapacity,50,offset=>api.evaluations({queryId:id,offset,limit:50})),
        ]);
        if(!current())return;
        if(queryResponse.ok){setQuery(queryResponse.data);running=running||queryIsRunning(queryResponse.data);}else nextErrors.query=queryResponse.error;
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
      setErrors(previous=>({activity:previous.activity,plans:previous.plans,candidates:previous.candidates,...nextErrors}));setLoading(false);
      if(running)timer=setTimeout(()=>void poll(),2500);
    }
    void poll();return()=>{alive=false;if(timer)clearTimeout(timer);};
  },[api,active,scope,runCapacity,evaluationId,resultCapacity,refreshToken,readCandidates]);
  const selectEvaluation=useCallback((id:string)=>{setEvaluationId(id);setEvaluation(null);setResults([]);setResultTotal(0);setResultCapacity(100);refresh();},[refresh]);
  const setCandidateOptions=useCallback((next:RequiredCandidateOptions)=>{
    if(next.evidence===candidateOptionsRef.current.evidence&&next.sort===candidateOptionsRef.current.sort)return;
    const options={...next};candidateOptionsRef.current=options;candidateCapacity.current=100;setCandidateOptionsState(options);setCandidateMembershipCurrent(false);
    const id=lastQuery.current;if(!id)return;
    candidatePreferences.current.set(id,{options,capacity:100});
    if(active)void readCandidates(id,100,options);
  },[active,readCandidates]);
  const loadMoreCandidates=useCallback(()=>{
    const id=lastQuery.current;if(!id||!candidateMembershipCurrent)return;
    const capacity=Math.min(600,candidateCapacity.current+100);if(capacity===candidateCapacity.current)return;
    candidateCapacity.current=capacity;candidatePreferences.current.set(id,{options:candidateOptionsRef.current,capacity});
    if(active)void readCandidates(id,capacity,candidateOptionsRef.current);
  },[active,candidateMembershipCurrent,readCandidates]);
  return {activity,plans,plansTotal,scope,plan,query,candidates,candidateTotal,candidateOptions,candidateMembershipCurrent,candidateLoading,evaluation,runs,runTotal,results,resultTotal,errors,loading,ready:Boolean(scope),refresh,selectScope,selectEvaluation,setCandidateOptions,
    loadMoreCandidates,loadMoreResults:()=>setResultCapacity(value=>value+100),loadMorePlans:()=>setPlanCapacity(value=>value+50),loadMoreRuns:()=>setRunCapacity(value=>value+50)};
}
