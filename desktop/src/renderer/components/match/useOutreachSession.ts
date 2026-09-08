import {useCallback,useEffect,useRef,useState} from 'react';
import type {OutreachAPI,Preparation} from '../../../shared/outreach';
import type {PublicError} from '../../../shared/bridge';
const changed:PublicError={code:'selections_changed',message:'The selected list changed while loading. Reload selected people.',retryable:true};
export const preparationReadError:PublicError={code:'network_error',message:'Could not load selected people. Retry to use the current list.',retryable:true};
export function outreachReadError(value:unknown):PublicError{
  if(value&&typeof value==='object'&&'code' in value&&'message' in value&&'retryable' in value&&typeof value.code==='string'&&typeof value.message==='string'&&typeof value.retryable==='boolean')return value as PublicError;
  return preparationReadError;
}
export async function readSelections(api:Pick<OutreachAPI,'selections'>,activityId:string,includeCancelled=false):Promise<Preparation[]>{
  const items:Preparation[]=[],ids=new Set<string>();let total:number|undefined;
  for(let offset=0;offset<10_000;offset+=200){
    const result=await api.selections({activityId,includeCancelled,offset,limit:200});if(!result.ok)throw result.error;
    const page=result.data;
    if(page.total>10_000)throw {code:'selection_list_too_large',message:'This activity has more than 10,000 selections. Open a smaller activity to prepare a batch.',retryable:false};
    if(page.offset!==offset||total!==undefined&&total!==page.total||page.items.length!==Math.min(200,Math.max(0,page.total-offset)))throw changed;
    total=page.total;
    for(const item of page.items){if(ids.has(item.id)||item.activity_id!==activityId||!includeCancelled&&!item.active)throw changed;ids.add(item.id);items.push(item);}
    if(items.length===total)return items;
  }
  throw changed;
}
export function useOutreachSession(api:Pick<OutreachAPI,'selections'>,activityId:string,active:boolean){
  const [items,setItems]=useState<Preparation[]>([]),[current,setCurrent]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState<PublicError|null>(null);
  const version=useRef(0),alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;version.current++;};},[]);
  const refresh=useCallback(async():Promise<Preparation[]|null>=>{
    const token=++version.current;setLoading(true);setCurrent(false);setError(null);
    try{
      const next=await readSelections({selections:api.selections},activityId);
      if(!alive.current||token!==version.current)return null;
      setItems(next);setCurrent(true);return next;
    }catch(cause){if(alive.current&&token===version.current)setError(outreachReadError(cause));return null;}
    finally{if(alive.current&&token===version.current)setLoading(false);}
  },[api.selections,activityId]);
  useEffect(()=>{if(active)void refresh();return()=>{version.current++;setLoading(false);setCurrent(false);};},[active,refresh]);
  // Fence old reads/actions without unmounting a person's unsaved local editor.
  const credentialsChanged=useCallback(()=>{version.current++;setCurrent(false);setLoading(false);},[]);
  const acceptReceipt=useCallback((person:Preparation)=>{if(person.activity_id!==activityId)return;setItems(previous=>person.active?previous.some(item=>item.id===person.id)?previous.map(item=>item.id===person.id?person:item):[...previous,person]:previous.filter(item=>item.id!==person.id));},[activityId]);
  return {items,current,loading,error,refresh,credentialsChanged,acceptReceipt};
}
