import {useCallback,useEffect,useState} from 'react';
import type {DraftsAPI,TemplateVersion} from '../../../shared/drafts';
import type {PublicError} from '../../../shared/bridge';

type PreviewState={id:string;template:TemplateVersion|null;loading:boolean;error:PublicError|null};
const unavailable:PublicError={code:'template_read_failed',message:'Could not load the original template.',retryable:true};
/** Read-only presentation data. Never controls composition validity or sending eligibility. */
export function useDraftTemplatePreview(api:Pick<DraftsAPI,'template'>,id:string|null,active:boolean,cached?:TemplateVersion){
  const [state,setState]=useState<PreviewState|null>(null),[epoch,setEpoch]=useState(0);
  const exact=cached?.id===id?cached:undefined;
  const reload=useCallback(()=>setEpoch(value=>value+1),[]);
  useEffect(()=>{
    if(!active||!id||exact)return;
    let live=true;setState({id,template:null,loading:true,error:null});
    void (async()=>{
      try{
        const result=await api.template(id);if(!live)return;
        if(!result.ok)throw result.error;
        if(result.data.id!==id)throw {code:'invalid_response',message:'The returned template does not match this draft version.',retryable:false};
        setState({id,template:result.data,loading:false,error:null});
      }catch(cause){if(live){const error=cause&&typeof cause==='object'&&'code'in cause&&typeof cause.code==='string'&&'message'in cause&&typeof cause.message==='string'&&'retryable'in cause&&typeof cause.retryable==='boolean'?cause as PublicError:unavailable;setState({id,template:null,loading:false,error});}}
    })();
    return()=>{live=false;};
  },[api,id,active,exact,epoch]);
  const owned=state?.id===id?state:null;
  return {template:exact??owned?.template??null,error:exact?null:owned?.error??null,loading:active&&!!id&&!exact&&(owned?.loading??true),reload};
}
