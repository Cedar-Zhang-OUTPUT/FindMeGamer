import { useEffect, useRef, useState } from 'react';
import type { DesktopBridge } from '../../../shared/bridge';
import type { GameDetail, GamePage } from '../../../shared/games';

export function LinkedGamePicker({ api, value, onChange, disabled, error }: { api: Pick<DesktopBridge, 'games'>; value: string | null; onChange: (id: string | null) => void; disabled: boolean; error?: string }) {
  const [query, setQuery] = useState('');
  const [request, setRequest] = useState({ query: '', offset: 0, attempt: 0 });
  const [page, setPage] = useState<GamePage | null>(null);
  const [selected, setSelected] = useState<GameDetail | null>(null);
  const [loadError, setLoadError] = useState('');
  const [selectedError, setSelectedError] = useState('');
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current; let alive = true;
    setLoading(true); setLoadError('');
    void api.games.list({ query: request.query, limit: 20, offset: request.offset }).then(result => {
      if (!alive || generation.current !== current) return;
      if (result.ok) setPage(result.data); else setLoadError(result.error.message);
    }).catch(() => { if (alive && generation.current === current) setLoadError('Could not load games.'); }).finally(() => { if (alive && generation.current === current) setLoading(false); });
    return () => { alive = false; };
  }, [api.games, request]);
  useEffect(() => {
    let alive = true; setSelectedError('');
    if (!value) { setSelected(null); return; }
    void api.games.detail(value).then(result => {
      if (!alive) return;
      if (result.ok) setSelected(result.data); else setSelectedError(result.error.message);
    }).catch(() => { if (alive) setSelectedError('Could not load the selected game.'); });
    return () => { alive = false; };
  }, [api.games, value]);
  const search = () => setRequest({ query: query.trim(), offset: 0, attempt: request.attempt + 1 });
  return <section className="creator-game-picker" aria-label="Linked game">
    <div className="creator-game-current"><span>Linked game</span><strong>{value ? selected?.id === value ? selected.name || 'Unnamed game' : selectedError ? 'Selected game unavailable' : 'Loading selected game…' : 'None'}</strong><button type="button" className="text-button" disabled={disabled || value === null} onClick={() => onChange(null)}>No linked game</button></div>
    {selectedError && <p className="creator-field-error" role="alert">{selectedError}</p>}
    <div className="creator-game-search"><div className="form-field"><label htmlFor="creator-field-game_id">Search games</label><input id="creator-field-game_id" type="search" value={query} disabled={disabled} aria-invalid={Boolean(error)} aria-describedby={error ? 'creator-game-error' : undefined} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); search(); } }}/></div><button type="button" className="button secondary" disabled={disabled || loading} onClick={search}>Search games</button></div>
    {error && <p id="creator-game-error" className="creator-field-error">{error}</p>}
    {loadError && <p className="creator-field-error" role="alert">{loadError}</p>}
    {loadError && <button type="button" className="text-button" disabled={disabled || loading} onClick={() => setRequest({ ...request, attempt: request.attempt + 1 })}>Retry games</button>}
    {loading && <p role="status">Loading games…</p>}
    {!loading && page?.items.length === 0 && <p>No matching games.</p>}
    <ul className="creator-game-options">{page?.items.map(game => <li key={game.id}><button type="button" className="button secondary" disabled={disabled || game.id === value} aria-label={`Select game ${game.name || 'Unnamed game'}`} onClick={() => { setSelected(game); onChange(game.id); }}>{game.name || 'Unnamed game'}{game.developer && <small>{game.developer}</small>}</button></li>)}</ul>
    {page && <div className="creator-game-pages"><button type="button" className="text-button" disabled={disabled || loading || page.offset === 0} onClick={() => setRequest({ ...request, offset: Math.max(0, page.offset - 20) })}>Previous games</button><span>{page.total ? `${page.offset + 1}–${page.offset + page.items.length} of ${page.total}` : '0 games'}</span><button type="button" className="text-button" disabled={disabled || loading || page.offset + page.limit >= page.total} onClick={() => setRequest({ ...request, offset: page.offset + 20 })}>Next games</button></div>}
  </section>;
}
