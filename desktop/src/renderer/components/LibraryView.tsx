import { useCallback, useEffect, useRef, useState } from 'react';
import type { DesktopBridge } from '../../shared/bridge';
import type { GameDetail, NavigationGuard } from '../../shared/games';
import { GameLibrary } from './GameLibrary';
import { CreatorLibrary } from './creators/CreatorLibrary';
import {AnalyzeProvider,useAnalyze} from './analyze/AnalyzeProvider';

type Kind = 'creators' | 'games';
function AnalysisTasksButton(){const analyze=useAnalyze();return <button className="button secondary" onClick={analyze.showTasks}>Analysis tasks{analyze.activeCount>0?` · ${analyze.activeCount}`:''}</button>;}
export function LibraryView({ api, active, onNavigationGuardChange, onConnectionRepair,onCollectionSettings,onUseForMatch }: { api: DesktopBridge; active: boolean; onNavigationGuardChange?: (guard: NavigationGuard | null) => void; onConnectionRepair?: () => void;onCollectionSettings?:()=>void;onUseForMatch?:(game:GameDetail)=>void }) {
  const [kind,setKind]=useState<Kind>('creators');
  const [views,setViews]=useState<Record<Kind,'list'|'record'>>({creators:'list',games:'list'});
  const creatorViewChanged=useCallback((view:'list'|'record')=>setViews(previous=>previous.creators===view?previous:{...previous,creators:view}),[]);
  const gameViewChanged=useCallback((view:'list'|'record')=>setViews(previous=>previous.games===view?previous:{...previous,games:view}),[]);
  const [profileRequest,setProfileRequest]=useState<{kind:Kind;id:string;nonce:number}|null>(null);
  const selected=useRef(kind);selected.current=kind;
  const guards=useRef<Record<Kind,NavigationGuard|null>>({creators:null,games:null});
  const analyzeGuard=useRef<NavigationGuard|null>(null);
  const tabScroll=useRef({creators:0,games:0});
  const publishGuard=useCallback(()=>{const child=guards.current[selected.current],analysis=analyzeGuard.current;if(!child&&!analysis){onNavigationGuardChange?.(null);return;}const combined:NavigationGuard=proceed=>child?child(proceed):proceed();if(analysis?.recovery||child?.recovery)combined.recovery={credentialsChanged:()=>{analysis?.recovery?.credentialsChanged();child?.recovery?.credentialsChanged();}};onNavigationGuardChange?.(combined);},[onNavigationGuardChange]);
  const registerCreatorGuard=useCallback((guard:NavigationGuard|null)=>{guards.current.creators=guard;publishGuard();},[publishGuard]);
  const registerGameGuard=useCallback((guard:NavigationGuard|null)=>{guards.current.games=guard;publishGuard();},[publishGuard]);
  const registerAnalyzeGuard=useCallback((guard:NavigationGuard|null)=>{analyzeGuard.current=guard;publishGuard();},[publishGuard]);
  useEffect(()=>{publishGuard();},[kind,publishGuard]);
  useEffect(()=>()=>onNavigationGuardChange?.(null),[onNavigationGuardChange]);
  function switchTab(target:Kind){
    if(target===kind)return;
    const proceed=()=>{
      const scroller=document.querySelector<HTMLElement>('.main-scroll');tabScroll.current[kind]=scroller?.scrollTop??0;
      selected.current=target;setKind(target);publishGuard();
      const control=document.getElementById(`tab-${target}`);control?.focus({preventScroll:true});
      requestAnimationFrame(()=>{if(scroller)scroller.scrollTop=tabScroll.current[target];if(document.activeElement===document.body)control?.focus({preventScroll:true});});
    };
    const guard=guards.current[kind];if(guard)guard(proceed);else proceed();
  }
  function openProfile(profile:{kind:Kind;id:string}){const proceed=()=>{selected.current=profile.kind;setKind(profile.kind);setProfileRequest({...profile,nonce:Date.now()});publishGuard();};const guard=guards.current[selected.current];if(guard)guard(proceed);else proceed();}
  return <AnalyzeProvider api={api} onConnectionRepair={onConnectionRepair} onCollectionSettings={onCollectionSettings} onOpenProfile={openProfile} onNavigationGuardChange={registerAnalyzeGuard}><div className={`library-topbar ${views[kind]==='record'?'is-record':''}`} role="group" aria-label="Library navigation"><div className="library-title">{views[kind]==='record'?<span>Library</span>:<h1>Library</h1>}</div><div className="library-navigation"><div className="segmented" role="tablist" aria-label="Library type">{(['creators','games'] as const).map(target=><button key={target} role="tab" id={`tab-${target}`} aria-controls={`panel-${target}`} aria-selected={kind===target} tabIndex={kind===target?0:-1} onClick={()=>switchTab(target)} onKeyDown={event=>{
    if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();switchTab(event.key==='Home'?'creators':event.key==='End'?'games':kind==='creators'?'games':'creators');}
  }}>{target==='creators'?'Creators':'Games'}</button>)}</div></div><AnalysisTasksButton/></div>
  <div role="tabpanel" id="panel-creators" aria-labelledby="tab-creators" hidden={kind!=='creators'}><CreatorLibrary api={api} active={active&&kind==='creators'} onNavigationGuardChange={registerCreatorGuard} onConnectionRepair={onConnectionRepair} openRequest={profileRequest?.kind==='creators'?profileRequest:undefined} onViewChange={creatorViewChanged}/></div>
  <div role="tabpanel" id="panel-games" aria-labelledby="tab-games" hidden={kind!=='games'}><GameLibrary api={api} active={active&&kind==='games'} onUseForMatch={onUseForMatch} onNavigationGuardChange={registerGameGuard} onConnectionRepair={onConnectionRepair} openRequest={profileRequest?.kind==='games'?profileRequest:undefined} onViewChange={gameViewChanged}/></div></AnalyzeProvider>;
}
