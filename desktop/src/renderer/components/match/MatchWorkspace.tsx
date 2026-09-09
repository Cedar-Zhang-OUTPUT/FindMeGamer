import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {CreatorDetail} from '../../../shared/creators';
import type {GameDetail,NavigationGuard} from '../../../shared/games';
import type {ActivityPage,ActivityView} from '../../../shared/match';
import {EmptyState,ErrorNotice,Icon,Loading} from '../Primitives';
import {CreatorRecord,type CreatorRecordProps} from '../creators/CreatorRecord';
import {CreatorEditor} from '../creators/CreatorEditor';
import {CreatorIdentityEditor} from '../creators/CreatorIdentityEditor';
import type {EditContext} from '../creators/creatorDraft';
import {MatchActivity} from './MatchActivity';
import {NewActivity} from './NewActivity';
import {matchReadError} from './matchMutation';
import {taskDate} from './matchStatus';
import './matchWorkspace.css';
import {AnalyzeProvider,useAnalyze} from '../analyze/AnalyzeProvider';

type Section='profile'|'emails'|'works';
type CreatorRoute={kind:'loading';id:string;section:Section;error:PublicError|null}|{kind:'detail';creator:CreatorDetail;section:Section;saved?:boolean}|{kind:'editor';creator:CreatorDetail;section:Section;initial:EditContext}|{kind:'identity';creator:CreatorDetail;section:Section};
type Route={kind:'list'}|{kind:'new';game?:GameDetail;nonce?:number}|{kind:'activity';id:string;creator:CreatorRoute|null};
type Owner='activity'|'new'|'creator'|'none';
const scroller=()=>document.querySelector<HTMLElement>('.main-scroll');
function gameName(activity:ActivityView){const game=activity.source_snapshot.game;return game&&typeof game==='object'&&!Array.isArray(game)&&typeof game.name==='string'?game.name:'Saved game';}

