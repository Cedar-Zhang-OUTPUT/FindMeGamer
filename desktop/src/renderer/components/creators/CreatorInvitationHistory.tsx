import {useCallback,useEffect,useRef,useState} from 'react';
import type {CollaborationAPI,ActivityInvitationPage} from '../../../shared/collaboration';
import type {PublicError} from '../../../shared/bridge';
import {ErrorNotice,Loading} from '../Primitives';
import {CollaborationEditor} from '../match/CollaborationEditor';
const noop=()=>{},readonly=async()=>false;
export function CreatorInvitationHistory({api,creatorId,active}:{api:CollaborationAPI;creatorId:string;active:boolean}){
 const [open,setOpen]=useState(false),[page,setPage]=useState<ActivityInvitationPage|null>(null),[selected,setSelected]=useState<string|null>(null),[offset,setOffset]=useState(0),[loading,setLoading]=useState(false),[error,setError]=useState<PublicError|null>(null);const generation=useRef(0);
 const load=useCallback(async()=>{const token=++generation.current;setLoading(true);setError(null);try{const result=await api.creatorHistory({creatorId,limit:50,offset});if(token!==generation.current)return;if(result.ok)setPage(result.data);else setError(result.error);}catch{if(token===generation.current)setError({code:'network_error',message:'Could not load invitation history.',retryable:true});}finally{if(token===generation.current)setLoading(false);}},[api,creatorId,offset]);
 useEffect(()=>{if(active&&open)void load();return()=>{generation.current++;};},[active,open,load]);
 const row=page?.items.find(item=>item.activity_id+':'+item.selection_id===selected);
 return <details className="creator-disclosure" onToggle={e=>setOpen(e.currentTarget.open)}><summary>Invitation history</summary><div className="creator-disclosure-body">{loading&&<Loading label="Loading invitation history…"/>}{error&&<ErrorNotice error={error} onRetry={()=>void load()}/>}{page?.total===0&&!loading&&<p>No associated activities</p>}<ul className="creator-invitation-history">{page?.items.map(item=>{const key=item.activity_id+':'+item.selection_id;return <li key={key}><button aria-pressed={selected===key} onClick={()=>setSelected(selected===key?null:key)}>{item.activity_name} · {item.invitation_state.replaceAll('_',' ')}</button></li>;})}</ul>{row&&<CollaborationEditor invitation={row} current={active&&open&&!loading&&!error} busy={false} editable={false} onUpdate={readonly} onRespond={readonly} onDirtyChange={noop}/>}{page&&page.total>50&&<div className="button-row"><button disabled={loading||offset===0} onClick={()=>setOffset(Math.max(0,offset-50))}>Previous</button><button disabled={loading||offset+50>=page.total} onClick={()=>setOffset(offset+50)}>Next</button></div>}</div></details>;
}
