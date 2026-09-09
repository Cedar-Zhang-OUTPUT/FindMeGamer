import {useEffect,useId,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {CompositionView} from '../../../shared/drafts';
import type {SendBatchPage,SendingAPI} from '../../../shared/sending';
import type {useActivitySending} from './useActivitySending';
import {reviewSendingReadback} from './sendingMutation';
import {QualificationEditor} from './QualificationEditor';
import {DeliveryEditor} from './DeliveryEditor';
import {ErrorNotice,Loading,analyzedDate} from '../Primitives';
import './sendingWorkspace.css';

export function SendingWorkspace({controller:c,composition,active,onRepairDraft,onSettings,onConnectionRepair,onUseCurrentTemplate}:{controller:ReturnType<typeof useActivitySending>;composition:CompositionView|null;active:boolean;onRepairDraft(id:string):void;onSettings?():void;onConnectionRepair?():void;onUseCurrentTemplate?():void}){
  const visible=active&&c.mode.kind!=='drafts',state=c.operation.state,uncertain=state.phase==='uncertain';
  const error=c.error??(c.mode.kind==='review'&&c.qualificationCurrent&&!uncertain?null:state.error);
  const mayReview=uncertain&&!!c.readback&&reviewSendingReadback(state.attempt,c.readback);
  return <section className="sending-workspace" hidden={!visible} aria-label="Sending">
    <header className="sending-workspace-heading"><button type="button" className="text-button" disabled={c.operation.busy||c.locked} onClick={c.backToDrafts}>Back to drafts</button>
      {c.mode.kind==='deliveries'&&<button type="button" className="text-button" disabled={c.busy} onClick={()=>void c.refreshBatch()}>Refresh deliveries</button>}</header>
    {error&&<ErrorNotice error={error} onRetry={!uncertain&&!c.busy?()=>void(c.mode.kind==='review'?c.checkQualification():c.refreshBatch()):undefined}/>}
    {c.loading&&<Loading label={c.mode.kind==='review'?'Checking recipients…':'Loading deliveries…'}/>}
    {state.phase==='running'&&<Loading label={state.attempt.command.kind==='send'?'Submitting emails…':state.attempt.command.kind==='retry'?'Requesting dispatch…':'Recording verification…'}/>}
    {uncertain&&<section className="drafts-recovery" aria-label="Unconfirmed sending request"><strong>{state.attempt.command.kind==='send'?'Submission not confirmed':'Delivery change not confirmed'}</strong>
      <div className="button-row">{c.operation.retryAllowed&&<button type="button" className="button primary" disabled={c.busy||!visible} onClick={()=>void c.retryOriginal()}>Retry same request</button>}
        {state.attempt.command.kind!=='send'&&!state.attempt.connectionChanged&&<button type="button" className="button secondary" disabled={c.busy||!visible} onClick={()=>void c.checkCurrent()}>Check current delivery</button>}
        {state.attempt.connectionChanged&&onConnectionRepair&&<button type="button" className="button secondary" disabled={c.busy||!visible} onClick={onConnectionRepair}>Review connection</button>}
      </div>
      {c.readback&&<div><p>{mayReview?'A newer attempt is available. The earlier change remains unconfirmed.':'The recorded state does not yet settle this request.'}</p>{mayReview&&<button type="button" className="button secondary" disabled={c.busy||!visible} onClick={c.reviewCurrent}>Review current attempt</button>}</div>}
    </section>}
    {composition&&<div hidden={c.mode.kind!=='review'}><QualificationEditor key={composition.id} composition={composition} qualification={c.qualification} exclusions={c.exclusions}
      current={visible&&c.mode.kind==='review'&&c.qualificationCurrent} busy={c.busy||c.locked||!visible||c.mode.kind!=='review'} onExclusionsChange={c.changeExclusions}
      onCheck={()=>void c.checkQualification()} onSend={()=>void c.send()} onRepairDraft={onRepairDraft} onOpenSettings={onSettings} onUseCurrentTemplate={onUseCurrentTemplate}/></div>}
    {c.batch&&<div hidden={c.mode.kind!=='deliveries'}><DeliveryEditor key={`${c.batch.id}:${c.verificationEpoch}`} batch={c.batch} current={visible&&c.mode.kind==='deliveries'&&c.current}
      busy={c.busy||c.locked||!visible||c.mode.kind!=='deliveries'} onRetry={c.retryDelivery} onResolve={c.resolveDelivery} onDirtyChange={c.setVerificationDirty}/></div>}
  </section>;
}

const historyError:PublicError={code:'sending_history_read_failed',message:'Could not load sending history. Try again.',retryable:true};
export function SendBatchHistory({api,activityId,active,epoch,disabled,onOpen}:{api:SendingAPI;activityId:string;active:boolean;epoch:number;disabled:boolean;onOpen(id:string):void}){
  const id=useId(),[expanded,setExpanded]=useState(false),[offset,setOffset]=useState(0),[refresh,setRefresh]=useState(0);
  const [loading,setLoading]=useState(false),[error,setError]=useState<PublicError|null>(null),[record,setRecord]=useState<{activityId:string;epoch:number;offset:number;page:SendBatchPage}|null>(null);
  useEffect(()=>{setOffset(0);},[activityId,epoch]);
  useEffect(()=>{
    let live=true;setRecord(null);setError(null);if(!expanded||!active||disabled){setLoading(false);return;}setLoading(true);
    void api.batches({activityId,offset,limit:50}).then(result=>{
      if(!live)return;if(!result.ok){setError(result.error);return;}const page=result.data;
      if(page.offset!==offset||page.limit!==50||page.items.length>50||page.items.some(item=>item.activity_id!==activityId)||new Set(page.items.map(item=>item.id)).size!==page.items.length){setError(historyError);return;}
      setRecord({activityId,epoch,offset,page});
    }).catch(()=>{if(live)setError(historyError);}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};
  },[api,activityId,active,epoch,disabled,expanded,offset,refresh]);
  const page=record?.activityId===activityId&&record.epoch===epoch&&record.offset===offset?record.page:null,available=active&&!disabled&&!loading&&!!page;
  return <section className="drafts-history" aria-label="Sending history"><button type="button" className="drafts-history-toggle" aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(value=>!value)}>Sending history</button>
    <div id={id} hidden={!expanded}>{loading&&<Loading label="Loading sending history…"/>}{error&&<ErrorNotice error={error} onRetry={active&&!disabled?()=>setRefresh(value=>value+1):undefined}/>}
      {page&&<><ul>{page.items.map(item=><li key={item.id}><div><strong>{item.deliveries.length} emails</strong><span>{analyzedDate(item.created_at)} · {item.qualification.excluded_count} excluded</span></div>
        <button type="button" className="button secondary" disabled={!available} onClick={()=>{if(available){setExpanded(false);onOpen(item.id);}}}>View deliveries</button></li>)}</ul>
        {!page.items.length&&<p className="muted">No sent batches yet.</p>}<footer><span>{page.total} batches</span><div className="button-row">
          <button type="button" disabled={!available||offset===0} onClick={()=>setOffset(value=>Math.max(0,value-50))}>Previous sending batches</button>
          <button type="button" disabled={!available||offset+50>=page.total} onClick={()=>setOffset(value=>value+50)}>Next sending batches</button></div></footer></>}
    </div></section>;
}