interface MatchWorkspaceProps {api:DesktopBridge;active:boolean;surface?:'match'|'outreach';onShowMatch?:()=>void;onShowOutreach?:()=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void;onCollectionSettings?:()=>void;onSMTPSettings?:()=>void;gameRequest?:{game:GameDetail;nonce:number};onGameRequestHandled?:()=>void}
export function MatchWorkspace(props:MatchWorkspaceProps){
  const guards=useRef<{task:NavigationGuard|null;analysis:NavigationGuard|null}>({task:null,analysis:null});
  const publish=useRef(props.onNavigationGuardChange);publish.current=props.onNavigationGuardChange;
  const register=useCallback((owner:'task'|'analysis',value:NavigationGuard|null)=>{
    guards.current[owner]=value;const {task,analysis}=guards.current;
    if(!task&&!analysis){publish.current?.(null);return;}
    const combined:NavigationGuard=proceed=>task?task(proceed):proceed();
    if(task?.recovery||analysis?.recovery)combined.recovery={credentialsChanged:()=>{task?.recovery?.credentialsChanged();analysis?.recovery?.credentialsChanged();}};
    publish.current?.(combined);
  },[]);
  const taskGuard=useCallback((value:NavigationGuard|null)=>register('task',value),[register]);
  const analysisGuard=useCallback((value:NavigationGuard|null)=>register('analysis',value),[register]);
  return <AnalyzeProvider api={props.api} onNavigationGuardChange={analysisGuard} onConnectionRepair={props.onConnectionRepair} onCollectionSettings={props.onCollectionSettings}><MatchWorkspaceContent {...props} onNavigationGuardChange={taskGuard}/></AnalyzeProvider>;
}
function MatchWorkspaceContent({api,active,onNavigationGuardChange,onConnectionRepair,onCollectionSettings,onSMTPSettings,gameRequest,onGameRequestHandled,surface='match',onShowMatch,onShowOutreach}:MatchWorkspaceProps){
  const analysis=useAnalyze();
  const [route,setRoute]=useState<Route>({kind:'list'}),[page,setPage]=useState<ActivityPage|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<PublicError|null>(null),[failedOffset,setFailedOffset]=useState<number|null>(null);
  const priorSurface=useRef(surface);
  useEffect(()=>{if(priorSurface.current===surface)return;priorSurface.current=surface;creatorGeneration.current++;setRoute(current=>current.kind==='new'?{kind:'list'}:current.kind==='activity'?{...current,creator:null}:current);},[surface]);
  const listRoot=useRef<HTMLDivElement>(null),activityRoot=useRef<HTMLDivElement>(null),listScroll=useRef(0),activityScroll=useRef(0),selectedActivity=useRef<string|null>(null),creatorOpener=useRef<HTMLElement|null>(null);
  const pageGeneration=useRef(0),creatorGeneration=useRef(0),loaded=useRef(false),pendingPage=useRef(false),alive=useRef(true),restoreFrame=useRef<number|null>(null);
  const guards=useRef<Record<Owner,NavigationGuard|null>>({activity:null,new:null,creator:null,none:null});
  const overlay=route.kind==='activity'?route.creator:null;
  const owner:Owner=route.kind==='new'?'new':route.kind==='activity'?overlay?overlay.kind==='editor'||overlay.kind==='identity'?'creator':'none':'activity':'none';
  const ownerRef=useRef(owner);ownerRef.current=owner;
  const retainsActivity=useRef(route.kind==='activity');retainsActivity.current=route.kind==='activity';
  const publish=useRef(onNavigationGuardChange);publish.current=onNavigationGuardChange;
  const handledGameRequest=useRef<number|null>(null);
  useEffect(()=>{if(!active||!gameRequest||handledGameRequest.current===gameRequest.nonce)return;handledGameRequest.current=gameRequest.nonce;creatorGeneration.current++;setRoute({kind:'new',game:gameRequest.game,nonce:gameRequest.nonce});onGameRequestHandled?.();const scroll=scroller();if(scroll)scroll.scrollTop=0;},[active,gameRequest,onGameRequestHandled]);
  // Creator inspection is a detour: its parent draft still owns exit safety.
  const publishGuard=useCallback(()=>{
    const visible=guards.current[ownerRef.current],retained=retainsActivity.current?guards.current.activity:null;
    const parent=retained!==visible?retained:null;
    if(!visible){publish.current?.(parent);return;}
    if(!parent){publish.current?.(visible);return;}
    const combined:NavigationGuard=proceed=>visible(()=>parent(proceed));
    if(visible.recovery||parent.recovery)combined.recovery={credentialsChanged:()=>{visible.recovery?.credentialsChanged();parent.recovery?.credentialsChanged();}};
    publish.current?.(combined);
  },[]);
  const register=useCallback((source:Owner,guard:NavigationGuard|null)=>{guards.current[source]=guard;if(ownerRef.current===source||source==='activity'&&retainsActivity.current)publishGuard();},[publishGuard]);
  const activityGuard=useCallback((guard:NavigationGuard|null)=>register('activity',guard),[register]);
  const newGuard=useCallback((guard:NavigationGuard|null)=>register('new',guard),[register]);
  const creatorGuard=useCallback((guard:NavigationGuard|null)=>register('creator',guard),[register]);
  useLayoutEffect(()=>{publishGuard();},[owner,route.kind,onNavigationGuardChange,publishGuard]);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;pageGeneration.current++;creatorGeneration.current++;publish.current?.(null);if(restoreFrame.current!==null)cancelAnimationFrame(restoreFrame.current);};},[]);
  const pageRef=useRef(page);pageRef.current=page;
  const load=useCallback(async(offset:number)=>{
    const token=++pageGeneration.current;pendingPage.current=true;setBusy(true);setError(null);setFailedOffset(null);
    try{
      const result=await api.match.activities({limit:50,offset});if(!alive.current||token!==pageGeneration.current)return;
      if(result.ok){const last=Math.max(0,Math.floor((result.data.total-1)/50)*50);if(offset>last){void load(last);return;}setPage(result.data);}else{setError(result.error);setFailedOffset(offset);}
      loaded.current=true;
    }catch{if(!alive.current||token!==pageGeneration.current)return;setError(matchReadError);setFailedOffset(offset);loaded.current=true;}
    if(alive.current&&token===pageGeneration.current){pendingPage.current=false;setBusy(false);}
  },[api.match]);
  useEffect(()=>{
    if(active&&!loaded.current)void load(pageRef.current?.offset??0);
    return()=>{pageGeneration.current++;if(pendingPage.current){pendingPage.current=false;loaded.current=false;}setBusy(false);};
  },[active,load]);
  function restore(root:HTMLDivElement|null,position:number,target:HTMLElement|null){
    if(restoreFrame.current!==null)cancelAnimationFrame(restoreFrame.current);
    restoreFrame.current=requestAnimationFrame(()=>{
      restoreFrame.current=null;if(!root||root.closest('[hidden]'))return;const scroll=scroller();if(scroll)scroll.scrollTop=position;
      // The opener can remain disabled during a fresh relationship GET. Keep
      // keyboard context on a visible tab instead of silently focusing body.
      const usable=(node:HTMLElement|null)=>node?.isConnected&&!node.matches(':disabled')&&!node.closest('[hidden]');
      const fallback=Array.from(root.querySelectorAll<HTMLElement>('[role=tab][aria-selected=true]')).find(node=>usable(node))??Array.from(root.querySelectorAll<HTMLElement>('button')).find(node=>usable(node));
      (usable(target)?target:fallback)?.focus({preventScroll:true});
    });
  }
  function toList(){creatorGeneration.current++;setRoute({kind:'list'});const row=Array.from(listRoot.current?.querySelectorAll<HTMLElement>('[data-activity-id]')??[]).find(node=>node.dataset.activityId===selectedActivity.current);restore(listRoot.current,listScroll.current,row??null);}
  function openActivity(id:string){listScroll.current=scroller()?.scrollTop??0;selectedActivity.current=id;setRoute({kind:'activity',id,creator:null});const scroll=scroller();if(scroll)scroll.scrollTop=0;}
  function created(activity:ActivityView){loaded.current=false;openActivity(activity.id);void load(pageRef.current?.offset??0);}
  function backToActivity(){creatorGeneration.current++;setRoute(current=>current.kind==='activity'?{...current,creator:null}:current);restore(activityRoot.current,activityScroll.current,creatorOpener.current);}
  async function openCreator(id:string,section:Section,retry=false){
    if(!retry){creatorOpener.current=document.activeElement as HTMLElement;activityScroll.current=scroller()?.scrollTop??0;const scroll=scroller();if(scroll)scroll.scrollTop=0;}
    const token=++creatorGeneration.current;setRoute(current=>current.kind==='activity'?{...current,creator:{kind:'loading',id,section,error:null}}:current);
    try{const result=await api.creators.detail(id);if(!alive.current||token!==creatorGeneration.current)return;setRoute(current=>current.kind==='activity'?{...current,creator:result.ok?{kind:'detail',creator:result.data,section}:{kind:'loading',id,section,error:result.error}}:current);}
    catch{if(alive.current&&token===creatorGeneration.current)setRoute(current=>current.kind==='activity'?{...current,creator:{kind:'loading',id,section,error:matchReadError}}:current);}
  }
  function edit(target:Parameters<CreatorRecordProps['onEdit']>[0]){
    if(route.kind!=='activity'||overlay?.kind!=='detail')return;
    const section:Section=target.kind==='contact'?'emails':target.kind==='work'?'works':'profile';
    setRoute({...route,creator:target.kind==='identity'?{kind:'identity',creator:overlay.creator,section}:{kind:'editor',creator:overlay.creator,section,initial:target.kind==='creator'?{kind:'creator',base:overlay.creator}:{kind:target.kind,creator:overlay.creator,base:target.base??null}}});
  }
  function cancelEdit(){if(route.kind==='activity'&&(overlay?.kind==='editor'||overlay?.kind==='identity'))setRoute({...route,creator:{kind:'detail',creator:overlay.creator,section:overlay.section}});}
  function saved(creator:CreatorDetail){creatorGeneration.current++;setRoute(current=>current.kind==='activity'?{...current,creator:{kind:'detail',creator,section:current.creator&&'section' in current.creator?current.creator.section:'profile',saved:true}}:current);}
  function requestBack(){const guard=guards.current[ownerRef.current];if(guard)guard(backToActivity);else backToActivity();}
  return <div className="match-workspace">
    <div className="analysis-entry-actions"><button className="button secondary" onClick={analysis.showTasks}>Analysis tasks</button>{surface==='outreach'&&onSMTPSettings&&<button className="button secondary" onClick={onSMTPSettings}>Email settings</button>}</div>
    <div ref={listRoot} hidden={route.kind!=='list'}>
      <div className="page-heading match-workspace-heading"><h1>{surface==='outreach'?'Outreach':'Match'}</h1>{surface==='outreach'?<button className="button primary" onClick={onShowMatch}>Find creators</button>:<button className="button primary" onClick={()=>{listScroll.current=scroller()?.scrollTop??0;setRoute({kind:'new'});}}>New activity</button>}</div>
      <div className="match-list-caption"><span>{page?`${page.items.length?page.offset+1:0}–${page.items.length?page.offset+page.items.length:0} of ${page.total}`:''}</span><button className="icon-button" aria-label="Refresh activities" title="Refresh activities" disabled={busy} onClick={()=>void load(page?.offset??0)}><Icon name="refresh"/></button></div>
      {busy&&<Loading label="Loading activities…"/>}{page&&<ul className="match-activity-list" aria-label="Activities">{page.items.map(activity=><li key={activity.id}><button className="match-activity-row" data-activity-id={activity.id} aria-label={`Open ${activity.name}`} onClick={()=>openActivity(activity.id)}><span><strong>{activity.name}</strong><span>{gameName(activity)}</span></span><time dateTime={activity.created_at}>{taskDate(activity.created_at)}</time><Icon name="chevron"/></button></li>)}</ul>}
      {error&&<ErrorNotice error={error} onRetry={()=>void load(failedOffset??page?.offset??0)}/>}{!busy&&!error&&page?.items.length===0&&<EmptyState title="No activities yet"/>}
      {page&&page.total>0&&<div className="match-pagination"><button className="button secondary" disabled={busy||page.offset===0} onClick={()=>void load(Math.max(0,page.offset-50))}>Previous page</button><button className="button secondary" disabled={busy||page.offset+page.limit>=page.total} onClick={()=>void load(page.offset+50)}>Next page</button></div>}
    </div>
    {route.kind==='new'&&<NewActivity key={route.nonce??'manual'} api={api} initialGame={route.game} onCreated={created} onCancel={toList} onNavigationGuardChange={newGuard} onConnectionRepair={onConnectionRepair}/>}
    {route.kind==='activity'&&<><div ref={activityRoot} hidden={Boolean(overlay)}><MatchActivity key={route.id} api={api} activityId={route.id} active={active&&!overlay} surface={surface} onShowMatch={onShowMatch} onShowOutreach={onShowOutreach} onBack={toList} onOpenCreator={(id,section)=>void openCreator(id,section==='contacts'?'emails':section==='works'?'works':'profile')} onNavigationGuardChange={activityGuard} onConnectionRepair={onConnectionRepair} onCollectionSettings={onCollectionSettings} onSMTPSettings={onSMTPSettings}/></div>
      {overlay&&<div className="match-creator-route"><button className="text-button back-button" onClick={requestBack}><Icon name="arrow"/>Back to activity</button>
        {overlay.kind==='loading'&&(overlay.error?<ErrorNotice error={overlay.error} onRetry={()=>void openCreator(overlay.id,overlay.section,true)}/>:<Loading label="Loading creator…"/>)}
        {overlay.kind==='detail'&&<>{overlay.saved&&<p role="status" className="creator-saved-message">Saved</p>}<CreatorRecord key={overlay.creator.id} api={api} creator={overlay.creator} initialSection={overlay.section} invitationActivityId={surface==='outreach'?route.id:undefined} refreshToken={overlay.creator.revision} onBack={backToActivity} onEdit={edit}/></>}
        {overlay.kind==='editor'&&<CreatorEditor api={api} initial={overlay.initial} onSaved={saved} onCancel={cancelEdit} onNavigationGuardChange={creatorGuard} onConnectionRepair={onConnectionRepair}/>}
        {overlay.kind==='identity'&&<CreatorIdentityEditor api={api} initial={overlay.creator} onSaved={saved} onCancel={cancelEdit} onNavigationGuardChange={creatorGuard} onConnectionRepair={onConnectionRepair}/>}
      </div>}
    </>}
  </div>;
}
