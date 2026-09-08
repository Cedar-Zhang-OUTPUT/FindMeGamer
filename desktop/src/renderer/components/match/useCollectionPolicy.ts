import {useCallback,useEffect,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {CollectionSettings,SettingsAPI} from '../../../shared/settings';
import {matchReadError} from './matchMutation';

type PolicyRead={phase:'loading'|'ready'|'failed';data:CollectionSettings|null;error:PublicError|null};
/** Read-only policy refresh. Never dispatches, resumes, or changes a shared switch. */
export function useCollectionPolicy(api:SettingsAPI,active:boolean){
  const [state,setState]=useState<PolicyRead>({phase:'loading',data:null,error:null});
  const [revision,setRevision]=useState(0);
  const refresh=useCallback(()=>setRevision(value=>value+1),[]);
  useEffect(()=>{
    if(!active)return;
    let current=true,timer:ReturnType<typeof setTimeout>|undefined;
    async function read(background=false){
      if(!background)setState(previous=>({...previous,phase:'loading'}));
      try{
        const result=await api.collection();if(!current)return;
        setState(previous=>result.ok?{phase:'ready',data:result.data,error:null}:{...previous,phase:'failed',error:result.error});
      }catch{if(current)setState(previous=>({...previous,phase:'failed',error:matchReadError}));}
      if(current)timer=setTimeout(()=>void read(true),5000);
    }
    void read();return()=>{current=false;if(timer)clearTimeout(timer);};
  },[api,active,revision]);
  return {...state,refresh};
}
