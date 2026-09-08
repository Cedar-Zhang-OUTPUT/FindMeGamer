import {useCallback,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {SavedSetView} from '../../../shared/savedSets';
import type {NavigationGuard} from '../../../shared/games';
import type {PlanCreate} from '../../../shared/match';
import {ErrorNotice,Icon,Loading} from '../Primitives';
import {DiscoveryConditions} from './DiscoveryConditions';
import {defaultConditions,validateConditions} from './discoveryConditionState';
import {CandidateResults,EvaluationResults} from './MatchResults';
import {CandidateQueryControls} from './CandidateQueryControls';
import {useMatchSession,queryIsRunning} from './useMatchSession';
import {useMatchOperation,type OperationReceipt} from './useMatchOperation';
import {MatchOperationNotice} from './MatchOperationNotice';
import {useMatchGuard} from './useMatchGuard';
import {taskDate,taskLabel} from './matchStatus';
import {useCollectionPolicy} from './useCollectionPolicy';
import {canContinueWithCollection,eligiblePlatforms} from './collectionPolicy';
import {CollectionSources} from './CollectionSources';
import {matchAuthErrors,type MatchCommand} from './matchMutation';
import {useSavedSetOperation} from './useSavedSetOperation';
import {SavedListComposer,SavedListNotice,type SavedListDraft} from './SavedListComposer';
import {SavedSetPicker,SavedSetResults} from './SavedSetBrowser';
import {useActivityOutreach} from './useActivityOutreach';
import {OutreachNotice,OutreachWorkspace,PreparationHistory} from './OutreachWorkspace';
import {useActivityDrafts} from './useActivityDrafts';
import {DraftsWorkspace,CompositionHistory} from './DraftsWorkspace';

function ResultTabs({value,onChange,count}:{value:'candidates'|'briefs';onChange:(value:'candidates'|'briefs')=>void;count?:number}){
  return <div role="tablist" aria-label="Match results" onKeyDown={event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const next=event.key==='Home'?'candidates':event.key==='End'?'briefs':value==='candidates'?'briefs':'candidates';onChange(next);
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role=tab]')[next==='candidates'?0:1]?.focus();
  }}><button role="tab" tabIndex={value==='candidates'?0:-1} aria-selected={value==='candidates'} onClick={()=>onChange('candidates')}>Candidates</button><button role="tab" tabIndex={value==='briefs'?0:-1} aria-selected={value==='briefs'} onClick={()=>onChange('briefs')}>Match briefs{count!==undefined?` · ${count}`:''}</button></div>;
}

