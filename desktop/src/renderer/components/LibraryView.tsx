import { useCallback, useRef, useState } from 'react';
import type { DesktopBridge } from '../../shared/bridge';
import type { ProfileKind, ProfileSummary } from '../../shared/library';
import { useLibrary } from '../hooks/useLibrary';
import { analyzedDate, Artwork, EmptyState, ErrorNotice, Icon, Loading } from './Primitives';
import { ProfileDetail } from './ProfileDetail';
import { GameLibrary } from './GameLibrary';
import type { NavigationGuard } from '../../shared/games';

export function LibraryView({ api, active, onNavigationGuardChange, onConnectionRepair }: { api: DesktopBridge; active: boolean; onNavigationGuardChange?: (guard: NavigationGuard | null) => void; onConnectionRepair?: () => void }) {
  const [kind, setKind] = useState<ProfileKind>('creators');
  // Creator remains on the v1 cursor contract. Games owns its v2 offset state.
  const library = useLibrary(api, true, active && kind === 'creators');
  const { state } = library;
  const gameGuard = useRef<NavigationGuard | null>(null);
  const tabScroll = useRef({creators:0,games:0});
  const registerGuard = useCallback((guard: NavigationGuard | null) => {
    gameGuard.current = guard;
    onNavigationGuardChange?.(guard);
  }, [onNavigationGuardChange]);
  const [selection, setSelection] = useState<ProfileSummary | null>(null);
  const savedScroll = useRef(0);
  const list = useRef<HTMLDivElement>(null);
  function openProfile(profile: ProfileSummary) {
    const scroller = document.querySelector<HTMLElement>('.main-scroll');
    savedScroll.current = scroller?.scrollTop ?? 0;
    setSelection(profile);
    if (scroller) scroller.scrollTop = 0;
  }
  function backToList() {
    const id = selection?.id;
    setSelection(null);
    requestAnimationFrame(() => {
      const scroller = document.querySelector<HTMLElement>('.main-scroll');
      if (scroller) scroller.scrollTop = savedScroll.current;
      const button = [...(list.current?.querySelectorAll<HTMLButtonElement>('[data-profile-id]') ?? [])].find(element => element.dataset.profileId === id);
      button?.focus({ preventScroll: true });
    });
  }
  function switchTab(target: ProfileKind) {
    if (target === kind) return;
    const proceed = () => {
      const scroller = document.querySelector<HTMLElement>('.main-scroll');
      tabScroll.current[kind] = scroller?.scrollTop ?? 0;
      setKind(target);
      const control = document.getElementById(`tab-${target}`);
      control?.focus({preventScroll:true});
      requestAnimationFrame(() => { if(scroller) scroller.scrollTop = tabScroll.current[target]; if(document.activeElement === document.body) control?.focus({preventScroll:true}); });
    };
    if (kind === 'games' && gameGuard.current) gameGuard.current(proceed); else proceed();
  }
  return <>
    <div ref={list} hidden={selection !== null}>
      <div className="page-heading"><h1>Library</h1>{kind === 'creators' && <span className="read-only-label">Read-only</span>}</div>
      <div className="library-navigation"><div className="segmented" role="tablist" aria-label="Library type">{(['creators', 'games'] as const).map(target => <button key={target} role="tab" id={`tab-${target}`} aria-controls={`panel-${target}`} aria-selected={kind === target} tabIndex={kind === target ? 0 : -1} onClick={() => switchTab(target)} onKeyDown={event => {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'creators' : event.key === 'End' ? 'games' : kind === 'creators' ? 'games' : 'creators'; switchTab(next); }
      }}>{target === 'creators' ? 'Creators' : 'Games'}</button>)}</div>{kind === 'creators' && <div className="platforms"><span className="platform-label"><span className="platform-dot youtube"/>YouTube</span><span className="platform-unavailable">Instagram <span>Not connected</span></span></div>}</div>
      <div role="tabpanel" id="panel-creators" aria-labelledby="tab-creators" hidden={kind !== 'creators'}>
        <div className="library-toolbar"><form className="search-form" role="search" onSubmit={event => { event.preventDefault(); library.search(); }}><Icon name="search"/><input type="search" aria-label="Search creators" placeholder="Search creators…" value={state.draft} onChange={event => library.setDraft(event.target.value)}/><button className="button primary" type="submit">Search</button></form><label className="collection-filter"><input type="checkbox" checked={state.onlyCollection} onChange={event => library.setCollection(event.target.checked)}/><Icon name="collection"/>Saved only</label><button className="icon-button refresh-button" title="Refresh Library" aria-label="Refresh Library" onClick={library.refresh} disabled={state.phase !== 'idle'}><Icon name="refresh"/></button></div>
        {(state.query || state.onlyCollection) && <div className="active-filters"><span>{state.query ? `Results for “${state.query}”` : 'Saved profiles'}</span><button className="text-button" onClick={library.clearFilters}>Clear filters<Icon name="close"/></button></div>}
        {state.phase === 'loading' ? <div className="list-loading"><Loading label="Loading creators…"/><div className="skeleton-rows" aria-hidden="true"><span/><span/><span/></div></div> : <>
          {state.items.length > 0 && <><div className="list-caption"><span>{state.items.length} {state.items.length === 1 ? 'creator' : 'creators'}{state.nextCursor ? ' loaded' : ''}</span><span>Analyzed</span></div><ul className="profile-list" aria-label="Creators">{state.items.map(profile => <li key={profile.id}>
            <button className="profile-row" data-profile-id={profile.id} aria-label={`Open ${profile.name}`} onClick={() => openProfile(profile)}><Artwork url={profile.artworkUrl} name={profile.name} kind={profile.kind}/><span className="profile-row-content"><span className="profile-row-title">{profile.name}{profile.favorite && <Icon name="collection"/>}</span><span className="profile-row-summary">{profile.summary || profile.sourceId}</span>{profile.tags.length > 0 && <span className="row-tags">{profile.tags.slice(0, 3).map((tag, index) => <span key={`${tag}-${index}`}>{tag}</span>)}</span>}</span>{profile.kind === 'creators' && profile.subscribers !== null && <span className="row-subscribers"><strong>{new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(profile.subscribers)}</strong><span>subscribers</span></span>}<span className="row-date">{analyzedDate(profile.updatedAt)}</span><Icon name="chevron"/></button>
          </li>)}</ul></>}
          {state.error && <ErrorNotice error={state.error} onRetry={library.retry}/>}
          {!state.error && state.loaded && state.items.length === 0 && <EmptyState title={state.query || state.onlyCollection ? 'No matching profiles' : 'No creators yet'} action={(state.query || state.onlyCollection) ? <button className="button secondary" onClick={library.clearFilters}>Clear filters</button> : undefined}/>}
          {state.phase === 'more' ? <Loading label="Loading more…"/> : state.nextCursor && !state.error && <div className="list-footer"><button className="button secondary" onClick={library.loadMore}>Load more</button></div>}
        </>}
      </div>
      <div role="tabpanel" id="panel-games" aria-labelledby="tab-games" hidden={kind !== 'games'}><GameLibrary api={api} active={active && kind === 'games'} onNavigationGuardChange={registerGuard} onConnectionRepair={onConnectionRepair}/></div>
    </div>
    {selection && <ProfileDetail key={`${selection.kind}-${selection.id}`} api={api} summary={selection} onBack={backToList}/>}
  </>;
}
