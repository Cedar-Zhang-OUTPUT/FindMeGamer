import {useEffect,useState} from 'react';
import type {CreatorAPI,CreatorCreate,CreatorDetail,WorkDetail,ContactDetail} from '../../../shared/creators';
import type {PublicError} from '../../../shared/bridge';
import {ErrorNotice,Loading} from '../Primitives';
import {readNetworkError,type MutationAttempt} from './creatorMutation';

type Candidate={id:string;creatorId:string;title:string;identity:string;historical:boolean};
export function CreatorRecovery({api,attempt,onUse}:{api:CreatorAPI;attempt:MutationAttempt;onUse:(creatorId:string)=>void}) {
  const [page,setPage]=useState<{items:Candidate[];total:number;offset:number;limit:number}|null>(null);
  const [input,setInput]=useState({offset:0,version:0});
  const [error,setError]=useState<PublicError|null>(null);
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    let alive=true;setBusy(true);setError(null);
    async function read(){
      try{
        const command=attempt.command;
        if(command.kind==='creator'){
          const data=command.data as CreatorCreate;
          const response=await api.list({query:Array.from(data.account_id||data.profile_url||data.name||'').slice(0,255).join(''),...(data.platform?{platform:data.platform}:{}),offset:input.offset,limit:24});
          if(!alive)return;if(!response.ok){setError(response.error);return;}
          setPage({...response.data,items:response.data.items.map((item:CreatorDetail)=>({id:item.id,creatorId:item.id,title:item.name||item.public_name||item.source_identity.account_id||'Creator',identity:`${item.platform} · ${item.source_identity.account_id||item.source_identity.canonical_url||item.id}`,historical:false}))});
        }else if(command.kind==='contact'){
          const response=await api.detail(command.creatorId);
          if(!alive)return;if(!response.ok){setError(response.error);return;}
          const items=response.data.contacts.map((item:ContactDetail)=>({id:item.id,creatorId:command.creatorId,title:item.email,identity:`${item.purpose||'Email'} · Identity ${item.identity_revision}`,historical:!item.is_current_identity}));
          setPage({items,total:items.length,offset:0,limit:Math.max(1,items.length)});
        }else if(command.kind==='work'){
          const response=await api.works({creatorId:command.creatorId,includePreviousIdentity:true,offset:input.offset,limit:24});
          if(!alive)return;if(!response.ok){setError(response.error);return;}
          setPage({...response.data,items:response.data.items.map((item:WorkDetail)=>({id:item.id,creatorId:command.creatorId,title:item.work_name||item.content_title||item.source_url||'Work',identity:`${item.source_platform} · Identity ${item.identity_revision}`,historical:!item.is_current_identity}))});
        }
      }catch{if(alive)setError(readNetworkError);}finally{if(alive)setBusy(false);}
    }
    void read();return()=>{alive=false;};
  },[api,attempt,input]);
  return <section className="creator-recovery" aria-label="Check saved records"><h3>Check saved records</h3><p>Choose a record only after checking it. A match alone does not confirm this save.</p>
    {busy&&<Loading label="Checking records…"/>}{error&&<ErrorNotice error={error} onRetry={()=>setInput(value=>({...value,version:value.version+1}))}/>}
    {page&&<><div className="creator-recovery-list">{page.items.map(item=><div key={item.id}><strong>{item.title}</strong><span>{item.identity}{item.historical?' · Previous identity':''}</span><code>{item.id}</code><button className="button secondary" disabled={busy} onClick={()=>onUse(item.creatorId)}>Use this record</button></div>)}</div>{!page.items.length&&<p>No records on this page. The save remains unconfirmed.</p>}
      {page.total>page.limit&&<div className="game-pagination"><span>{page.offset+1}–{page.offset+page.items.length} of {page.total}</span><div className="button-row"><button className="button secondary" disabled={busy||page.offset===0} onClick={()=>setInput({offset:Math.max(0,page.offset-page.limit),version:0})}>Previous records</button><button className="button secondary" disabled={busy||page.offset+page.limit>=page.total} onClick={()=>setInput({offset:page.offset+page.limit,version:0})}>Next records</button></div></div>}</>}
  </section>;
}
