import { useCallback, useEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../shared/bridge';
import { GAME_FIELDS, type GameDetail, type GameListInput, type GamePage, type GameSort, type GameWebsiteStatus, type NavigationGuard } from '../../shared/games';
import { GameEditor } from './GameEditor';
import { comparisonValue, gameLabels } from './gameDraft';
import { analyzedDate, Artwork, EmptyState, ErrorNotice, Icon, Loading } from './Primitives';
import '../games.css';

type Route = { kind: 'list' } | { kind: 'loading'; id: string; error: PublicError | null } | { kind: 'detail'; game: GameDetail; saved?: boolean } | { kind: 'editor'; game: GameDetail | null };
interface LibraryState { search: string; query: string; onlyCollection: boolean; websiteStatus: GameWebsiteStatus; sort: GameSort; page: GamePage | null; busy: boolean; error: PublicError | null; failedInput: GameListInput | null }
function queryInput(state: LibraryState, offset = 0): GameListInput {
  return { query: state.query, onlyCollection: state.onlyCollection, websiteStatus: state.websiteStatus, sort: state.sort, offset };
}
const interrupted: PublicError = { code: 'network_error', message: 'Games could not be loaded. Your current page is still here.', retryable: true };
const titleOf = (game: GameDetail) => game.name || game.website_url || 'Untitled game';
function canOpen(url: string | null): url is string {
  if (!url) return false;
  try { const parsed = new URL(url); return parsed.protocol === 'https:' && !parsed.username && !parsed.password; } catch { return false; }
}

function GameRecord({ api, game, saved, onBack, onEdit }: { api: DesktopBridge; game: GameDetail; saved?: boolean; onBack: () => void; onEdit: () => void }) {
  const [externalError, setExternalError] = useState<PublicError | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [game.id]);
  async function open(url: string) {
    try { const response = await api.openExternal(url); setExternalError(response.ok ? null : response.error); }
    catch { setExternalError({ code: 'open_failed', message: 'The link could not be opened.', retryable: false }); }
  }
  return <article className="game-record"><div className="game-editor-heading"><button className="text-button" onClick={onBack}><Icon name="arrow"/>Back to games</button>{saved && <span className="game-saved-message" role="status"><Icon name="check"/>Saved</span>}</div>
    <section className="profile-identity"><Artwork url={game.cover_url} name={titleOf(game)} kind="games" large/><div className="identity-main"><h2 ref={heading} tabIndex={-1}>{titleOf(game)}</h2>{game.developer && <p>{game.developer}</p>}</div><button className="button primary" onClick={onEdit}>Edit game</button>
      <div className="profile-metrics">{game.favorite && <div><span>Collection</span><strong>Saved</strong></div>}{game.last_analyzed_at && <div><span>Analyzed</span><strong>{analyzedDate(game.last_analyzed_at)}</strong></div>}{game.release_date && <div><span>Release date</span><strong>{game.release_date}</strong></div>}</div>
    </section>
    {externalError && <ErrorNotice error={externalError}/>}
    <div className={`game-detail-columns ${game.reference_works.length ? '' : 'game-detail-single'}`}><section>{game.description && <><h3>About</h3><p className="game-description-text">{game.description}</p></>}{game.tags.length > 0 && <ul className="tags">{game.tags.map((tag, index) => <li key={`${tag}-${index}`}>{tag}</li>)}</ul>}<dl className="game-identity-fields"><div><dt>Website</dt><dd>{game.website_url ? <><span>{game.website_url}</span>{canOpen(game.website_url) && <button className="text-button" onClick={() => void open(game.website_url!)}>Open website<Icon name="external"/></button>}</> : 'Not recorded'}</dd></div>{game.steam_app_id && <div><dt>Steam ID</dt><dd>{game.steam_app_id}</dd></div>}{game.languages.length > 0 && <div><dt>Languages</dt><dd>{game.languages.join(', ')}</dd></div>}</dl></section>
      {game.reference_works.length > 0 && <section className="game-detail-references"><h3>Reference works <span className="count">{game.reference_works.length}</span></h3>{game.reference_works.length ? <ul>{game.reference_works.map((reference, index) => <li key={reference.id || index}><h4>{reference.name || reference.url}</h4>{reference.url && <div className="game-reference-link"><span>{reference.url}</span>{canOpen(reference.url) && <button className="text-button" onClick={() => void open(reference.url!)}>Open reference<Icon name="external"/></button>}</div>}{reference.similarities.length > 0 && <ul className="tags">{reference.similarities.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul>}{reference.reason && <p>{reference.reason}</p>}</li>)}</ul> : <p className="muted">No references added.</p>}</section>}</div>
    <details className="game-provenance"><summary>Source &amp; saved fields</summary><div className="game-source-binding"><h3>Source binding · Read-only</h3><dl><div><dt>Steam source</dt><dd>{game.source_identity.steam_app_id || 'Not bound'}</dd></div><div><dt>Source URL</dt><dd>{game.source_identity.canonical_url || 'Not bound'}</dd></div><div><dt>Revision</dt><dd>{game.revision}</dd></div></dl></div><div className="game-source-comparisons">{GAME_FIELDS.map(field => <div className="game-source-field" key={field}><h4>{gameLabels[field]}{game.overridden_fields.includes(field) && <span className="game-source-badge">Manual override</span>}</h4><div><span>Source</span><p>{comparisonValue(game.source_fields[field])}</p></div><div><span>Saved</span><p>{comparisonValue(game[field])}</p></div></div>)}</div></details>
  </article>;
}

export function GameLibrary({ api, active, onNavigationGuardChange, onConnectionRepair }: { api: DesktopBridge; active: boolean; onNavigationGuardChange?: (guard: NavigationGuard | null) => void; onConnectionRepair?: () => void }) {
  const [library, setLibrary] = useState<LibraryState>({ search: '', query: '', onlyCollection: false, websiteStatus: 'all', sort: 'recent_updated', page: null, busy: false, error: null, failedInput: null });
  const [route, setRoute] = useState<Route>({ kind: 'list' });
  const listState = useRef(library); listState.current = library;
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const alive = useRef(true);
  const loaded = useRef(false);
  const listScroll = useRef(0);
  const listRoot = useRef<HTMLDivElement>(null);
  const editorGuard = useRef<NavigationGuard | null>(null);
  const registerGuard = useCallback((guard: NavigationGuard | null) => { editorGuard.current = guard; onNavigationGuardChange?.(guard); }, [onNavigationGuardChange]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; loaded.current = false; generation.current++; detailGeneration.current++; }; }, []);
  useEffect(() => () => onNavigationGuardChange?.(null), [onNavigationGuardChange]);

  const loadPage = useCallback(async (input: GameListInput, preserve = true) => {
    const token = ++generation.current;
    const request = { ...input, websiteStatus: input.websiteStatus ?? 'all', sort: input.sort ?? 'recent_updated', limit: 24, offset: input.offset || 0 };
    setLibrary(previous => ({ ...previous, query: input.query || '', onlyCollection: input.onlyCollection || false, websiteStatus: request.websiteStatus, sort: request.sort, page: preserve ? previous.page : null, busy: true, error: null, failedInput: null }));
    try {
      const response = await api.games.list(request);
      if (!alive.current || generation.current !== token) return;
      if (!response.ok) { setLibrary(previous => ({ ...previous, busy: false, error: response.error, failedInput: request })); return; }
      const lastOffset = Math.max(0, Math.floor((response.data.total - 1) / 24) * 24);
      if ((input.offset || 0) > lastOffset) { void loadPage({ ...input, offset: lastOffset }, preserve); return; }
      setLibrary(previous => ({ ...previous, page: response.data, busy: false, error: null, failedInput: null }));
    } catch { if (alive.current && generation.current === token) setLibrary(previous => ({ ...previous, busy: false, error: interrupted, failedInput: request })); }
  }, [api]);
  useEffect(() => { if (active && !loaded.current) { loaded.current = true; void loadPage({ offset: 0 }, false); } }, [active, loadPage]);

  function rememberScroll() { listScroll.current = document.querySelector<HTMLElement>('.main-scroll')?.scrollTop ?? 0; }
  function scrollTop() { const element = document.querySelector<HTMLElement>('.main-scroll'); if (element) element.scrollTop = 0; }
  function backToList(refresh = false) {
    detailGeneration.current++;
    setRoute({ kind: 'list' });
    if (refresh) { const current = listState.current; void loadPage(queryInput(current, current.page?.offset || 0)); }
    requestAnimationFrame(() => { const element = document.querySelector<HTMLElement>('.main-scroll'); if (element) element.scrollTop = listScroll.current; listRoot.current?.querySelector<HTMLInputElement>('input[type=search]')?.focus({ preventScroll: true }); });
  }
  async function openGame(id: string, preserveScroll = false) {
    if (!preserveScroll) rememberScroll();
    scrollTop();
    const token = ++detailGeneration.current; setRoute({ kind: 'loading', id, error: null });
    try {
      const response = await api.games.detail(id);
      if (!alive.current || detailGeneration.current !== token) return;
      setRoute(response.ok ? { kind: 'detail', game: response.data } : { kind: 'loading', id, error: response.error });
    } catch { if (alive.current && detailGeneration.current === token) setRoute({ kind: 'loading', id, error: interrupted }); }
  }
  function saved(game: GameDetail) {
    setRoute({ kind: 'detail', game, saved: true }); scrollTop();
    const current = listState.current;
    setLibrary(previous => ({ ...previous, page: previous.page ? { ...previous.page, items: previous.page.items.map(item => item.id === game.id ? game : item) } : null }));
    void loadPage(queryInput(current, current.page?.offset || 0));
  }
  const page = library.page;
  const shownStart = page && page.items.length ? page.offset + 1 : 0;
  const pageInput = (offset: number): GameListInput => queryInput(library, offset);
  const filtered = Boolean(library.query || library.onlyCollection || library.websiteStatus !== 'all');
  return <div className="games-library">
    <div ref={listRoot} hidden={route.kind !== 'list'}><div className="game-library-tools"><form className="search-form" role="search" onSubmit={event => { event.preventDefault(); void loadPage({ ...pageInput(0), query: library.search.trim() }); }}><Icon name="search"/><input type="search" aria-label="Search games" maxLength={255} placeholder="Search games…" value={library.search} onChange={event => setLibrary(previous => ({ ...previous, search: event.target.value }))}/><button className="button secondary" type="submit">Search</button></form><button className="button primary" onClick={() => { rememberScroll(); scrollTop(); setRoute({ kind: 'editor', game: null }); }}>New game</button></div>
      <div className="game-list-filter"><label className="collection-filter"><input type="checkbox" checked={library.onlyCollection} onChange={event => void loadPage({ ...pageInput(0), onlyCollection: event.target.checked })}/><Icon name="collection"/>Saved only</label><label className="game-query-choice">Website<select value={library.websiteStatus} onChange={event => void loadPage({ ...pageInput(0), websiteStatus: event.target.value as GameWebsiteStatus })}><option value="all">All</option><option value="available">Available</option><option value="missing">Missing</option></select></label><label className="game-query-choice">Sort<select aria-label="Sort games" value={library.sort} onChange={event => void loadPage({ ...pageInput(0), sort: event.target.value as GameSort })}><option value="recent_updated">Recently updated</option><option value="recent_added">Recently added</option><option value="name">Name</option></select></label><button className="text-button" disabled={library.busy} onClick={() => void loadPage(pageInput(library.failedInput?.offset ?? page?.offset ?? 0))}>Refresh</button></div>
      {library.query && <div className="active-filters"><span>Results for “{library.query}”</span><button className="text-button" onClick={() => { setLibrary(previous => ({ ...previous, search: '' })); void loadPage({ ...pageInput(0), query: '' }); }}>Clear search</button></div>}
      {page && (library.busy || library.error) && <p className="game-results-status" role="status">{library.busy ? 'Updating results…' : 'Previous results'}</p>}
      {page && page.items.length > 0 && <ul className="profile-list" aria-label="Games">{page.items.map(game => <li key={game.id}><button className="profile-row" aria-label={`Open ${titleOf(game)}`} onClick={() => void openGame(game.id)}><Artwork url={game.cover_url} name={titleOf(game)} kind="games"/><span className="profile-row-content"><span className="profile-row-title">{titleOf(game)}{game.favorite && <Icon name="collection"/>}</span><span className="profile-row-summary">{game.developer || game.website_url || 'Manual game'}</span>{game.tags.length > 0 && <span className="row-tags">{game.tags.slice(0, 3).map((tag, index) => <span key={index}>{tag}</span>)}</span>}</span>{game.updated_at && <span className="row-date" title="Updated">{analyzedDate(game.updated_at)}</span>}<Icon name="chevron"/></button></li>)}</ul>}
      {library.busy && <Loading label="Loading games…"/>}
      {library.error && <ErrorNotice error={library.error} onRetry={() => library.failedInput && void loadPage(library.failedInput, Boolean(page))}/>}
      {!library.busy && !library.error && page?.items.length === 0 && <EmptyState title={filtered ? 'No matching games' : 'No games yet'} action={filtered ? <button className="button secondary" onClick={() => { setLibrary(previous => ({ ...previous, search: '' })); void loadPage({ ...pageInput(0), query: '', onlyCollection: false, websiteStatus: 'all' }); }}>Clear filters</button> : undefined}/>}
      {page && <div className="game-pagination"><span>{shownStart}–{page.offset + page.items.length} of {page.total}</span><div><button className="button secondary" disabled={library.busy || Boolean(library.error) || page.offset === 0} onClick={() => void loadPage(pageInput(Math.max(0, page.offset - 24)))}>Previous page</button><button className="button secondary" disabled={library.busy || Boolean(library.error) || page.offset + page.limit >= page.total} onClick={() => void loadPage(pageInput(page.offset + page.limit))}>Next page</button></div></div>}
    </div>
    {route.kind === 'loading' && <section className="game-detail-loading"><button className="text-button" onClick={() => backToList()}>Back to games</button>{route.error ? <ErrorNotice error={route.error} onRetry={() => void openGame(route.id, true)}/> : <Loading label="Loading game…"/>}</section>}
    {route.kind === 'detail' && <GameRecord api={api} game={route.game} saved={route.saved} onBack={() => backToList()} onEdit={() => { setRoute({ kind: 'editor', game: route.game }); scrollTop(); }}/>}
    {route.kind === 'editor' && <GameEditor key={route.game?.id || 'new'} api={api} initial={route.game} onSaved={saved} onCancel={() => backToList(true)} onNavigationGuardChange={registerGuard} onConnectionRepair={onConnectionRepair}/>}
  </div>;
}
