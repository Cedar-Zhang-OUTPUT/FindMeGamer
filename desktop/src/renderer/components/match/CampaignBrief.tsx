import {useEffect,useRef,useState} from 'react';
import type {ActivityView,MatchAPI} from '../../../shared/match';
import type {PublicError} from '../../../shared/bridge';
import {ErrorNotice} from '../Primitives';
export type BriefGuardState={dirty:boolean;busy:boolean;locked:boolean};
type Edit={text:string;revision:number};
type State={kind:'view'}|({kind:'edit';error?:PublicError}&Edit)|({kind:'saving'|'unconfirmed'|'checking';error?:PublicError}&Edit)|({kind:'review';latest:ActivityView}&Edit);
type Props={api:Pick<MatchAPI,'updateBrief'|'activity'>;activity:ActivityView;discardToken:number;onStateChange:(state:BriefGuardState)=>void;onSaved:()=>void};
const unknown:PublicError={code:'brief_save_unconfirmed',message:'Save not confirmed. Check the latest brief before continuing.',retryable:false};
const readError:PublicError={code:'brief_read_failed',message:'Could not load the latest brief. Try again.',retryable:true};
export function CampaignBrief({api,activity,discardToken,onStateChange,onSaved}:Props){
 const [state,setState]=useState<State>({kind:'view'}),[saved,setSaved]=useState<ActivityView|null>(null);
 const generation=useRef(0),discard=useRef(discardToken),pending=useRef(false);
 const current=saved&&(saved.revision??-1)>=(activity.revision??-1)?saved:activity;
 const busy=state.kind==='saving'||state.kind==='checking',locked=['saving','unconfirmed','checking','review'].includes(state.kind);
 useEffect(()=>{onStateChange({dirty:state.kind!=='view',busy,locked});},[state.kind,busy,locked,onStateChange]);
 useEffect(()=>()=>{generation.current++;},[]);
 useEffect(()=>{if(discard.current!==discardToken){discard.current=discardToken;generation.current++;setState({kind:'view'});}},[discardToken]);
 function accept(value:ActivityView){setSaved(value);setState({kind:'view'});onSaved();}
 async function save(){
  if(state.kind!=='edit'||pending.current||state.text.length>5000)return;
  const edit={text:state.text,revision:state.revision},token=++generation.current;pending.current=true;setState({kind:'saving',...edit});
  try{
   const result=await api.updateBrief({id:activity.id,data:{campaign_brief:edit.text.trim()||null,expected_revision:edit.revision}});if(token!==generation.current)return;
   if(result.ok&&result.data.id===activity.id&&result.data.revision===edit.revision+1&&(result.data.campaign_brief??'')===edit.text.trim()){accept(result.data);return;}
   if(!result.ok&&['request_invalid','workspace_key_invalid','access_denied'].includes(result.error.code))setState({kind:'edit',...edit,error:result.error});
   else setState({kind:'unconfirmed',...edit,error:unknown});
  }catch{if(token===generation.current)setState({kind:'unconfirmed',...edit,error:unknown});}
  finally{pending.current=false;}
 }
 async function check(){
  if(state.kind!=='unconfirmed'||pending.current)return;
  const edit={text:state.text,revision:state.revision},token=++generation.current;pending.current=true;setState({kind:'checking',...edit});
  try{
   const result=await api.activity(activity.id);if(token!==generation.current)return;
   if(!result.ok||result.data.id!==activity.id||typeof result.data.revision!=='number'){setState({kind:'unconfirmed',...edit,error:result.ok?readError:result.error});return;}
   if((result.data.campaign_brief??'')===(edit.text.trim()))accept(result.data);
   else setState({kind:'review',...edit,latest:result.data});
  }catch{if(token===generation.current)setState({kind:'unconfirmed',...edit,error:readError});}finally{pending.current=false;}
 }
 if(state.kind==='view')return <section className="campaign-brief" aria-label="Campaign brief"><div className="button-row"><strong>Campaign brief</strong><button className="text-button" disabled={typeof current.revision!=='number'} title={typeof current.revision!=='number'?'Service update required':undefined} onClick={()=>setState({kind:'edit',text:current.campaign_brief??'',revision:current.revision!})}>{current.campaign_brief?'Edit campaign brief':'Add campaign brief'}</button></div>{current.campaign_brief&&<p className="campaign-brief-summary">{current.campaign_brief}</p>}</section>;
 return <section className="campaign-brief" aria-label="Campaign brief">
  {state.kind==='review'?<><h3>Review latest brief</h3><dl><dt>Saved on server</dt><dd>{state.latest.campaign_brief||'Empty'}</dd><dt>Your text</dt><dd>{state.text||'Empty'}</dd></dl><div className="button-row"><button className="button secondary" onClick={()=>accept(state.latest)}>Use latest brief</button><button className="button primary" onClick={()=>setState({kind:'edit',text:state.text,revision:state.latest.revision!})}>Continue editing my brief</button></div></>:<>
   <label htmlFor="campaign-brief">Campaign brief</label><textarea id="campaign-brief" rows={3} maxLength={5000} value={state.text} disabled={state.kind!=='edit'} onChange={event=>{if(state.kind==='edit')setState({...state,text:event.target.value,error:undefined});}}/>
   <p className="muted">Applies to new searches; existing results retain their original brief.</p>
   {state.error&&<ErrorNotice error={state.error}/>}
   <div className="button-row">{state.kind==='edit'?<><button className="text-button" onClick={()=>setState({kind:'view'})}>Cancel brief</button><button className="button primary" disabled={state.text.length>5000} onClick={()=>void save()}>Save brief</button></>:<button className="button secondary" disabled={busy} onClick={()=>void check()}>{state.kind==='saving'?'Saving brief…':busy?'Checking brief…':'Check latest brief'}</button>}</div>
  </>}
 </section>;
}
