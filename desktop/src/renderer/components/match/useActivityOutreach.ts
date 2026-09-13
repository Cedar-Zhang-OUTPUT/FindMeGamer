import {useCallback,useEffect,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {CandidateQueryOptions,CandidateView} from '../../../shared/match';
import type {Preparation,RecipientBatchDetail,RecipientChoice,SelectionUpdate} from '../../../shared/outreach';
import {outreachReadError,readSelections,useOutreachSession} from './useOutreachSession';
import {candidateSelection,excludedSelections,readCandidateMembership,visibleSelections} from './outreachProjection';
import {useOutreachOperation} from './useOutreachOperation';
import {useMatchOperation} from './useMatchOperation';
import type {OutreachCommand,OutreachReceipt} from './outreachMutation';
import {useLocalSelection} from './useLocalSelection';
type Props={api:Pick<DesktopBridge,'outreach'|'match'|'localSelections'>;activityId:string;active:boolean;initialized?:boolean;queryId:string|null;candidates:CandidateView[];candidateCurrent:boolean;options:Required<CandidateQueryOptions>;onOptions:(next:Required<CandidateQueryOptions>)=>void;blocked:boolean;onPrepared?:(batch:RecipientBatchDetail)=>void};
type PendingFreeze={queryId:string;recipients:RecipientChoice[]};
type AfterWrite={kind:'ordinary'}|{kind:'filter';apply:()=>void;count:number};
const unavailable:PublicError={code:'preparation_unavailable',message:'Reload the current people and search before continuing.',retryable:true};
export function useActivityOutreach({api,activityId,active,initialized,queryId,candidates,candidateCurrent,options,onOptions,blocked,onPrepared}:Props){
  const session=useOutreachSession(api.outreach,activityId,active,initialized),operation=useOutreachOperation(api.outreach),stopOperation=useMatchOperation(api.match);
  const local=useLocalSelection(api,activityId,queryId,session.items,session.current);
  const [panel,setPanel]=useState<'candidates'|'selected'|'batch'>('candidates'),[selectedId,setSelectedId]=useState<string|null>(null);
  const [batchMode,setBatchMode]=useState<'current'|'history'>('current');
  const [batch,setBatch]=useState<RecipientBatchDetail|null>(null),[batchCurrent,setBatchCurrent]=useState(false),[notice,setNotice]=useState('');
  const [processing,setProcessing]=useState(false),[readBusy,setReadBusy]=useState(false),[problem,setProblem]=useState<PublicError|null>(null),[dirty,setDirty]=useState(false);
  const [chosenIds,setChosenIds]=useState<string[]>([]),[historyEpoch,setHistoryEpoch]=useState(0),[pendingCount,setPendingCount]=useState(0);
  const pendingFreeze=useRef<PendingFreeze|null>(null),afterWrite=useRef<AfterWrite>({kind:'ordinary'}),version=useRef(0),alive=useRef(true),actionPending=useRef(false);
  const batchRef=useRef(batch),wasActive=useRef(active);batchRef.current=batch;
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;version.current++;};},[]);
  const busy=processing||readBusy||operation.busy||stopOperation.busy||local.busy,locked=operation.locked||stopOperation.locked||local.locked;
  const unavailableNow=blocked||busy||locked;
  const loadBatch=useCallback(async(id:string)=>{
    const token=++version.current;setReadBusy(true);setBatchCurrent(false);setProblem(null);
    try{const result=await api.outreach.batch({activityId,id});if(!alive.current||token!==version.current)return null;if(!result.ok)throw result.error;
      if(result.data.activity_id!==activityId||result.data.id!==id)throw unavailable;
      setBatch(result.data);setBatchCurrent(true);return result.data;
    }catch(error){if(alive.current&&token===version.current)setProblem(outreachReadError(error));return null;}
    finally{if(alive.current&&token===version.current)setReadBusy(false);}
  },[api.outreach,activityId]);
  useEffect(()=>{
    const returning=active&&!wasActive.current;wasActive.current=active;
    // Opening/freezing already supplies a current batch; only a detour return needs another read.
    if(returning&&panel==='batch'&&batch?.id)void loadBatch(batch.id);
  },[active,panel,batch?.id,loadBatch]);
  const credentialsChanged=useCallback(()=>{version.current++;local.credentialsChanged();session.credentialsChanged();operation.credentialsChanged();stopOperation.credentialsChanged();setBatchCurrent(false);setReadBusy(false);setProcessing(false);},[local.credentialsChanged,session.credentialsChanged,operation.credentialsChanged,stopOperation.credentialsChanged]);
  async function refresh(){await session.refresh();if(batchRef.current)await loadBatch(batchRef.current.id);}
  async function complete(receipt:OutreachReceipt|null):Promise<boolean>{
    if(!receipt)return false;
    if(receipt.kind==='freeze'){
      setBatch(receipt.data);setBatchCurrent(true);setBatchMode('current');setPanel('batch');setSelectedId(null);setHistoryEpoch(n=>n+1);pendingFreeze.current=null;setPendingCount(0);setNotice('Preparation saved');
      onPrepared?.(receipt.data);
    }else{
      if(receipt.kind==='bulk'&&afterWrite.current.kind==='filter'){afterWrite.current.apply();setNotice(`${afterWrite.current.count} removed from selection`);}
      if(receipt.kind==='update')setNotice('Changes saved');
      if(receipt.kind==='cancel')setSelectedId(id=>id===receipt.data.id?null:id);
      if(receipt.kind!=='bulk'){
        session.acceptReceipt(receipt.data);
        const person=receipt.data;
        setBatch(previous=>previous?{...previous,recipients:previous.recipients.map(item=>item.selection_id===person.id?{...item,preparation:person,current_missing_fields:person.missing_fields}:item)}:null);
      }
      await session.refresh();if(batchRef.current)await loadBatch(batchRef.current.id);
    }
    afterWrite.current={kind:'ordinary'};return true;
  }
  async function mutate(command:OutreachCommand){setProblem(null);return complete(await operation.execute(command));}
  async function toggle(candidate:CandidateView,current=candidateCurrent){
    if(local.enabled){if(!unavailableNow&&local.ready&&current&&!candidate.identity_changed)local.toggle(candidate);return;}
    if(unavailableNow||actionPending.current||!session.current||!current||candidate.identity_changed)return;
    afterWrite.current={kind:'ordinary'};const selected=candidateSelection(candidate,session.items);
    await mutate(selected?{kind:'cancel',activityId,id:selected.id,data:{expected_revision:selected.revision}}:{kind:'add',activityId,data:{candidate_id:candidate.id}});
  }
  async function selectLoaded(loaded:CandidateView[]=candidates,current=candidateCurrent){
    if(local.enabled){if(!unavailableNow&&local.ready&&current)local.setLoaded(loaded,true);return;}
    if(unavailableNow||actionPending.current||!session.current||!current)return;
    const ids=loaded.filter(item=>!item.identity_changed&&!candidateSelection(item,session.items)).map(item=>item.id);
    if(!ids.length)return;if(ids.length>600){setProblem({code:'selection_limit',message:'Choose up to 600 people at a time.',retryable:false});return;}
    afterWrite.current={kind:'ordinary'};await mutate({kind:'bulk',activityId,data:{add_candidate_ids:ids}});
  }
  async function changeOptions(next:Required<CandidateQueryOptions>){
    return changeProjection({next,previous:options,visible:candidates,current:candidateCurrent,read:()=>queryId?readCandidateMembership(api.match,queryId,next):Promise.reject(unavailable),apply:()=>onOptions(next)});
  }
  async function deselectLoaded(loaded:CandidateView[]=candidates,current=candidateCurrent){
    if(unavailableNow||actionPending.current||!current)return;
    if(local.enabled){if(local.ready)local.setLoaded(loaded,false);return;}
    if(!session.current)return;
    const selected=[...new Map(loaded.filter(item=>!item.identity_changed).flatMap(item=>{const row=candidateSelection(item,session.items);return row?[[row.id,row] as const]:[];})).values()];
    if(selected.length){afterWrite.current={kind:'ordinary'};await mutate({kind:'bulk',activityId,data:{add_candidate_ids:[],cancel_selections:selected.map(row=>({selection_id:row.id,expected_revision:row.revision}))}});}
  }
  async function changeProjection({next,previous,visible,current,read,apply}:{next:Required<CandidateQueryOptions>;previous:Required<CandidateQueryOptions>;visible:CandidateView[];current:boolean;read:()=>Promise<CandidateView[]>;apply:()=>void}){
    if(unavailableNow||actionPending.current)return;
    if(local.enabled){apply();return;}
    if(next.evidence===previous.evidence){apply();return;}
    if(!session.current||!current){setProblem(unavailable);return;}
    const projection=visibleSelections(visible,session.items);
    if(!projection.length){apply();return;}
    const token=version.current;actionPending.current=true;setProcessing(true);setProblem(null);
    try{
      const matching=await read();if(!alive.current||token!==version.current)return;
      const removals=excludedSelections(projection,matching);
      if(!removals.length){apply();return;}
      afterWrite.current={kind:'filter',apply,count:removals.length};await mutate({kind:'bulk',activityId,data:{cancel_selections:removals}});
    }catch(error){if(alive.current&&token===version.current)setProblem(outreachReadError(error));}
    finally{actionPending.current=false;if(alive.current)setProcessing(false);}
  }
  function openSelected(){setPanel('selected');setSelectedId(null);setChosenIds(session.items.length<=600?session.items.map(p=>p.id):[]);}
  async function openBatch(id:string){const value=await loadBatch(id);if(value){setBatchMode('history');setPanel('batch');setSelectedId(null);}}
  async function openCurrentBatch(id:string,personId:string){const value=await loadBatch(id);if(!value)return false;setBatchMode('current');setPanel('batch');setSelectedId(value.recipients.some(row=>row.selection_id===personId)?personId:null);return true;}
  async function updatePerson(id:string,data:SelectionUpdate){
    if(unavailableNow)return false;afterWrite.current={kind:'ordinary'};
    const person=(panel==='batch'?batch?.recipients.map(item=>item.preparation):session.items)?.find(item=>item.id===id);
    const observedContact=person?.revision===data.expected_revision&&person.context_token===data.context_token&&typeof data.contact_id==='string'
      ?person.contact_options.find(contact=>contact.id===data.contact_id&&contact.status==='eligible'):undefined;
    return mutate({kind:'update',activityId,id,data,...(observedContact?{observedContact}:{} )});
  }
  async function remove(person:Preparation){if(unavailableNow||!session.current)return;if(local.enabled){const member=local.state?.draft.members[person.candidate_id];if(member)local.change(member,false);return;}afterWrite.current={kind:'ordinary'};await mutate({kind:'cancel',activityId,id:person.id,data:{expected_revision:person.revision}});}
  async function freezePending(){
    const pending=pendingFreeze.current;if(!pending)return;
    await mutate({kind:'freeze',activityId,data:{recipients:pending.recipients}});
  }
  async function submitStop(retry=false){
    const pending=pendingFreeze.current;if(!pending)return;
    const receipt=await (retry?stopOperation.state.phase==='idle'?stopOperation.retryRejected():stopOperation.retry():stopOperation.execute({kind:'stop',queryId:pending.queryId}));
    if(receipt&&'stop_requested' in receipt.data&&receipt.data.stop_requested&&receipt.data.query_id===pending.queryId)await freezePending();
  }
  async function prepare(ids:string[]){
    if(local.enabled){if(blocked||dirty||processing||readBusy||operation.busy||operation.locked||stopOperation.busy||stopOperation.locked)return;const receipt=await local.prepare();if(receipt)await complete({kind:'freeze',data:receipt});return;}
    if(unavailableNow||actionPending.current||dirty)return;
    if(!session.current||!queryId||ids.length<1||ids.length>600||new Set(ids).size!==ids.length){setProblem(unavailable);return;}
    const byId=new Map(session.items.map(p=>[p.id,p]));
    const selected=ids.map(id=>byId.get(id));if(selected.some(p=>!p?.active||!p.freeze_ready)){setProblem(unavailable);return;}
    const recipients=selected.map(p=>({selection_id:p!.id,expected_revision:p!.revision,context_token:p!.context_token}));
    pendingFreeze.current=Object.freeze({queryId,recipients:structuredClone(recipients)});setPendingCount(ids.length);setProblem(null);
    await submitStop();
  }
  async function checkStop(){
    const pending=pendingFreeze.current;if(!pending||busy)return;const token=version.current;setReadBusy(true);setProblem(null);
    try{const result=await api.match.query(pending.queryId);if(token!==version.current||!alive.current)return;if(!result.ok)throw result.error;
      if(result.data.id===pending.queryId&&result.data.activity_id===activityId&&result.data.stop_requested){stopOperation.confirmSaved();await freezePending();}
      else setProblem({code:'stop_unconfirmed',message:'Discovery has not confirmed the stop. Retry the same request.',retryable:false});
    }catch(error){if(token===version.current&&alive.current)setProblem(outreachReadError(error));}finally{if(alive.current)setReadBusy(false);}
  }
  async function reconcile(){
    if(!operation.locked||operation.state.phase!=='uncertain'||busy)return;
    const attempt=operation.state.attempt,token=version.current;setReadBusy(true);setProblem(null);
    try{
      if(attempt.command.kind==='freeze'){
        const requestId='request_id' in attempt.input.data?attempt.input.data.request_id:null;let found=false;
        for(let offset=0;offset<10_000;offset+=200){
          const result=await api.outreach.batches({activityId,offset,limit:200});if(token!==version.current||!alive.current)return;if(!result.ok)throw result.error;
          const summary=result.data.items.find(item=>item.request_id===requestId);
          if(summary){const detail=await api.outreach.batch({activityId,id:summary.id});if(token!==version.current||!alive.current)return;if(!detail.ok)throw detail.error;
            if(operation.confirmBatch(detail.data))await complete({kind:'freeze',data:detail.data});found=true;break;}
          if(offset+result.data.items.length>=result.data.total)break;if(!result.data.items.length)throw unavailable;
        }
        if(!found)setProblem({code:'batch_not_confirmed',message:'No matching preparation found. Retry the same request.',retryable:false});
      }else{
        const current=await readSelections(api.outreach,activityId,true);if(token!==version.current||!alive.current)return;
        if(operation.confirmSelections(current)){
          if(afterWrite.current.kind==='filter'){afterWrite.current.apply();setNotice(`${afterWrite.current.count} removed from selection`);}
          afterWrite.current={kind:'ordinary'};await refresh();
        }
      }
    }catch(error){if(alive.current&&token===version.current)setProblem(outreachReadError(error));}finally{if(alive.current)setReadBusy(false);}
  }
  return {session,local,selectionReady:local.enabled?local.ready:session.current,selectionCount:local.enabled?local.desired.length:session.items.length,operation,stopOperation,panel,setPanel,batch,batchCurrent,batchMode,selectedId,setSelectedId,chosenIds,setChosenIds,dirty,setDirty,historyEpoch,pendingCount,
    busy,locked,problem,notice,credentialsChanged,refresh,toggle,selectLoaded,deselectLoaded,changeOptions,changeProjection,prepare,openSelected,openBatch,openCurrentBatch,updatePerson,remove,reconcile,checkStop,
    retryStop:()=>submitStop(true),retry:()=>operation.retry().then(complete),isSelected:(candidate:CandidateView)=>local.enabled?local.isSelected(candidate):Boolean(candidateSelection(candidate,session.items)),
    cancelPending:()=>{if(!busy&&!locked){pendingFreeze.current=null;setPendingCount(0);}},
  };
}
