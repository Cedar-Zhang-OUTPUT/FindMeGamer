import {useEffect,useRef,useState} from 'react';
import {CreatorDialog} from '../creators/CreatorDialog';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {GameDetail,NavigationGuard} from '../../../shared/games';
import type {CreatorDetail} from '../../../shared/creators';
import {ErrorNotice} from '../Primitives';
import './sourceImport.css';
import {useAnalyze} from './AnalyzeProvider';
import {GameEditor} from '../GameEditor';

export type SourceTarget={kind:'game';game?:GameDetail}|{kind:'youtube';creator:CreatorDetail};
type Command={kind:'game';input:Parameters<DesktopBridge['analysis']['steamImport']>[0];created:number}|{kind:'youtube';input:Parameters<DesktopBridge['analysis']['bindYouTube']>[0];created:number};
type State={kind:'editing'}|{kind:'submitting';command:Command}|{kind:'failed'|'uncertain'|'fenced';command:Command;error:PublicError};
const unknown:PublicError={code:'analysis_write_unknown',message:'The source may have been saved. Check the same request before changing it.',retryable:false};
export function validSourceURL(value:string,kind:SourceTarget['kind']):boolean {
 try{const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||u.port||u.hash)return false;
 return kind==='game'?u.hostname==='store.steampowered.com'&&/^\/app\/[1-9][0-9]*(?:\/[^\s]*)?$/.test(u.pathname):['youtube.com','www.youtube.com'].includes(u.hostname)&&/^\/(?:channel\/UC[A-Za-z0-9_-]+|@[A-Za-z0-9_.-]+)\/?$/.test(u.pathname);
 }catch{return false;}
}
export function SourceImport({api,target,onSaved,onClose,onNavigationGuardChange,onConnectionRepair,onLockChange,allowArchive=true,onManual}:{api:DesktopBridge;target:SourceTarget;onSaved:(record:GameDetail|CreatorDetail)=>void;onClose:()=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void;onLockChange?:(locked:boolean)=>void;allowArchive?:boolean;onManual?:()=>void}) {
 const analysis=useAnalyze();const [reviewing,setReviewing]=useState(false);
 const [manual,setManual]=useState(false);
 const [url,setURL]=useState(target.kind==='youtube'?target.creator.profile_url??'':target.game?.source_identity.canonical_url??'');
 const [state,setState]=useState<State>({kind:'editing'}),[clock,setClock]=useState(Date.now());
 const alive=useRef(true),epoch=useRef(0),busy=useRef(false),current=useRef(state);current.current=state;
 const request=useRef<Command|null>(null);
 const [leaving,setLeaving]=useState(false);const pendingNavigation=useRef<(()=>void)|null>(null);
 const locked=state.kind==='submitting'||state.kind==='uncertain'||state.kind==='fenced';
 useEffect(()=>{onLockChange?.(locked||manual);return()=>onLockChange?.(false);},[locked,manual,onLockChange]);
 useEffect(()=>{alive.current=true;const timer=window.setInterval(()=>setClock(Date.now()),30_000);return()=>{alive.current=false;epoch.current++;clearInterval(timer);};},[]);
 useEffect(()=>{if(manual)return;const guard:NavigationGuard=proceed=>{pendingNavigation.current=proceed;setLeaving(true);};guard.recovery={credentialsChanged:()=>{epoch.current++;busy.current=false;const command=request.current;if(command)setState({kind:'fenced',command,error:{code:'connection_changed',message:'Connection changed. Check the source in the original workspace.',retryable:false}});}};onNavigationGuardChange?.(url||state.kind!=='editing'?guard:null);return()=>onNavigationGuardChange?.(null);},[onNavigationGuardChange,manual,url,state.kind]);
 useEffect(()=>{const prevent=(event:BeforeUnloadEvent)=>{if(url||current.current.kind!=='editing'){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent);},[url]);
 async function submit(){
  if(busy.current||state.kind==='fenced')return;
  let command=request.current;
  if(command&&Date.now()-command.created>=24*60*60*1000)return;
  if(!command){if(!validSourceURL(url.trim(),target.kind))return;const idempotencyKey=crypto.randomUUID(),created=Date.now();
   command=target.kind==='game'?{kind:'game',created,input:Object.freeze({url:url.trim(),idempotencyKey,...(target.game?{gameId:target.game.id,expectedRevision:target.game.revision}:{})})}:{kind:'youtube',created,input:Object.freeze({url:url.trim(),creatorId:target.creator.id,expectedRevision:target.creator.revision,idempotencyKey})};request.current=Object.freeze(command);
  }
  const checking=state.kind==='uncertain';busy.current=true;const token=++epoch.current;setState({kind:'submitting',command});
  try{const result=command.kind==='game'?await api.analysis.steamImport(command.input):await api.analysis.bindYouTube(command.input);if(!alive.current||token!==epoch.current)return;
   if(result.ok){request.current=null;onSaved(result.data);return;}
   setState({kind:result.error.code==='connection_changed'?'fenced':checking||result.error.code==='analysis_write_unknown'?'uncertain':'failed',command,error:result.error});
  }catch{if(alive.current&&token===epoch.current)setState({kind:'uncertain',command,error:unknown});}finally{if(token===epoch.current)busy.current=false;}
 }
 const expired=state.kind!=='editing'&&clock-state.command.created>=24*60*60*1000;
 if(manual&&target.kind==='game')return <section className="steam-manual-entry"><label>Original Steam URL<input readOnly value={url}/></label><GameEditor api={api} initial={target.game??null} onSaved={onSaved} onCancel={()=>setManual(false)} onNavigationGuardChange={onNavigationGuardChange} onConnectionRepair={onConnectionRepair}/></section>;
 return <section className="source-import" aria-label={target.kind==='game'?'Import Steam source':'Bind YouTube channel'}><span className="eyebrow">{target.kind==='game'?'STEAM':'YOUTUBE'}</span><h2>{target.kind==='game'?'Import game source':'Bind channel'}</h2>
 <form onSubmit={event=>{event.preventDefault();void submit();}}><label>{target.kind==='game'?'Steam URL':'YouTube channel URL'}<input type="url" value={url} maxLength={2048} disabled={locked} placeholder={target.kind==='game'?'https://store.steampowered.com/app/…':'https://www.youtube.com/@…'} onChange={event=>{request.current=null;setState({kind:'editing'});setURL(event.target.value);}}/></label>
 <p className="muted">{target.kind==='game'?'Source only · AI analysis is a separate action.':'Binds this profile · Previous-identity works and contacts stay in history.'}</p>
 {state.kind!=='editing'&&state.kind!=='submitting'&&<ErrorNotice error={state.error}/>}
 {expired&&<p role="alert">Request check expired. Inspect the saved source before starting another operation.</p>}
 {target.kind==='game'&&state.kind==='failed'&&<button type="button" className="button secondary" onClick={()=>onManual?onManual():setManual(true)}>{target.game?'Edit saved game manually':'Enter manually'}</button>}
 <div className="source-import-actions"><button type="submit" className="button primary" disabled={state.kind==='submitting'||state.kind==='fenced'||expired||!validSourceURL(url.trim(),target.kind)}>{state.kind==='submitting'?'Saving source…':state.kind==='uncertain'?'Check same request':state.kind==='failed'?'Retry source request':target.kind==='game'?'Import source':'Bind channel'}</button>{!locked&&<button type="button" className="button secondary" onClick={onClose}>Cancel</button>}{state.kind!=='editing'&&state.kind!=='submitting'&&onConnectionRepair&&['workspace_key_invalid','not_connected','secure_storage_unavailable'].includes(state.error.code)&&<button type="button" className="button secondary" onClick={onConnectionRepair}>Connection settings</button>}{allowArchive&&(state.kind==='uncertain'||state.kind==='fenced')&&<button type="button" className="button secondary" onClick={()=>setReviewing(true)}>Keep unresolved request</button>}</div>
 {reviewing&&state.kind!=='editing'&&state.kind!=='submitting'&&<div role="alertdialog" aria-label="Retain unresolved source request"><h3>This request may already have completed.</h3><p>Keep its original input and key in Analysis tasks. Check the original workspace before importing again.</p><button type="button" className="button secondary" onClick={()=>setReviewing(false)}>Keep checking</button><button type="button" className="button secondary" onClick={()=>{analysis.retainUnconfirmed({title:target.kind==='game'?'Steam source import':'YouTube binding',request:state.command,startedAt:state.command.created,originalWorkspace:state.kind==='fenced',...(target.kind==='youtube'?{profile:{kind:'creators' as const,id:target.creator.id}}:target.game?{profile:{kind:'games' as const,id:target.game.id}}:{})});onClose();}}>Save for review and leave</button></div>}
 </form>{leaving&&<CreatorDialog role="alertdialog" title="Leave source import" onClose={()=>{setLeaving(false);pendingNavigation.current=null;}} actions={<><button className="button secondary" onClick={()=>{setLeaving(false);pendingNavigation.current=null;}}>Keep importing</button>{!locked&&<button className="button secondary" onClick={()=>{const proceed=pendingNavigation.current;pendingNavigation.current=null;setLeaving(false);onClose();proceed?.();}}>Discard link and leave</button>}</>}><p>{locked?'Resolve this source request first':'Leave source import?'}</p></CreatorDialog>}</section>;
}
