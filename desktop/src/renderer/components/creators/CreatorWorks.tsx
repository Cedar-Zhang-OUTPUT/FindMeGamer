import { useEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import type { WorkDetail, WorkPage } from '../../../shared/creators';
import { analyzedDate, EmptyState, ErrorNotice, friendlyLabel, Icon, Loading } from '../Primitives';

const PAGE_SIZE = 50;
const NUMBER_FORMAT = new Intl.NumberFormat('en');

function safeHTTPS(value: string | null): value is string {
  if (!value) return false;
  try { const url = new URL(value); return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password; }
  catch { return false; }
}
function duration(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return null;
  const whole = Math.floor(seconds), hours = Math.floor(whole / 3600), minutes = Math.floor((whole % 3600) / 60), remaining = whole % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}` : `${minutes}:${String(remaining).padStart(2, '0')}`;
}
function workTitle(work: WorkDetail) { return work.content_title || work.work_name || work.source_content_id || 'Untitled work'; }
function pageRange(page: WorkPage) {
  if (!page.items.length) return page.total ? `0 of ${page.total.toLocaleString('en')}` : '0 works';
  return `${(page.offset + 1).toLocaleString('en')}–${(page.offset + page.items.length).toLocaleString('en')} of ${page.total.toLocaleString('en')}`;
}
interface NavigationState { creatorId: string; includePrevious: boolean; offset: number }
interface PageSnapshot { creatorId: string; identityRevision: number; includePrevious: boolean; page: WorkPage }
interface GameCache { api: DesktopBridge; values: Map<string, string | null>; pending: Set<string> }
export interface CreatorWorksProps {
  api: DesktopBridge; creatorId: string; identityRevision: number; active: boolean;
  onEdit: (target: { kind: 'work'; base?: WorkDetail }) => void; refreshToken?: number;
}

export function CreatorWorks({ api, creatorId, identityRevision, active, onEdit, refreshToken = 0 }: CreatorWorksProps) {
  const [navigation, setNavigation] = useState<NavigationState>({ creatorId, includePrevious: false, offset: 0 });
  const effective = navigation.creatorId === creatorId ? navigation : { creatorId, includePrevious: false, offset: 0 };
  const [snapshot, setSnapshot] = useState<PageSnapshot | null>(null);
  const [phase, setPhase] = useState<'idle' | 'loading'>('idle');
  const [error, setError] = useState<PublicError | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [externalError, setExternalError] = useState<PublicError | null>(null);
  const [, refreshGameLabels] = useState(0);
  const request = useRef(0);
  const gameCache = useRef<GameCache>({ api, values: new Map(), pending: new Set() });
  if (gameCache.current.api !== api) gameCache.current = { api, values: new Map(), pending: new Set() };
  const page = snapshot?.creatorId === creatorId && snapshot.identityRevision === identityRevision && snapshot.includePrevious === effective.includePrevious ? snapshot.page : null;

  useEffect(() => { if (navigation.creatorId !== creatorId) setNavigation({ creatorId, includePrevious: false, offset: 0 }); }, [creatorId, navigation.creatorId]);
  useEffect(() => {
    const sequence = ++request.current;
    if (!active) return;
    setPhase('loading'); setError(null);
    void api.creators.works({ creatorId, includePreviousIdentity: effective.includePrevious, limit: PAGE_SIZE, offset: effective.offset }).then(result => {
      if (sequence !== request.current) return;
      setPhase('idle');
      if (result.ok) setSnapshot({ creatorId, identityRevision, includePrevious: effective.includePrevious, page: result.data }); else setError(result.error);
    }, () => {
      if (sequence !== request.current) return;
      setPhase('idle'); setError({ code: 'bridge_unavailable', message: 'Known works could not be loaded.', retryable: true });
    });
    return () => { if (request.current === sequence) request.current += 1; };
  }, [active, api, creatorId, effective.includePrevious, effective.offset, identityRevision, refreshToken, retryToken]);

  useEffect(() => {
    if (!active || !page) return;
    const cache = gameCache.current;
    const ids = [...new Set(page.items.flatMap(item => item.game_id ? [item.game_id] : []))]
      .filter(id => !cache.values.has(id) && !cache.pending.has(id)).slice(0, PAGE_SIZE);
    if (!ids.length) return;
    ids.forEach(id => cache.pending.add(id));
    void Promise.all(ids.map(async id => {
      try {
        const result = await api.games.detail(id);
        return [id, result.ok && result.data.name ? result.data.name : null] as const;
      } catch { return [id, null] as const; }
    })).then(entries => {
      if (gameCache.current !== cache) return;
      entries.forEach(([id, label]) => { cache.pending.delete(id); cache.values.set(id, label); });
      refreshGameLabels(version => version + 1);
    });
  }, [active, api, page]);

  function gameLabel(id: string) {
    const cache = gameCache.current;
    return cache.values.has(id) ? cache.values.get(id) || 'Game unavailable' : 'Loading game…';
  }
  async function open(url: string) {
    if (!safeHTTPS(url)) return;
    setExternalError(null);
    try { const result = await api.openExternal(url); if (!result.ok) setExternalError(result.error); }
    catch { setExternalError({ code: 'open_failed', message: 'This work link could not be opened.', retryable: false }); }
  }
  return <section className="creator-section creator-works" aria-labelledby="creator-works-heading">
    <div className="creator-section-heading creator-action-heading"><h2 className="sr-only" id="creator-works-heading">Known works</h2><button className="button primary" onClick={() => onEdit({ kind: 'work' })}>Add work</button></div>
    <div className="creator-work-tools"><label className="creator-history-toggle"><input type="checkbox" checked={effective.includePrevious} onChange={event => setNavigation({ creatorId, includePrevious: event.target.checked, offset: 0 })}/>Include previous identities</label><details className="creator-help"><summary>About this list</summary><p>Known works are saved records, not a complete viewing or play history.</p></details></div>
    {externalError && <ErrorNotice error={externalError}/>} 
    {phase === 'loading' && !page && <Loading label="Loading known works…"/>}
    {error && <ErrorNotice error={error} onRetry={() => setRetryToken(value => value + 1)}/>} 
    {page && <>
      {phase === 'loading' && <Loading label="Refreshing known works…"/>}
      {page.items.length === 0 ? <EmptyState title="No known works"/> : <ul className="creator-work-list">
        {page.items.map(work => { const title = workTitle(work), time = duration(work.timestamp_seconds); return <li key={work.id}><article>
          <div className="creator-card-heading"><div><h3>{title}</h3><div className="creator-badges"><span>{friendlyLabel(work.content_type)}</span>{!work.is_current_identity && <span>Previous identity</span>}{work.origin === 'manual' && <span>Manual</span>}</div></div>{work.is_current_identity && <button className="button secondary" onClick={() => onEdit({ kind: 'work', base: work })}>Edit {title}</button>}</div>
          {work.evidence_excerpt && <blockquote>{work.evidence_excerpt}</blockquote>}
          {(work.published_at || time || work.game_id) && <dl className="creator-detail-grid creator-work-facts">{work.published_at && <div><dt>Published</dt><dd>{analyzedDate(work.published_at)}</dd></div>}{time && <div><dt>Timestamp</dt><dd>{time}</dd></div>}{work.game_id && <div><dt>Linked game</dt><dd>{gameLabel(work.game_id)}</dd></div>}</dl>}
          {work.metrics.length > 0 && <ul className="creator-metrics" aria-label={`Metrics for ${title}`}>{work.metrics.map((metric, index) => <li className="creator-metric" style={{ minWidth: 0, overflowWrap: 'anywhere' }} key={`${metric.name}-${index}`}>{NUMBER_FORMAT.format(metric.value)} {friendlyLabel(metric.name).toLocaleLowerCase()}</li>)}</ul>}
          <details className="creator-provenance"><summary>Record details</summary><div className="creator-work-details">{work.verification_notes && <p className="creator-verification"><strong>Evidence notes</strong>{work.verification_notes}</p>}{work.source_url && <div className="creator-source-row"><span><strong>Work URL</strong><span className="creator-raw-value">{work.source_url}</span></span>{safeHTTPS(work.source_url) && <button className="text-button" onClick={() => void open(work.source_url!)} aria-label={`Open ${title}`}>Open work<Icon name="external"/></button>}</div>}<dl className="creator-detail-grid creator-provenance-identity"><div><dt>Source platform</dt><dd>{friendlyLabel(work.source_platform)}</dd></div>{work.source_content_id && <div><dt>Source content ID</dt><dd>{work.source_content_id}</dd></div>}<div><dt>Identity revision</dt><dd>{work.identity_revision}</dd></div>{work.source_collected_at && <div><dt>Source collected</dt><dd>{analyzedDate(work.source_collected_at)}</dd></div>}{work.content_id && <div><dt>Display content ID</dt><dd>{work.content_id}</dd></div>}{work.collected_at && <div><dt>Collected</dt><dd>{analyzedDate(work.collected_at)}</dd></div>}{work.platform !== work.source_platform && <div><dt>Display platform</dt><dd>{friendlyLabel(work.platform)}</dd></div>}</dl><details className="creator-raw-details"><summary>Raw fields</summary><div className="creator-provenance-grid"><div><h4>Source fields</h4><pre>{JSON.stringify(work.source_fields, null, 2)}</pre></div><div><h4>Manual overrides</h4><pre>{JSON.stringify(work.manual_overrides, null, 2)}</pre></div></div></details></div></details>
        </article></li>; })}
      </ul>}
      <nav className="creator-pagination" aria-label="Known works pages"><span>{pageRange(page)}</span><div><button className="button secondary" disabled={phase === 'loading' || page.offset === 0} onClick={() => setNavigation({ ...effective, offset: Math.max(0, page.offset - PAGE_SIZE) })}>Previous works</button><button className="button secondary" disabled={phase === 'loading' || page.offset + page.items.length >= page.total} onClick={() => setNavigation({ ...effective, offset: page.offset + PAGE_SIZE })}>Next works</button></div></nav>
    </>}
  </section>;
}
