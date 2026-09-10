import {useCallback,useEffect,useRef,useState} from 'react';
import type {MatchAPI,CandidateView,EvaluationResult,MatchPage} from '../../../shared/match';
import type {CreatorSearch,CreatorSearchPerson} from '../../../shared/creatorSearch';
import type {PublicError,Result} from '../../../shared/bridge';
import {readCandidateMembership} from './outreachProjection';
import {matchReadError} from './matchMutation';
export const creatorSearchRunning=(value:CreatorSearch|null)=>Boolean(value&&['queued','running','stopping'].includes(value.status));
type Scope={kind:'loading'|'legacy'}|{kind:'search';id:string};
async function all<T extends {candidate_id:string}>(fetch:(offset:number)=>Promise<Result<MatchPage<T>>>):Promise<T[]>{
  const items:T[]=[];let total:number|undefined;
  for(let offset=0;offset<600;offset+=100){const r=await fetch(offset);if(!r.ok)throw r.error;if(r.data.offset!==offset||r.data.total>600||(total!==undefined&&r.data.total!==total))throw matchReadError;total=r.data.total;if(r.data.items.length!==Math.min(100,Math.max(0,total-offset)))throw matchReadError;items.push(...r.data.items);if(new Set(items.map(item=>item.candidate_id)).size!==items.length)throw matchReadError;if(items.length===total)return items;}
  throw matchReadError;
}
export function useCreatorSearchSession(api:MatchAPI,activityId:string,active:boolean,pollMs=2500){
  const [scope,setScope]=useState<Scope>({kind:'loading'}),[history,setHistory]=useState<CreatorSearch[]>([]),[historyTotal,setHistoryTotal]=useState(0),[historyCapacity,setHistoryCapacity]=useState(50);
  const [search,setSearch]=useState<CreatorSearch|null>(null),[people,setPeople]=useState<CreatorSearchPerson[]>([]),[results,setResults]=useState<EvaluationResult[]>([]),[candidates,setCandidates]=useState<CandidateView[]>([]);
  const [error,setError]=useState<PublicError|null>(null),[historyError,setHistoryError]=useState<PublicError|null>(null),[loading,setLoading]=useState(false),[current,setCurrent]=useState(false),[epoch,setEpoch]=useState(0);
  const initialized=useRef(false),version=useRef(0);
  const refresh=useCallback(()=>setEpoch(v=>v+1),[]);
  const select=useCallback((id:string|null)=>{version.current++;setScope(id?{kind:'search',id}:{kind:'legacy'});setSearch(null);setResults([]);setPeople([]);setCandidates([]);setCurrent(false);setError(null);},[]);
  useEffect(()=>{if(!active)return;let live=true;
    void (async()=>{try{const pages=await Promise.all(Array.from({length:Math.ceil(historyCapacity/50)},(_,index)=>api.creatorSearches({activityId,offset:index*50,limit:50})));if(!live)return;const failed=pages.find(page=>!page.ok);if(failed&&!failed.ok)throw failed.error;const data=pages.flatMap(page=>page.ok?[page.data]:[]),items=data.flatMap(page=>page.items);if(new Set(items.map(item=>item.id)).size!==items.length)throw matchReadError;setHistory(items);setHistoryTotal(data[0].total);setHistoryError(null);if(!initialized.current){initialized.current=true;setScope(items.length?{kind:'search',id:items[0].id}:{kind:'legacy'});}}catch(cause){if(live){setHistoryError((cause as PublicError)?.code?cause as PublicError:matchReadError);if(!initialized.current){initialized.current=true;setScope({kind:'legacy'});}}}})();
    return()=>{live=false;};
  },[api,activityId,active,epoch,historyCapacity]);
  useEffect(()=>{
    if(!active||scope.kind!=='search')return;let live=true,timer:ReturnType<typeof setTimeout>|undefined;const token=++version.current,id=scope.id;
    const valid=()=>live&&token===version.current;
    async function poll(){setLoading(true);let keepPolling=true;
      try{const response=await api.creatorSearch(id);if(!valid())return;if(!response.ok)throw response.error;const task=response.data;if(task.activity_id!==activityId)throw matchReadError;setSearch(task);setHistory(h=>h.some(s=>s.id===id)?h.map(s=>s.id===id?task:s):[task,...h]);keepPolling=creatorSearchRunning(task);
        if(!keepPolling){const [rows,briefs,members]=await Promise.all([all(offset=>api.creatorSearchPeople({id,offset,limit:100})),task.evaluation_id?all(offset=>api.evaluationResults({id:task.evaluation_id!,offset,limit:100})):Promise.resolve([]),task.query_id?readCandidateMembership(api,task.query_id,{evidence:'all',sort:'added'}):Promise.resolve([])]);if(!valid())return;setPeople(rows);setResults(briefs);setCandidates(members);setCurrent(true);}
        else setCurrent(false);
        setError(null);
      }catch(cause){if(valid()){setCurrent(false);setError((cause as PublicError)?.code?cause as PublicError:matchReadError);}keepPolling=false;}
      finally{if(valid()){setLoading(false);if(keepPolling)timer=setTimeout(()=>void poll(),pollMs);}}
    }
    void poll();return()=>{live=false;version.current++;if(timer)clearTimeout(timer);};
  },[api,activityId,active,scope,epoch,pollMs]);
  return{scope,search,history,historyTotal,historyError,error,loading,current,people,results,candidates,select,refresh,loadOlder:()=>setHistoryCapacity(v=>v+50)};
}
