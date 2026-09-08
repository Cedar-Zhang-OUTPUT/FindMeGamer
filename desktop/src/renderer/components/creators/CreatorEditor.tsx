import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {ContactDetail,CreatorDetail,WorkDetail} from '../../../shared/creators';
import type {NavigationGuard} from '../../../shared/games';
import {ErrorNotice,Icon,Loading} from '../Primitives';
import {CreatorForm} from './CreatorForm';
import {ContactForm} from './ContactForm';
import {WorkForm} from './WorkForm';
import {CreatorDialog} from './CreatorDialog';
import {CreatorRecovery} from './CreatorRecovery';
import {changedKeys,draftFrom,fieldLabel,makePayload,sourceValue,updateDraftField,validateDraft,type EditContext,type EntityDraft} from './creatorDraft';
import './creatorEditor.css';
import {authErrors,canReplay,certainlyRejected,dispatchMutation,freezeAttempt,isCreation,mutationNetworkError,readNetworkError,RETRY_WINDOW,type MutationAttempt,type MutationCommand} from './creatorMutation';

type Phase='editing'|'saving'|'uncertain'|'conflict'|'reconciling'|'readback-failed';
type NavigationIntent={kind:'internal'}|{kind:'external';proceed:()=>void};
type Conflict={context:EditContext|null;creator:CreatorDetail|null;choices:Record<string,'mine'|'latest'>;error:PublicError|null;nextOffset?:number;identityChanged?:boolean};
function parentOf(context:EditContext){return context.kind==='creator'?context.base as CreatorDetail|null:context.creator??null;}
function commandFor(context:EditContext,draft:EntityDraft):MutationCommand {
  const data=makePayload(context,draft);
  return context.kind==='creator'?{kind:'creator',id:context.base?.id??null,data} as MutationCommand:
    {kind:context.kind,creatorId:context.creator!.id,id:context.base?.id??null,data} as MutationCommand;
}
const show=(value:unknown)=>value===null||value===undefined?'Unknown':typeof value==='object'?JSON.stringify(value,null,2):String(value);

