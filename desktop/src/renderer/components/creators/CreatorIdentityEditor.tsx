import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import {CREATOR_PLATFORMS,type CreatorDetail,type CreatorPlatform,type IdentityUpdate} from '../../../shared/creators';
import type {NavigationGuard} from '../../../shared/games';
import {ErrorNotice,Icon,Loading} from '../Primitives';
import {CreatorDialog} from './CreatorDialog';
import {validWebURL} from './creatorDraft';
import {authErrors,certainlyRejected,mutationNetworkError,readNetworkError} from './creatorMutation';
import './creatorEditor.css';

type Phase='editing'|'confirming'|'saving'|'unconfirmed'|'checking'|'review-current';
function IdentitySummary({creator}:{creator:CreatorDetail}) {
  const identity=creator.source_identity;
  return <div className="creator-identity-summary"><strong>{identity.platform}</strong><span>{identity.account_id||'URL-only identity'}</span>{identity.canonical_url&&<span>{identity.canonical_url}</span>}</div>;
}
export function CreatorIdentityEditor({api,initial,onSaved,onCancel,onNavigationGuardChange,onConnectionRepair}:{api:DesktopBridge;initial:CreatorDetail;onSaved:(creator:CreatorDetail)=>void;onCancel:()=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void}) {
  const [base,setBase]=useState(initial);
  const [platform,setPlatform]=useState<CreatorPlatform>(initial.platform);
  const [account,setAccount]=useState(''),[url,setURL]=useState('');
  const [phase,setPhase]=useState<Phase>('editing');
  const [error,setError]=useState<PublicError|null>(null);
  const [current,setCurrent]=useState<CreatorDetail|null>(null);
  const [frozen,setFrozen]=useState<IdentityUpdate|null>(null);
  const [recovery,setRecovery]=useState(false);
  const [navigation,setNavigation]=useState<(()=>void)|null>(null);
  const alive=useRef(true),inFlight=useRef(false),generation=useRef(0),heading=useRef<HTMLHeadingElement>(null);
  const busy=phase==='saving'||phase==='checking';
  const unresolved=phase==='unconfirmed'||phase==='review-current';
  const dirty=Boolean(account||url||platform!==base.platform);
  const needsGuard=dirty||busy||unresolved;
  const credentialsChanged=useCallback(()=>{generation.current++;setError(null);setCurrent(null);setRecovery(true);if(frozen)setPhase('unconfirmed');},[frozen]);
  const guard=useMemo<NavigationGuard>(()=>{
    const handler:NavigationGuard=proceed=>setNavigation(()=>proceed);
    if(recovery&&!busy)handler.recovery={credentialsChanged};return handler;
  },[recovery,busy,credentialsChanged]);
  useEffect(()=>{alive.current=true;heading.current?.focus({preventScroll:true});return()=>{alive.current=false;generation.current++;};},[]);
  useEffect(()=>{onNavigationGuardChange?.(needsGuard?guard:null);return()=>onNavigationGuardChange?.(null);},[needsGuard,guard,onNavigationGuardChange]);
  function fail(value:PublicError){setError(value);if(authErrors.has(value.code))setRecovery(true);}
  function finish(creator:CreatorDetail){onNavigationGuardChange?.(null);onSaved(creator);}
  function review(){
    if(phase!=='editing'||inFlight.current)return;
    const id=account.trim(),homepage=url.trim();
    if((!id&&!homepage)||id.length>128||(homepage&&(!validWebURL(homepage)||homepage.length>2048))){fail({code:'request_invalid',message:'Enter a new account ID or an HTTP(S) homepage without credentials.',retryable:false});return;}
    setFrozen({platform,...(id?{account_id:id}:{}),...(homepage?{profile_url:homepage}:{}),expected_revision:base.revision,confirmed:true});setError(null);setPhase('confirming');
  }
  async function readCurrent(complete=false){
    if(inFlight.current)return;inFlight.current=true;const token=generation.current;setPhase('checking');setError(null);
    try{
      const result=await api.creators.detail(base.id);
      if(!alive.current||token!==generation.current)return;
      if(result.ok){setCurrent(result.data);if(complete)finish(result.data);else setPhase('review-current');}
      else{fail(result.error);setPhase('unconfirmed');}
    }catch{if(alive.current&&token===generation.current){fail(readNetworkError);setPhase('unconfirmed');}}
    finally{inFlight.current=false;}
  }
  async function change(){
    if(inFlight.current||phase!=='confirming'||!frozen)return;
    inFlight.current=true;const token=generation.current;setPhase('saving');setError(null);
    try{
      const result=await api.creators.rebind({id:base.id,data:frozen});
      if(!alive.current||token!==generation.current)return;
      if(result.ok){inFlight.current=false;await readCurrent(true);}
      else{
        fail(result.error);
        setPhase(result.error.code==='creator_revision_conflict'||result.error.code==='creator_identity_changed'||!certainlyRejected(result.error.code)?'unconfirmed':'editing');
      }
    }catch{if(alive.current&&token===generation.current){fail(mutationNetworkError);setPhase('unconfirmed');}}
    finally{inFlight.current=false;}
  }
  const closed=phase!=='editing';
  return <section className="creator-editor"><div className="game-editor-heading"><button className="text-button" onClick={()=>needsGuard?guard(onCancel):onCancel()}><Icon name="arrow"/>Back to creator</button></div><h2 ref={heading} tabIndex={-1}>Change account identity</h2>
    <section className="settings-card"><h3>Current account</h3><IdentitySummary creator={base}/></section>
    {error&&<ErrorNotice error={error}/>}{busy&&<Loading label={phase==='saving'?'Changing identity…':'Reading current identity…'}/>}
    {unresolved&&<section className="game-uncertain"><h3>Review current identity</h3><p>Check which account is linked before making another change.</p><button className="button secondary" onClick={()=>void readCurrent()}>Check current identity</button>
      {current&&<><IdentitySummary creator={current}/><div className="button-row"><button className="button secondary" onClick={()=>finish(current)}>Use current account</button><button className="button primary" onClick={()=>{setBase(current);setCurrent(null);setFrozen(null);setPhase('editing');setError(null);}}>Review change against current record</button></div></>}
    </section>}
    <form onSubmit={event=>{event.preventDefault();review();}}><fieldset className="creator-form" disabled={closed}><legend>New account</legend><div className="creator-form-grid">
      <div className="form-field"><label htmlFor="new-creator-platform">New platform</label><select id="new-creator-platform" value={platform} onChange={event=>setPlatform(event.target.value as CreatorPlatform)}>{CREATOR_PLATFORMS.map(value=><option key={value}>{value}</option>)}</select></div>
      <div className="form-field"><label htmlFor="new-creator-account">New account ID</label><input id="new-creator-account" value={account} onChange={event=>setAccount(event.target.value)}/></div>
      <div className="form-field creator-wide-field"><label htmlFor="new-creator-url">New homepage URL</label><input id="new-creator-url" value={url} onChange={event=>setURL(event.target.value)}/></div>
    </div>{(platform==='twitch'||platform==='instagram')&&<span className="status-badge">Manual account · Analysis unavailable</span>}</fieldset><div className="game-editor-footer"><button type="button" className="button secondary" disabled={closed} onClick={()=>needsGuard?guard(onCancel):onCancel()}>Cancel</button><button className="button primary" disabled={closed}>Review identity change</button></div></form>
    {recovery&&onConnectionRepair&&!busy&&<button className="button secondary" onClick={onConnectionRepair}>Repair connection</button>}
    {phase==='confirming'&&frozen&&<CreatorDialog title="Change account identity?" onClose={()=>setPhase('editing')} actions={<><button className="button secondary" onClick={()=>setPhase('editing')}>Keep current identity</button><button className="button primary" onClick={()=>void change()}>Change identity</button></>}><div className="creator-identity-compare"><section><h3>From</h3><IdentitySummary creator={base}/></section><section><h3>To</h3><strong>{frozen.platform}</strong><p>{frozen.account_id||'URL-only identity'}</p>{frozen.profile_url&&<p>{frozen.profile_url}</p>}</section></div><p>Existing emails and works become read-only history. Source facts and analysis are cleared; manual notes stay.</p></CreatorDialog>}
    {navigation&&<CreatorDialog title="Unsaved identity change" onClose={()=>setNavigation(null)} actions={<><button className="button secondary" onClick={()=>setNavigation(null)}>Continue editing</button><button className="text-button" disabled={busy||unresolved} onClick={()=>{const proceed=navigation;setNavigation(null);onNavigationGuardChange?.(null);onCancel();if(proceed!==onCancel)proceed();}}>Discard changes</button></>}><p>{unresolved?'Check the unconfirmed identity change before leaving.':'Your new identity has not been saved.'}</p></CreatorDialog>}
  </section>;
}
