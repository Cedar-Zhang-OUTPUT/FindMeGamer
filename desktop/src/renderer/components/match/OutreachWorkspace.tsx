import {useCallback,useEffect,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {Preparation,RecipientBatchPage} from '../../../shared/outreach';
import {ErrorNotice,Loading} from '../Primitives';
import {PreparationEditor,PreparationSnapshot} from './PreparationEditor';
import {MatchOperationNotice} from './MatchOperationNotice';
import {outreachReadError} from './useOutreachSession';
import {taskDate} from './matchStatus';
import type {useActivityOutreach} from './useActivityOutreach';
import './outreachWorkspace.css';
type Controller=ReturnType<typeof useActivityOutreach>;
const nameOf=(person:Preparation)=>person.name||person.public_name||person.identity.account_id;
export function PreparationHistory({api,activityId,active,epoch,disabled,onOpen}:{api:DesktopBridge['outreach'];activityId:string;active:boolean;epoch:number;disabled:boolean;onOpen:(id:string)=>void}){
  const [expanded,setExpanded]=useState(false),[page,setPage]=useState<RecipientBatchPage|null>(null),[error,setError]=useState<PublicError|null>(null),[loading,setLoading]=useState(false);
  const generation=useRef(0),offset=useRef(0);
  const load=useCallback(async(next:number)=>{
    const token=++generation.current;offset.current=next;setLoading(true);setError(null);
    try{const result=await api.batches({activityId,offset:next,limit:50});if(token!==generation.current)return;if(!result.ok)throw result.error;setPage(result.data);}
    catch(cause){if(token===generation.current)setError(outreachReadError(cause));}
    finally{if(token===generation.current)setLoading(false);}
  },[api,activityId]);
  useEffect(()=>{if(expanded&&active)void load(offset.current);return()=>{generation.current++;};},[expanded,active,epoch,load]);
  return <details className="outreach-history" open={expanded} onToggle={event=>setExpanded(event.currentTarget.open)}><summary>Preparation history</summary>
    {loading&&<Loading label="Loading preparations…"/>}{page&&<><ul>{page.items.map(item=><li key={item.id}><button className="text-button" disabled={disabled||loading} aria-label={`Open preparation · ${item.recipient_count} people · ${taskDate(item.created_at)}`} onClick={()=>onOpen(item.id)}><strong>{item.recipient_count} people</strong><span>{taskDate(item.created_at)}</span></button></li>)}</ul>{page.total===0&&<p className="muted">No preparations yet</p>}<div className="button-row"><button className="text-button" disabled={loading||page.offset===0} onClick={()=>void load(Math.max(0,page.offset-50))}>Previous preparations</button><button className="text-button" disabled={loading||page.offset+page.items.length>=page.total} onClick={()=>void load(page.offset+50)}>Next preparations</button></div></>}
    {error&&<ErrorNotice error={error} onRetry={()=>void load(offset.current)}/>}
  </details>;
}
function PersonStatus({person}:{person:Preparation}){
  return <div className="outreach-person-status"><span className={person.contact_status==='eligible'?'ready':'needs'}>{person.contact_status==='eligible'?person.selected_contact?.email:person.contact_status==='not_selected'?'No email':`Email ${person.contact_status}`}</span>{!person.public_name_confirmed&&<span className="needs">Confirm name</span>}{!person.works.length&&!person.evaluation&&<span className="needs">No evidence</span>}{person.identity_changed&&<span className="needs">Account changed</span>}{!person.active&&<span className="needs">Selection removed</span>}</div>;
}
export function OutreachNotice({controller:c,onRepair}:{controller:Controller;onRepair?:()=>void}){
  const {state}=c.operation;
  return <div className="outreach-feedback">
    {c.notice&&<p role="status">{c.notice}</p>}
    {state.phase==='running'&&<Loading label={state.attempt.command.kind==='freeze'?`Preparing ${c.pendingCount} people…`:'Saving selection…'}/>}
    {state.phase==='uncertain'&&<section className="match-uncertain" aria-label="Unconfirmed outreach request"><h3>Save not confirmed</h3><p>{state.attempt.connectionChanged?'Check the original workspace before retrying.':!c.operation.retryAllowed?'The retry window ended. Check the saved people.':'The request may already be saved.'}</p><div className="button-row"><button className="button primary" disabled={!c.operation.retryAllowed||c.busy} onClick={()=>void c.retry()}>Retry same save</button><button className="button secondary" disabled={c.busy} onClick={()=>void c.reconcile()}>Check saved people</button></div></section>}
    {state.error&&<ErrorNotice error={state.error}/>}{c.problem&&<ErrorNotice error={c.problem} onRetry={c.problem.retryable?()=>void c.refresh():undefined}/>}
    <MatchOperationNotice operation={c.stopOperation} onRetry={()=>void c.retryStop()} onCheck={()=>void c.checkStop()} onRepair={onRepair}/>
    {c.pendingCount>0&&!c.busy&&!c.locked&&(c.stopOperation.state.error||c.operation.state.error)&&<div className="button-row">{c.stopOperation.state.error&&<button className="button secondary" disabled={!c.stopOperation.retryRejectedAllowed} onClick={()=>void c.retryStop()}>Retry stop and prepare {c.pendingCount}</button>}<button className="text-button" onClick={c.cancelPending}>Cancel preparation</button></div>}
    {onRepair&&state.error&&<button className="text-button" onClick={onRepair}>Open Settings</button>}
  </div>;
}
export function OutreachWorkspace({api,controller:c,active,onRequest,onOpenCreator,onChooseTemplate,evaluationChoices=[]}:{api:DesktopBridge;controller:Controller;active:boolean;onRequest:(action:()=>void)=>void;onOpenCreator:(id:string,section?:'overview'|'contacts'|'works')=>void;onChooseTemplate?:()=>void;evaluationChoices?:Array<{id:string;label:string}>}){
  const selected=c.panel==='selected',history=c.batchMode==='history';
  const people=selected?c.session.items:c.batch?.recipients.map(item=>history?item.snapshot:item.preparation)??[];
  const currentPerson=people.find(item=>item.id===c.selectedId),retainedPerson=useRef<Preparation|null>(null);
  if(currentPerson)retainedPerson.current=currentPerson;
  const person=currentPerson??(c.dirty&&retainedPerson.current?.id===c.selectedId?retainedPerson.current:undefined);
  const frozen=c.batch?.recipients.find(item=>item.selection_id===c.selectedId);
  const disabled=c.busy||c.locked||!(selected?c.session.current:c.batchCurrent);
  const chosen=c.chosenIds.filter(id=>people.some(p=>p.id===id));
  return <section className="outreach-workspace" aria-label={selected?'Selected people':'Outreach preparation'}>
    <header className="outreach-heading"><button className="text-button" onClick={()=>onRequest(()=>{c.setPanel('candidates');c.setSelectedId(null);})}>Back to candidates</button><div><h2>{selected?`Selected · ${people.length}`:`Preparation · ${c.batch?.recipient_count??0}`}</h2>{!selected&&<span className="status-badge">{history?'History · read only':'Not ready to send'}</span>}</div>
      {selected&&<div className="outreach-prepare-action"><button className="button primary" disabled={disabled||c.dirty||!chosen.length||chosen.length>600} onClick={()=>void c.prepare(chosen)}>Prepare {chosen.length}</button><span>Stops discovery · no email sent</span></div>}
      {!selected&&!history&&onChooseTemplate&&<button className="button primary" disabled={disabled||c.dirty||!people.length} onClick={onChooseTemplate}>Choose template</button>}
    </header>
    {selected&&c.session.error&&<ErrorNotice error={c.session.error} onRetry={()=>void c.refresh()}/>}
    {selected&&c.session.loading&&<Loading label="Loading selected people…"/>}
    {!people.length&&!c.session.loading&&<div className="outreach-empty"><h3>No people selected</h3><button className="button primary" onClick={()=>onRequest(()=>{c.setPanel('candidates');c.setSelectedId(null);})}>Choose creators</button></div>}
    <div className={`outreach-columns ${person?'has-detail':''}`}>
      <div className="outreach-roster">{selected&&people.length>0&&<div className="outreach-roster-tools"><button className="text-button" disabled={disabled||people.length>600} onClick={()=>c.setChosenIds(people.map(p=>p.id))}>Include all</button><button className="text-button" disabled={disabled} onClick={()=>c.setChosenIds([])}>Clear</button>{people.length>600&&<span>Choose up to 600</span>}</div>}
        <ul aria-label={selected?'Selected creators':'Prepared creators'}>{people.map(item=><li key={item.id} className={person?.id===item.id?'current':''}>
          {selected&&<input type="checkbox" aria-label={`Include ${nameOf(item)} in preparation`} checked={chosen.includes(item.id)} disabled={disabled||!chosen.includes(item.id)&&chosen.length>=600} onChange={()=>c.setChosenIds(chosen.includes(item.id)?chosen.filter(id=>id!==item.id):[...chosen,item.id])}/>}
          <button className="outreach-person" aria-label={`${history?'View':'Edit'} ${nameOf(item)}`} aria-pressed={person?.id===item.id} onClick={()=>onRequest(()=>c.setSelectedId(item.id))}><strong>{nameOf(item)}</strong><span className="muted">{item.identity.platform==='youtube'?'YouTube':item.identity.platform==='x'?'X':item.identity.platform} · {item.identity.account_id}</span><PersonStatus person={item}/></button>
          {selected&&<button className="text-button" disabled={disabled} aria-label={`Remove ${nameOf(item)} from outreach`} onClick={()=>onRequest(()=>void c.remove(item))}>Remove</button>}
        </li>)}</ul>
      </div>
      {person?<div className="outreach-detail"><button className="text-button" onClick={()=>onRequest(()=>c.setSelectedId(null))}>Close details</button>{history?<><h3>Original snapshot</h3><PreparationSnapshot preparation={person}/></>:<>{!currentPerson&&<p role="status">Selection no longer active. Your unsaved changes are still here.</p>}<PreparationEditor key={person.id} preparation={person} creators={api.creators} active={active} busy={c.busy||c.locked||selected&&c.session.loading} current={Boolean(currentPerson)&&(selected?c.session.current:c.batchCurrent)} evaluationChoices={evaluationChoices} onSave={data=>c.updatePerson(person.id,data)} onOpenCreator={onOpenCreator} onOpenExternal={url=>{void api.openExternal(url);}} onRefresh={()=>void c.refresh()} onDirtyChange={c.setDirty}/>{frozen&&<details className="match-context"><summary>Original snapshot</summary><PreparationSnapshot preparation={frozen.snapshot}/></details>}</>}</div>:!selected&&history?<div className="outreach-detail"><h3>Original snapshot</h3><span className="muted">{c.batch?.recipient_count} people · {c.batch?taskDate(c.batch.created_at):''}</span></div>:null}
    </div>
  </section>;
}