export function CreatorEditor({api,initial,onSaved,onCancel,onNavigationGuardChange,onConnectionRepair}:{api:DesktopBridge;initial:EditContext;onSaved:(creator:CreatorDetail)=>void;onCancel:()=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void}) {
  const [context,setContext]=useState(initial);
  const [draft,setDraft]=useState(()=>draftFrom(initial));
  const [phase,setPhase]=useState<Phase>('editing');
  const [error,setError]=useState<PublicError|null>(null);
  const [errors,setErrors]=useState<Record<string,string>>({});
  const [attempt,setAttempt]=useState<MutationAttempt|null>(null);
  const attemptRef=useRef<MutationAttempt|null>(null);
  const [lookup,setLookup]=useState(false);
  const [conflict,setConflict]=useState<Conflict|null>(null);
  const [reading,setReading]=useState(false);
  const [recovery,setRecovery]=useState(false);
  const [pendingNavigation,setPendingNavigation]=useState<NavigationIntent|null>(null);
  const [savedId,setSavedId]=useState<string|null>(null);
  const [,tick]=useState(0);
  const alive=useRef(true),inFlight=useRef(false),readRevision=useRef(0);
  const heading=useRef<HTMLHeadingElement>(null),afterSave=useRef<NavigationIntent|null>(null);
  const dirty=changedKeys(context,draft).length>0;
  const changed=changedKeys(context,draft);
  // A confirmed name is one decision, not two independently mixable fields.
  const conflictKeys=changed.filter(key=>!(context.kind==='creator'&&changed.includes('public_name')&&key==='public_name_confirmed'));
  const busy=phase==='saving'||phase==='reconciling';
  const locked=phase==='uncertain';
  const historical=context.kind!=='creator'&&context.base&&!(context.base as ContactDetail|WorkDetail).is_current_identity;
  const needsGuard=dirty||busy||locked||phase==='conflict'||phase==='readback-failed';
  const setFrozen=useCallback((next:MutationAttempt|null)=>{attemptRef.current=next;setAttempt(next);},[]);
  const credentialsChanged=useCallback(()=>{
    if(attemptRef.current)setFrozen({...attemptRef.current,credentialsChanged:true});
    setRecovery(true);setLookup(false);setError(null);setPendingNavigation(null);readRevision.current++;
    setReading(false);
    setConflict(current=>current?{context:null,creator:null,choices:{},error:{code:'credentials_changed',message:'Credentials changed. Reload the current record to continue.',retryable:true}}:null);
  },[setFrozen]);
  const guard=useMemo<NavigationGuard>(()=>{
    const handler:NavigationGuard=proceed=>setPendingNavigation({kind:'external',proceed});
    if(recovery&&!busy)handler.recovery={credentialsChanged};
    return handler;
  },[recovery,busy,credentialsChanged]);
  useEffect(()=>{alive.current=true;heading.current?.focus({preventScroll:true});return()=>{alive.current=false;readRevision.current++;};},[]);
  useEffect(()=>{onNavigationGuardChange?.(needsGuard?guard:null);return()=>onNavigationGuardChange?.(null);},[needsGuard,guard,onNavigationGuardChange]);
  useEffect(()=>{
    if(!attempt||!locked)return;
    const timer=setTimeout(()=>tick(value=>value+1),Math.max(1,Math.min(attempt.startedAt+RETRY_WINDOW-Date.now()+1,2_147_483_647)));
    return()=>clearTimeout(timer);
  },[attempt,locked]);
  function rememberError(value:PublicError){setError(value);if(authErrors.has(value.code))setRecovery(true);}
  function finish(creator:CreatorDetail){onNavigationGuardChange?.(null);onSaved(creator);const navigation=afterSave.current;afterSave.current=null;if(navigation?.kind==='external')navigation.proceed();}
  async function reconcile(id:string){
    if(inFlight.current)return;inFlight.current=true;setSavedId(id);setPhase('reconciling');setError(null);
    try{
      const result=await api.creators.detail(id);
      if(!alive.current)return;
      if(result.ok)finish(result.data);else{rememberError(result.error);setPhase('readback-failed');afterSave.current=null;}
    }catch{if(alive.current){rememberError(readNetworkError);setPhase('readback-failed');afterSave.current=null;}}
    finally{inFlight.current=false;}
  }
  async function loadConflict(offset=0){
    const parent=parentOf(context);if(!parent)return;
    const token=++readRevision.current;setReading(true);setConflict({context:null,creator:null,choices:{},error:null});
    try{
      const response=await api.creators.detail(parent.id);
      if(!alive.current||token!==readRevision.current)return;
      if(!response.ok){setConflict({context:null,creator:null,choices:{},error:response.error});if(authErrors.has(response.error.code))setRecovery(true);return;}
      const latest=response.data;
      if(latest.source_identity.revision!==parent.source_identity.revision){setConflict({context:null,creator:latest,choices:{},error:null,identityChanged:true});return;}
      let base:EditContext['base']=context.kind==='creator'?latest:null;
      if(context.kind==='contact'&&context.base){
        base=latest.contacts.find(item=>item.id===context.base!.id)??null;
        if(!base||!(base as ContactDetail).is_current_identity){setConflict({context:null,creator:latest,choices:{},error:null,identityChanged:true});return;}
      }
      if(context.kind==='work'&&context.base){
        const works=await api.creators.works({creatorId:latest.id,includePreviousIdentity:true,offset,limit:100});
        if(!alive.current||token!==readRevision.current)return;
        if(!works.ok){setConflict({context:null,creator:latest,choices:{},error:works.error});if(authErrors.has(works.error.code))setRecovery(true);return;}
        base=works.data.items.find(item=>item.id===context.base!.id)??null;
        if(!base){setConflict({context:null,creator:latest,choices:{},error:works.data.offset+works.data.limit<works.data.total?null:{code:'creator_work_not_found',message:'This work is not in the current records.',retryable:false},nextOffset:works.data.offset+works.data.limit<works.data.total?works.data.offset+works.data.limit:undefined});return;}
        if(!(base as WorkDetail).is_current_identity||(base as WorkDetail).identity_revision!==latest.source_identity.revision){setConflict({context:null,creator:latest,choices:{},error:null,identityChanged:true});return;}
      }
      setConflict({context:{...context,base,...(context.kind!=='creator'?{creator:latest}:{})},creator:latest,choices:{},error:null});
    }catch{if(alive.current&&token===readRevision.current)setConflict({context:null,creator:null,choices:{},error:readNetworkError});}
    finally{if(alive.current&&token===readRevision.current)setReading(false);}
  }
  function choiceValue(key:string,choice:'mine'|'latest'){
    return choice==='latest'?draftFrom(conflict!.context!).values[key]:draft.resets.includes(key)?sourceValue(conflict!.context!,key):draft.values[key];
  }
  function publicNameConfirmed(choice:'mine'|'latest'){
    return choice==='latest'?choiceValue('public_name_confirmed','latest')===true:choiceValue('public_name','mine')===draft.values.public_name&&draft.values.public_name_confirmed===true;
  }
  function applyChoices(){
    if(!conflict?.context)return;
    if(!context.base){setContext(conflict.context);setPhase('editing');setConflict(null);setFrozen(null);return;}
    let next=draftFrom(conflict.context);
    for(const key of conflictKeys)if(conflict.choices[key]==='mine'){
      next=updateDraftField(next,key,draft.resets.includes(key)?sourceValue(conflict.context,key):draft.values[key]);
      if(draft.resets.includes(key))next.resets.push(key);
      if(key==='public_name')next.values.public_name_confirmed=publicNameConfirmed('mine');
      if(key==='public_name_confirmed'&&next.values.public_name!==draft.values.public_name)next.values.public_name_confirmed=false;
    }
    if(!changedKeys(conflict.context,next).length&&conflict.creator){finish(conflict.creator);return;}
    setContext(conflict.context);setDraft(next);setPhase('editing');setConflict(null);setFrozen(null);setError(null);
  }
  async function save(retry=false,navigation?:NavigationIntent){
    if(inFlight.current||historical||phase==='conflict'||phase==='reconciling'||phase==='readback-failed'||(locked&&!retry))return;
    if(retry&&(!attemptRef.current||!canReplay(attemptRef.current))){tick(value=>value+1);return;}
    if(!retry){
      const issues=validateDraft(context,draft);setErrors(issues);
      if(Object.keys(issues).length){setPendingNavigation(null);requestAnimationFrame(()=>{const element=document.getElementById(`creator-field-${Object.keys(issues)[0]}`);for(let parent=element?.parentElement;parent;parent=parent.parentElement)if(parent instanceof HTMLDetailsElement)parent.open=true;element?.focus();});return;}
      if(context.base&&!dirty){if(navigation?.kind==='external')navigation.proceed();else if(navigation)onCancel();return;}
    }
    const frozen=retry?attemptRef.current!:freezeAttempt(commandFor(context,draft));
    setFrozen(frozen);setLookup(false);setPendingNavigation(null);afterSave.current=navigation??null;inFlight.current=true;setPhase('saving');setError(null);
    try{
      const response=await dispatchMutation(api.creators,frozen);
      if(!alive.current)return;
      if(response.ok){
        const id=frozen.command.kind==='creator'?response.data.id:context.creator!.id;
        inFlight.current=false;await reconcile(id);return;
      }
      rememberError(response.error);afterSave.current=null;
      if(response.error.code==='connection_changed'&&attemptRef.current&&!attemptRef.current.credentialsChanged)setFrozen({...attemptRef.current,workspaceChanged:true});
      const rejected=!retry&&certainlyRejected(response.error.code);
      if(rejected){
        setFrozen(null);
        if(['creator_revision_conflict','work_revision_conflict','creator_identity_changed'].includes(response.error.code)&&parentOf(context)){setPhase('conflict');void loadConflict();}
        else setPhase('editing');
      }else setPhase('uncertain');
    }catch{if(alive.current){rememberError(mutationNetworkError);setPhase('uncertain');afterSave.current=null;}}
    finally{inFlight.current=false;}
  }
  function back(){if(needsGuard)setPendingNavigation({kind:'internal'});else onCancel();}
  const title=context.kind==='creator'?context.base?'Edit creator':'New creator':context.kind==='contact'?context.base?'Edit email':'Add email':context.base?'Edit work':'Add work';
  const action=context.base?'Save changes':context.kind==='creator'?'Create creator':context.kind==='contact'?'Add email':'Add work';
  const formProps={context,draft,disabled:busy||locked||phase==='readback-failed',errors,onChange:(next:EntityDraft)=>{setDraft(next);setErrors({});setError(null);}};
  if(historical)return <section><h2>Previous identity</h2><p>This record is read-only.</p><button className="button secondary" onClick={onCancel}>Back to creator</button></section>;
  return <section className="creator-editor"><div className="game-editor-heading"><button className="text-button" onClick={back}><Icon name="arrow"/>Back to creator</button>{dirty&&<span className="read-only-label">Unsaved changes</span>}</div><h2 ref={heading} tabIndex={-1}>{title}</h2>
    {phase==='reconciling'||phase==='readback-failed'?<section><h3>Save received</h3>{savedId&&<code>{savedId}</code>}{phase==='reconciling'?<Loading label="Loading current record…"/>:error&&<ErrorNotice error={error}/>}<button className="button primary" disabled={busy||!savedId} onClick={()=>savedId&&void reconcile(savedId)}>Retry current record</button></section>:phase==='conflict'?<section className="game-conflict" aria-label="Creator conflict resolution"><h3>Review latest changes</h3>
      {reading&&<Loading label="Reading current record…"/>}{conflict?.error&&<ErrorNotice error={conflict.error} onRetry={()=>void loadConflict()}/>}{conflict?.nextOffset!==undefined&&<button className="button secondary" onClick={()=>void loadConflict(conflict.nextOffset)}>Find in next page</button>}
      {conflict?.identityChanged&&<><p>The account identity changed. This draft has not been applied to the new account.</p><button className="button secondary" onClick={()=>{onNavigationGuardChange?.(null);onSaved(conflict.creator!);}}>Discard draft and view account</button></>}
      {conflict?.context&&<>{!context.base?<p>A newer version is available.</p>:<div className="game-conflict-rows">{conflictKeys.map(key=><fieldset key={key}><legend>{fieldLabel(key)}</legend>{(['latest','mine'] as const).map(choice=><label key={choice}>
        <input type="radio" name={`creator-choice-${key}`} aria-label={`${choice==='mine'?'Keep mine':'Use latest'}: ${fieldLabel(key)}`} aria-describedby={key==='public_name'?`creator-name-confirmation-${choice}`:undefined} checked={conflict.choices[key]===choice} onChange={()=>setConflict({...conflict,choices:{...conflict.choices,[key]:choice}})}/>
        <span><strong>{choice==='mine'?'Keep mine':'Use latest'}</strong><pre>{show(choiceValue(key,choice))}</pre>{key==='public_name'&&<small id={`creator-name-confirmation-${choice}`}>{publicNameConfirmed(choice)?'Confirmed':'Not confirmed'}</small>}</span>
      </label>)}</fieldset>)}</div>}
        <button className="button primary" disabled={Boolean(context.base)&&conflictKeys.some(key=>!conflict.choices[key])} onClick={applyChoices}>{context.base?'Apply choices':'Use current revision'}</button></>}
    </section>:<>
      {locked&&attempt&&<section className="game-uncertain"><h3>Save result unconfirmed</h3><p>{attempt.workspaceChanged?'Return to the original workspace to check this request.':attempt.credentialsChanged?'Credentials changed. Check records; this request cannot be replayed.':!isCreation(attempt.command)?'Check the current record before applying further changes.':!canReplay(attempt)?'The safe retry window has ended. Check records before deciding what to use.':'The save may have completed. Retry safely, or check records.'}</p><div className="button-row">{isCreation(attempt.command)&&<button className="button primary" disabled={!canReplay(attempt)} onClick={()=>void save(true)}>Retry same request</button>}<button className="button secondary" disabled={attempt.workspaceChanged} onClick={()=>{if(isCreation(attempt.command))setLookup(true);else{setPhase('conflict');void loadConflict();}}}>{isCreation(attempt.command)?'Check records':'Check current record'}</button></div>{lookup&&<CreatorRecovery api={api.creators} attempt={attempt} onUse={id=>void reconcile(id)}/>}</section>}
      {error&&<ErrorNotice error={error}/>}{Object.keys(errors).length>0&&<p role="alert">Check the highlighted fields.</p>}
      <form noValidate onSubmit={event=>{event.preventDefault();void save();}}>{context.kind==='creator'?<CreatorForm {...formProps}/>:context.kind==='contact'?<ContactForm {...formProps}/>:<WorkForm {...formProps} api={api}/>}<div className="game-editor-footer"><button className="button secondary" type="button" disabled={busy||locked} onClick={back}>Cancel</button><button className="button primary" type="submit" disabled={busy||locked||Boolean(context.base&&!dirty)}>{busy?'Saving…':action}</button></div></form>
    </>}
    {recovery&&onConnectionRepair&&!busy&&<button className="button secondary" onClick={onConnectionRepair}>Repair connection</button>}
    {pendingNavigation&&<CreatorDialog title={phase==='readback-failed'?'Reload saved creator':'Unsaved creator changes'} onClose={()=>setPendingNavigation(null)} actions={<>
      <button className="button secondary" onClick={()=>setPendingNavigation(null)}>{phase==='readback-failed'?'Stay here':'Continue editing'}</button>
      {phase==='readback-failed'?pendingNavigation.kind==='external'&&<button className="text-button" onClick={()=>{const navigation=pendingNavigation;setPendingNavigation(null);navigation.proceed();}}>Leave without reloading</button>:<button className="text-button" disabled={busy||locked} onClick={()=>{const navigation=pendingNavigation;onNavigationGuardChange?.(null);setPendingNavigation(null);onCancel();if(navigation.kind==='external')navigation.proceed();}}>Discard changes</button>}
      {phase==='readback-failed'?<button className="button primary" disabled={!savedId} onClick={()=>{if(!savedId)return;afterSave.current=pendingNavigation;setPendingNavigation(null);void reconcile(savedId);}}>Retry current record</button>:<button className="button primary" disabled={busy||locked||phase==='conflict'} onClick={()=>void save(false,pendingNavigation)}>Save and leave</button>}
    </>}><p>{locked?'Resolve the unconfirmed request before starting another.':busy?'Your save is still in progress.':phase==='readback-failed'?'Save received. Reload the current record before leaving.':'Save your changes before leaving?'}</p></CreatorDialog>}
  </section>;
}
