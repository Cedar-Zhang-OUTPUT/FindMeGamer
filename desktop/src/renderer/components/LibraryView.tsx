import { useCallback, useEffect, useRef, useState } from 'react';
import type { DesktopBridge } from '../../shared/bridge';
import type { NavigationGuard } from '../../shared/games';
import { GameLibrary } from './GameLibrary';
import { CreatorLibrary } from './creators/CreatorLibrary';

type Kind = 'creators' | 'games';
export function LibraryView({ api, active, onNavigationGuardChange, onConnectionRepair }: { api: DesktopBridge; active: boolean; onNavigationGuardChange?: (guard: NavigationGuard | null) => void; onConnectionRepair?: () => void }) {
  const [kind,setKind]=useState<Kind>('creators');
  const selected=useRef(kind);selected.current=kind;
  const guards=useRef<Record<Kind,NavigationGuard|null>>({creators:null,games:null});
  const tabScroll=useRef({creators:0,games:0});
  const registerCreatorGuard=useCallback((guard:NavigationGuard|null)=>{guards.current.creators=guard;if(selected.current==='creators')onNavigationGuardChange?.(guard);},[onNavigationGuardChange]);
  const registerGameGuard=useCallback((guard:NavigationGuard|null)=>{guards.current.games=guard;if(selected.current==='games')onNavigationGuardChange?.(guard);},[onNavigationGuardChange]);
  useEffect(()=>{onNavigationGuardChange?.(guards.current[kind]);},[kind,onNavigationGuardChange]);
  useEffect(()=>()=>onNavigationGuardChange?.(null),[onNavigationGuardChange]);
  function switchTab(target:Kind){
    if(target===kind)return;
    const proceed=()=>{
      const scroller=document.querySelector<HTMLElement>('.main-scroll');tabScroll.current[kind]=scroller?.scrollTop??0;
      selected.current=target;setKind(target);onNavigationGuardChange?.(guards.current[target]);
      const control=document.getElementById(`tab-${target}`);control?.focus({preventScroll:true});
      requestAnimationFrame(()=>{if(scroller)scroller.scrollTop=tabScroll.current[target];if(document.activeElement===document.body)control?.focus({preventScroll:true});});
    };
    const guard=guards.current[kind];if(guard)guard(proceed);else proceed();
  }
  return <><div className="page-heading"><h1>Library</h1></div><div className="library-navigation"><div className="segmented" role="tablist" aria-label="Library type">{(['creators','games'] as const).map(target=><button key={target} role="tab" id={`tab-${target}`} aria-controls={`panel-${target}`} aria-selected={kind===target} tabIndex={kind===target?0:-1} onClick={()=>switchTab(target)} onKeyDown={event=>{
    if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();switchTab(event.key==='Home'?'creators':event.key==='End'?'games':kind==='creators'?'games':'creators');}
  }}>{target==='creators'?'Creators':'Games'}</button>)}</div></div>
  <div role="tabpanel" id="panel-creators" aria-labelledby="tab-creators" hidden={kind!=='creators'}><CreatorLibrary api={api} active={active&&kind==='creators'} onNavigationGuardChange={registerCreatorGuard} onConnectionRepair={onConnectionRepair}/></div>
  <div role="tabpanel" id="panel-games" aria-labelledby="tab-games" hidden={kind!=='games'}><GameLibrary api={api} active={active&&kind==='games'} onNavigationGuardChange={registerGameGuard} onConnectionRepair={onConnectionRepair}/></div></>;
}