export function MatchActivity({api,activityId,active,onBack,onOpenCreator,onNavigationGuardChange,onConnectionRepair,onCollectionSettings}:{api:DesktopBridge;activityId:string;active:boolean;onBack:()=>void;onOpenCreator:(id:string,section?:'overview'|'contacts'|'works')=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void;onCollectionSettings?:()=>void}){
  const session=useMatchSession(api.match,activityId,active),operation=useMatchOperation(api.match);
  const savedOperation=useSavedSetOperation(api.savedSets);
  const [listDraft,setListDraft]=useState<SavedListDraft|null>(null),[openedSetId,setOpenedSetId]=useState<string|null>(null),[setsRefresh,setSetsRefresh]=useState(0);
  const [checkingSet,setCheckingSet]=useState(false),[recoveredSet,setRecoveredSet]=useState<SavedSetView|null>(null),[setReadError,setSetReadError]=useState<PublicError|null>(null),[setReadBusy,setSetReadBusy]=useState(false);
  const setReadVersion=useRef(0);
  const policy=useCollectionPolicy(api.settings,active);
  const [draft,setDraft]=useState<PlanCreate|null>(null),[tab,setTab]=useState<'candidates'|'briefs'>('candidates');
  const [acknowledge,setAcknowledge]=useState(false),[retryAcknowledged,setRetryAcknowledged]=useState(false);
  const [checking,setChecking]=useState(false),[recoveredId,setRecoveredId]=useState(''),[knownBatches,setKnownBatches]=useState<string[]>([]);
  const {activity,plan,query,evaluation}=session;
  const drafts=useActivityDrafts({api,activityId,gameId:activity?.game_id??null,active});
  const outreach=useActivityOutreach({api,activityId,active,queryId:query?.id??null,candidates:session.candidates,candidateCurrent:session.candidateMembershipCurrent,options:session.candidateOptions,onOptions:session.setCandidateOptions,blocked:operation.busy||operation.locked||savedOperation.busy||savedOperation.locked||drafts.busy||drafts.locked||Boolean(listDraft)||Boolean(draft)});
  const policyNeedsRepair=Boolean(policy.error&&matchAuthErrors.has(policy.error.code));
  const credentialsChanged=useCallback(()=>{operation.credentialsChanged();savedOperation.credentialsChanged();outreach.credentialsChanged();drafts.credentialsChanged();setReadVersion.current++;setRecoveredSet(null);setSetReadBusy(false);},[operation.credentialsChanged,savedOperation.credentialsChanged,outreach.credentialsChanged,drafts.credentialsChanged]);
  const guard=useMatchGuard({operation:{busy:operation.busy||savedOperation.busy||outreach.busy||drafts.busy,locked:operation.locked||savedOperation.locked||outreach.locked||drafts.locked,state:{error:operation.state.error??savedOperation.state.error??outreach.operation.state.error??outreach.stopOperation.state.error??drafts.operation.state.error},credentialsChanged},dirty:draft!==null||listDraft!==null||outreach.dirty||drafts.dirty,readRepair:policyNeedsRepair,onChange:onNavigationGuardChange,onDiscard:()=>{setDraft(null);setListDraft(null);outreach.setDirty(false);outreach.setSelectedId(null);drafts.discardEdits();}});
  const showingConditions=draft!==null||(session.ready&&!session.scope?.planId&&!session.scope?.queryId);
  function complete(receipt:OperationReceipt|null){
    if(!receipt)return;setChecking(false);setRecoveredId('');setAcknowledge(false);setRetryAcknowledged(false);
    if('plan_id' in receipt.data){setDraft(null);setTab('candidates');session.selectScope({planId:receipt.data.plan_id,queryId:null});}
    else if('evaluation_id' in receipt.data){session.selectEvaluation(receipt.data.evaluation_id);setTab('briefs');}
    else session.refresh();
  }
  function execute(command:MatchCommand){if(command.kind==='continueDiscovery')setKnownBatches(query?.batches.map(batch=>batch.id)??[]);void operation.execute(command).then(complete);}
  function startDiscovery(){const conditions=draft??defaultConditions();if(policy.phase!=='ready'||!eligiblePlatforms(conditions.platforms,policy.data).length||Object.keys(validateConditions(conditions)).length)return;execute({kind:'createPlan',activityId,data:{...conditions,mode:'discover'}});}
  function refresh(){session.refresh();policy.refresh();void outreach.refresh();void drafts.refresh();}
  const locked=operation.busy||operation.locked||savedOperation.busy||savedOperation.locked||outreach.busy||outreach.locked||drafts.busy||drafts.locked;
  function savedList(metadata:SavedSetView|null){if(!metadata)return;setListDraft(null);setCheckingSet(false);setRecoveredSet(null);setOpenedSetId(metadata.id);setSetsRefresh(value=>value+1);}
  function saveList(){if(!listDraft||!session.candidateMembershipCurrent||locked)return;void savedOperation.execute({queryId:listDraft.queryId,name:listDraft.name,candidateIds:listDraft.ids}).then(savedList);}
  function markCandidate(id:string){if(!session.candidateMembershipCurrent||locked)return;setListDraft(previous=>previous?{...previous,ids:previous.ids.includes(id)?previous.ids.filter(value=>value!==id):previous.ids.length<600?[...previous.ids,id]:previous.ids}:null);}
  function openCreator(id:string,section?:'overview'|'contacts'|'works'){if(!locked&&draft===null)onOpenCreator(id,section);else guard.request(()=>onOpenCreator(id,section));}
  function openSaved(id:string){guard.request(()=>{setOpenedSetId(id);setListDraft(null);setDraft(null);setTab('candidates');});}
  function savedMetadata(metadata:SavedSetView){if(query?.id!==metadata.query_id)session.selectScope({planId:null,queryId:metadata.query_id});}
  async function inspectSaved(id:string){
    const version=++setReadVersion.current;setSetReadBusy(true);setRecoveredSet(null);setSetReadError(null);
    try{const result=await api.savedSets.detail(id);if(version!==setReadVersion.current)return;if(result.ok&&result.data.activity_id===activityId)setRecoveredSet(result.data);else setSetReadError(result.ok?{code:'saved_set_mismatch',message:'This list belongs to another activity.',retryable:false}:result.error);}
    catch{if(version===setReadVersion.current)setSetReadError({code:'network_error',message:'The saved list could not be loaded.',retryable:true});}
    finally{if(version===setReadVersion.current)setSetReadBusy(false);}
  }
  const eligible=session.candidates.filter(candidate=>!candidate.identity_changed);
  const running=queryIsRunning(query);
  const lastBatch=query?.batches.reduce<(typeof query.batches)[number]|undefined>((latest,batch)=>!latest||batch.ordinal>latest.ordinal?batch:latest,undefined);
  const game=activity?.source_snapshot.game;
  const gameName=game&&typeof game==='object'&&!Array.isArray(game)&&typeof game.name==='string'?game.name:'Saved game';
  const evaluationUnknown=Boolean(evaluation?.steps.some(step=>step.error_code?.includes('outcome_unknown')));
  const planningUnknown=plan?.error_code==='planning_outcome_unknown';
  const command=operation.state.phase==='uncertain'?operation.state.attempt.command:null;
  const canReconcileQuery=command?.kind==='stop'?query?.stop_requested&&!running:command?.kind==='continueDiscovery'?query?.batches.some(batch=>!knownBatches.includes(batch.id)):false;
  function reconcile(){
    if(!command)return;
    if((command.kind==='createPlan'||command.kind==='retryPlan')&&recoveredId){operation.confirmSaved();session.selectScope({planId:recoveredId,queryId:null});setDraft(null);}
    else if((command.kind==='evaluate'||command.kind==='retryEvaluation')&&recoveredId){operation.confirmSaved();session.selectEvaluation(recoveredId);setTab('briefs');}
    else if(canReconcileQuery)operation.confirmSaved();else return;
    setChecking(false);setRecoveredId('');
  }
  return <section className="match-activity">
    <div className="match-breadcrumb"><button className="text-button" onClick={()=>guard.request(onBack)}><Icon name="arrow"/>Activities</button><span>{gameName}</span><button className="icon-button" title="Refresh activity" aria-label="Refresh activity" onClick={refresh} disabled={session.loading}><Icon name="refresh"/></button></div>
    <div className="page-heading"><h1>{activity?.name??'Activity'}</h1></div>
    {!activity&&!session.errors.activity&&<Loading label="Loading activity…"/>}{session.errors.activity&&<ErrorNotice error={session.errors.activity} onRetry={session.refresh}/>}
    {activity&&<>
      <details className="match-context"><summary>Game context</summary><p>{gameName} · Saved {taskDate(activity.created_at)}</p><p>Library edits do not change this activity’s saved game or references.</p>{game&&typeof game==='object'&&!Array.isArray(game)&&typeof game.description==='string'&&<p>{game.description}</p>}
        {Array.isArray(activity.source_snapshot.references)&&<ul>{activity.source_snapshot.references.map((reference,index)=><li key={index}>{reference&&typeof reference==='object'&&!Array.isArray(reference)&&typeof reference.name==='string'?reference.name:'Reference work'}</li>)}</ul>}
      </details>
      <PreparationHistory api={api.outreach} activityId={activityId} active={active} epoch={outreach.historyEpoch} disabled={locked} onOpen={id=>guard.request(()=>{drafts.setMode({kind:'people'});void outreach.openBatch(id);})}/>
      <CompositionHistory api={api.drafts} activityId={activityId} active={active} epoch={drafts.historyEpoch} disabled={locked} onOpen={id=>guard.request(()=>void drafts.open(id))}/>
      <DraftsWorkspace api={api} controller={drafts} active={active} onRequest={action=>{if(locked)guard.request(action);else action();}} onBack={()=>drafts.setMode({kind:'people'})} onConnectionRepair={onConnectionRepair} onRepairPerson={selectionId=>{if(drafts.batch)void outreach.openCurrentBatch(drafts.batch.id,selectionId).then(opened=>{if(opened)drafts.setMode({kind:'people'});});}}/>
      <div hidden={drafts.mode.kind!=='people'}>
      {drafts.composition&&<button className="button secondary" disabled={locked||outreach.dirty} onClick={()=>{drafts.setMode({kind:'composition',id:drafts.composition!.id});void drafts.open(drafts.composition!.id);}}>Back to drafts</button>}
      <OutreachNotice controller={outreach} onRepair={onConnectionRepair}/>
      {outreach.panel!=='candidates'&&<OutreachWorkspace api={api} controller={outreach} active={active&&drafts.mode.kind==='people'} onRequest={guard.request} onOpenCreator={openCreator} onChooseTemplate={()=>guard.request(()=>{if(outreach.batch)void drafts.begin(outreach.batch);})} evaluationChoices={session.runs.map(run=>({id:run.id,label:`${taskDate(run.created_at)} · ${taskLabel(run.status)}`}))}/>}
      <div hidden={outreach.panel!=='candidates'}>
      <SavedSetPicker api={api.savedSets} activityId={activityId} active={active&&outreach.panel==='candidates'} refreshToken={setsRefresh} disabled={locked} selectedId={openedSetId} onOpen={openSaved}/>
      {query&&<div className="outreach-toolbar"><div className="button-row"><button className="button secondary" disabled={locked||Boolean(listDraft)||!outreach.session.current} onClick={()=>guard.request(outreach.openSelected)}>Selected · {outreach.session.items.length}</button>{!openedSetId&&<button className="text-button" disabled={locked||Boolean(listDraft)||!session.candidateMembershipCurrent||!outreach.session.current||!eligible.length} onClick={()=>void outreach.selectLoaded()}>Select loaded</button>}</div>{outreach.session.loading&&<span role="status">Loading selection…</span>}{outreach.session.error&&<ErrorNotice error={outreach.session.error} onRetry={()=>void outreach.refresh()}/>}</div>}
      {showingConditions?<><h2>Find creators</h2>{plan&&<p className="inline-warning">New search · Earlier results and evaluations stay in history.</p>}<CollectionSources selected={(draft??defaultConditions()).platforms} policy={policy} onSettings={onCollectionSettings??onConnectionRepair}/><DiscoveryConditions value={draft??defaultConditions()} onChange={setDraft} disabled={locked} submitDisabled={policy.phase!=='ready'||!eligiblePlatforms((draft??defaultConditions()).platforms,policy.data).length} onSubmit={startDiscovery} onCancel={session.scope?.planId||session.scope?.queryId?()=>setDraft(null):undefined}/></>:<>
        <div className="match-history"><label>Search<select aria-label="Search history" disabled={locked} value={session.scope?.planId?`plan:${session.scope.planId}`:session.scope?.queryId?`query:${session.scope.queryId}`:''} onChange={event=>{const [kind,id]=event.target.value.split(':');guard.request(()=>{setOpenedSetId(null);setAcknowledge(false);session.selectScope({planId:kind==='plan'?id:null,queryId:kind==='query'?id:null});});}}>
          {session.plans.map(item=><option key={item.id} value={`plan:${item.id}`}>{taskDate(item.created_at)} · {item.conditions.platforms.map(platform=>platform==='youtube'?'YouTube':'X').join(' + ')} · {taskLabel(item.status)}</option>)}
          {activity.queries.filter(item=>!session.plans.some(search=>search.query_id===item.id)).map(item=><option key={item.id} value={`query:${item.id}`}>{taskDate(item.created_at)} · {taskLabel(item.status)}</option>)}
          {session.scope?.planId&&!session.plans.some(item=>item.id===session.scope?.planId)&&<option value={`plan:${session.scope.planId}`}>Submitted search</option>}
        </select></label>{session.plans.length<session.plansTotal&&<button className="text-button" onClick={session.loadMorePlans}>Older searches</button>}<button className="button secondary" disabled={locked} onClick={()=>guard.request(()=>{setOpenedSetId(null);setDraft(structuredClone(plan?.conditions??defaultConditions()));})}>Adjust conditions</button></div>
        {plan&&(plan.status==='queued'||plan.status==='running')&&<Loading label={plan.status==='queued'?'Planning queued…':'Planning discovery…'}/>}
        {plan?.error_code&&<section className="match-task-problem" role="status"><strong>{taskLabel(plan.error_code)}</strong>{planningUnknown&&<label className="match-acknowledgement"><input type="checkbox" checked={retryAcknowledged} onChange={event=>setRetryAcknowledged(event.target.checked)}/>I accept possible repeated model charges</label>}{plan.retryable&&<button className="button primary" disabled={locked||(planningUnknown&&!retryAcknowledged)} onClick={()=>execute({kind:'retryPlan',id:plan.id})}>{plan.query_id?'Retry dispatch':'Retry planning'}</button>}{onConnectionRepair&&<button className="button secondary" onClick={onConnectionRepair}>Open Settings</button>}</section>}
        {plan&&<details className="match-context"><summary>Search details</summary><div className="match-condition-summary"><span>{plan.conditions.platforms.map(platform=>platform==='youtube'?'YouTube':'X').join(' + ')}</span><span>Batch target {plan.conditions.batch_target??100}</span><span>Result limit {plan.conditions.result_limit??600}</span></div><dl>{Object.entries(plan.conditions.filters??{}).filter(([,value])=>Array.isArray(value)?value.length>0:value!==false&&value!=='any').map(([key,value])=><div key={key}><dt>{taskLabel(key)}</dt><dd>{Array.isArray(value)?value.map(item=>typeof item==='object'?`${item.minimum??0}–${item.maximum??'any'}`:String(item)).join(', '):String(value)}</dd></div>)}</dl>{plan.conditions.keywords?.length?<p>{plan.conditions.keywords.join(' · ')}</p>:null}{plan.output&&<><p>{plan.output.summary}</p><details><summary>Planning rationale</summary><p>{plan.output.rationale}</p><dl>{Object.entries(plan.output.provider_queries).map(([platform,terms])=><div key={platform}><dt>{platform}</dt><dd>{terms}</dd></div>)}</dl></details></>}</details>}
        {query&&<>
          <div className="match-discovery-header"><div><strong className="match-found-count">{query.result_count}</strong><span>creators found</span><span className={`status-badge ${running?'match-running':''}`}>{query.stop_requested&&running?'Stopping':taskLabel(query.status)}</span></div>
            {running?<button className="button secondary" disabled={locked||query.stop_requested} onClick={()=>execute({kind:'stop',queryId:query.id})}>Stop discovery</button>:<button className="button secondary" disabled={locked||policy.phase!=='ready'||!canContinueWithCollection(query,policy.data)||(query.requires_acknowledgement&&!acknowledge)} onClick={()=>execute({kind:'continueDiscovery',queryId:query.id,data:{acknowledge_unknown:acknowledge}})}>Continue discovery</button>}
          </div>
          {query.requires_acknowledgement&&<div className="match-task-problem"><strong>Provider outcome unknown</strong><label className="match-acknowledgement"><input type="checkbox" checked={acknowledge} onChange={event=>setAcknowledge(event.target.checked)}/>I accept possible repeated provider charges</label></div>}
          {!running&&lastBatch?.reason&&<p className="match-batch-state" role="status">{taskLabel(lastBatch.reason)}</p>}
          <CollectionSources selected={query.conditions.providers.map(provider=>provider.platform)} query={query} policy={policy} onSettings={onCollectionSettings??onConnectionRepair}/>
          <details className="match-context"><summary>Discovery usage</summary><dl><div><dt>Requests used</dt><dd>{query.usage.requests_used}</dd></div><div><dt>Items received</dt><dd>{query.usage.provider_items_received}</dd></div><div><dt>Unknown request reservations</dt><dd>{query.usage.unknown_requests_reserved}</dd></div><div><dt>Reserved request budget</dt><dd>{query.requests_reserved} / {query.conditions.total_request_budget??120}</dd></div><div><dt>Reserved item budget</dt><dd>{query.scanned_reserved} / {query.conditions.total_scan_budget??6000}</dd></div></dl></details>
          {!openedSetId&&<><div className="match-results-toolbar"><ResultTabs value={tab} onChange={setTab} count={evaluation?.matched_count}/><div className="match-evaluate-action"><button className="button primary" disabled={locked||Boolean(listDraft)||!session.candidateMembershipCurrent||eligible.length===0||Boolean(evaluation&&(evaluation.status==='running'||evaluation.status==='queued'))} onClick={()=>execute({kind:'evaluate',queryId:query.id,data:{candidate_ids:eligible.map(candidate=>candidate.id)}})}>Evaluate {eligible.length} loaded</button><span>Uses model quota</span></div></div>
          {tab==='candidates'?<><CandidateQueryControls value={session.candidateOptions} filteredTotal={session.candidateTotal} queryTotal={query.result_count} current={session.candidateMembershipCurrent} loading={session.candidateLoading} disabled={locked} onChange={next=>{if(listDraft)session.setCandidateOptions(next);else void outreach.changeOptions(next);}}/>{listDraft?<SavedListComposer draft={listDraft} onChange={setListDraft} onCancel={()=>setListDraft(null)} onSave={saveList} disabled={locked} current={session.candidateMembershipCurrent} onMarkLoaded={()=>setListDraft(previous=>previous?{...previous,ids:[...new Set([...previous.ids,...session.candidates.map(item=>item.id)])].slice(0,600)}:null)} onClear={()=>setListDraft(previous=>previous?{...previous,ids:[]}:null)}/>:<div className="saved-list-tools"><button className="button secondary" disabled={locked||!session.candidateMembershipCurrent||!session.candidates.length} onClick={()=>setListDraft({queryId:query.id,name:'',ids:[]})}>Save list</button></div>}<CandidateResults candidates={session.candidates} total={session.candidateTotal} loading={session.candidateLoading} stale={!session.candidateMembershipCurrent&&session.candidates.length>0} sort={session.candidateOptions.sort} onLoadMore={session.loadMoreCandidates} onOpenCreator={openCreator} outreach={{isSelected:outreach.isSelected,disabled:locked||!session.candidateMembershipCurrent||!outreach.session.current,onToggle:candidate=>void outreach.toggle(candidate)}} selection={listDraft?{ids:listDraft.ids,disabled:locked||!session.candidateMembershipCurrent,onToggle:markCandidate}:undefined}/>{session.errors.candidates&&<ErrorNotice error={session.errors.candidates} onRetry={session.refresh}/>}</>:<section className="match-evaluation" aria-label="Evaluation">
            {session.runs.length>0&&<div className="match-run-picker"><label>Evaluation<select aria-label="Evaluation history" disabled={locked} value={evaluation?.id??''} onChange={event=>{session.selectEvaluation(event.target.value);setRetryAcknowledged(false);}}>{!evaluation&&<option value="">Loading evaluation…</option>}{session.runs.map(run=><option key={run.id} value={run.id}>{taskDate(run.created_at)} · {run.candidate_count} candidates · {taskLabel(run.status)}</option>)}</select></label>{session.runs.length<session.runTotal&&<button className="text-button" onClick={session.loadMoreRuns}>Older evaluations</button>}</div>}
            {evaluation?<><div className="match-evaluation-status" role="status"><strong>{evaluation.status==='running'?taskLabel(evaluation.stage):taskLabel(evaluation.status)}</strong><span>{evaluation.candidate_count} frozen candidates</span></div><details className="match-context"><summary>Evaluation usage</summary><dl><div><dt>Model operations started</dt><dd>{evaluation.usage.model_operations_started}</dd></div><div><dt>Steps completed</dt><dd>{evaluation.usage.succeeded_steps}</dd></div><div><dt>Steps failed</dt><dd>{evaluation.usage.failed_steps}</dd></div></dl></details>{evaluation.retryable&&<div className="match-task-problem">{evaluationUnknown&&<label className="match-acknowledgement"><input type="checkbox" checked={retryAcknowledged} onChange={event=>setRetryAcknowledged(event.target.checked)}/>I accept possible repeated model charges</label>}<button className="button secondary" disabled={locked||(evaluationUnknown&&!retryAcknowledged)} onClick={()=>execute({kind:'retryEvaluation',id:evaluation.id,data:{}})}>Retry failed steps</button></div>}<EvaluationResults results={session.results} total={session.resultTotal} loading={session.loading||evaluation.status==='queued'||evaluation.status==='running'} onLoadMore={session.loadMoreResults} onOpenCreator={(id,section)=>guard.request(()=>onOpenCreator(id,section))} onOpenExternal={url=>{void api.openExternal(url);}}/></>:<p className="match-no-evaluation">No evaluation yet</p>}
            {session.errors.evaluation&&<ErrorNotice error={session.errors.evaluation} onRetry={session.refresh}/>}</section>}</>}
        </>}
      </>}
      {openedSetId&&<SavedSetResults api={api.savedSets} id={openedSetId} activityId={activityId} active={active&&outreach.panel==='candidates'} onMetadata={savedMetadata} onOriginal={()=>setOpenedSetId(null)} onOpenCreator={openCreator} outreach={{isSelected:outreach.isSelected,disabled:locked||!outreach.session.current,onToggle:candidate=>void outreach.toggle(candidate,true)}} onSelectLoaded={candidates=>void outreach.selectLoaded(candidates,true)} onQueryChange={change=>outreach.changeProjection(change)}/>}
      </div>
      </div>
      <SavedListNotice operation={savedOperation} onRetry={()=>void savedOperation.retry().then(savedList)} onCheck={()=>{setCheckingSet(true);setSetsRefresh(value=>value+1);}} onRepair={onConnectionRepair}/>
      {checkingSet&&savedOperation.locked&&<section className="saved-list-recovery" aria-label="Recover saved list"><SavedSetPicker api={api.savedSets} activityId={activityId} active={active} refreshToken={setsRefresh} disabled={setReadBusy} onOpen={id=>void inspectSaved(id)}/>{setReadBusy&&<Loading label="Checking saved list…"/>}{recoveredSet&&<p>{recoveredSet.name} · {recoveredSet.count} saved</p>}{setReadError&&<ErrorNotice error={setReadError}/>}<button className="button secondary" disabled={!recoveredSet||setReadBusy} onClick={()=>{if(recoveredSet&&savedOperation.confirmSaved(recoveredSet))savedList(recoveredSet);}}>Use saved list</button></section>}
      {session.errors.plans&&<ErrorNotice error={session.errors.plans} onRetry={session.refresh}/>} {session.errors.plan&&<ErrorNotice error={session.errors.plan} onRetry={session.refresh}/>} {session.errors.query&&<ErrorNotice error={session.errors.query} onRetry={session.refresh}/>}
      {policyNeedsRepair&&onConnectionRepair&&<button className="button secondary" onClick={onConnectionRepair}>Repair connection</button>}
      <MatchOperationNotice operation={operation} onRetry={()=>void operation.retry().then(complete)} onCheck={()=>{setChecking(true);setRecoveredId('');session.refresh();}} onRepair={onConnectionRepair}/>
      {checking&&command&&<section className="match-recovery-records" aria-label="Saved tasks"><h3>Confirm the task saved by this request</h3>{command.kind==='createPlan'||command.kind==='retryPlan'?<><select aria-label="Saved search to use" value={recoveredId} onChange={event=>setRecoveredId(event.target.value)}><option value="">Choose the saved search</option>{session.plans.map(item=><option key={item.id} value={item.id}>{taskDate(item.created_at)} · {item.conditions.platforms.join(' + ')} · {item.id}</option>)}</select>{session.plans.length<session.plansTotal&&<button onClick={session.loadMorePlans}>Older searches</button>}</>:command.kind==='evaluate'||command.kind==='retryEvaluation'?<select aria-label="Saved evaluation to use" value={recoveredId} onChange={event=>setRecoveredId(event.target.value)}><option value="">Choose the saved evaluation</option>{session.runs.map(item=><option key={item.id} value={item.id}>{taskDate(item.created_at)} · {item.candidate_count} candidates · {item.id}</option>)}</select>:<p>{canReconcileQuery?'The submitted query change is now recorded.':'No confirming query change yet. Refresh status or retry the same request.'}</p>}<button className="button secondary" disabled={!recoveredId&&!canReconcileQuery||session.loading} onClick={reconcile}>Use saved task</button></section>}
    </>}{guard.dialog}
  </section>;
}
