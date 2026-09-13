import {SelectionActions} from '../SelectionActions';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { PublicError } from '../../../shared/bridge';
import type { CandidateEvidenceFilter, CandidateListInput, CandidateQueryOptions, CandidateSort, CandidateView } from '../../../shared/match';
import type { SavedSetPage, SavedSetsAPI, SavedSetView } from '../../../shared/savedSets';
import { ErrorNotice, Icon, Loading } from '../Primitives';
import { CandidateResults, type CandidateOutreachControl } from './MatchResults';
import { membershipChanged, readCandidateMembership } from './outreachProjection';
import './savedSetBrowser.css';

type Options = Required<CandidateQueryOptions>;
const DEFAULT_OPTIONS: Options = { evidence: 'all', sort: 'relevance' };
const networkError: PublicError = { code: 'network_error', message: 'Saved lists could not be loaded. Try again.', retryable: true };
const scopeError: PublicError = { code: 'invalid_response', message: 'This saved list does not belong to the current activity.', retryable: false };
const responseError: PublicError = { code: 'invalid_response', message: 'The saved-list response could not be used. Reload and try again.', retryable: true };

export function SavedSetPicker({ api, activityId, active, refreshToken, disabled = false, selectedId, onOpen }: {
  api: SavedSetsAPI; activityId: string; active: boolean; refreshToken?: number; disabled?: boolean;
  selectedId?: string | null; onOpen: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [page, setPage] = useState<SavedSetPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<PublicError | null>(null);
  const [failed, setFailed] = useState<{ activityId: string; offset: number; limit: number } | null>(null);
  const generation = useRef(0), pageRef = useRef(page), activityRef = useRef(activityId);
  pageRef.current = page;

  const load = useCallback(async (input: { activityId: string; offset: number; limit: number }) => {
    const token = ++generation.current;
    setBusy(true); setError(null); setFailed(null);
    try {
      const result = await api.list(input);
      if (token !== generation.current) return;
      if (!result.ok) { setError(result.error); setFailed(input); setBusy(false); return; }
      setPage(result.data); setBusy(false);
    } catch {
      if (token === generation.current) { setError(networkError); setFailed(input); setBusy(false); }
    }
  }, [api]);

  useEffect(() => {
    const changed = activityRef.current !== activityId;
    if (changed) { activityRef.current = activityId; generation.current++; pageRef.current = null; setPage(null); setError(null); setFailed(null); }
    if (expanded && active) void load({ activityId, offset: changed ? 0 : pageRef.current?.offset ?? 0, limit: 50 });
  }, [active, activityId, expanded, load, refreshToken]);
  useEffect(() => () => { generation.current++; }, []);

  const start = page?.items.length ? page.offset + 1 : 0, end = page ? page.offset + page.items.length : 0;
  return <details className="saved-set-picker" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
    <summary aria-disabled={disabled} onClick={event => { if (disabled) event.preventDefault(); }}>Saved lists</summary>
    <div className="saved-set-picker-body">
      {busy && !page ? <Loading label="Loading saved lists…"/> : null}
      {page ? <><span className="saved-set-page-count">{start}–{end} of {page.total} saved lists</span><ul>{page.items.map(set => <li key={set.id}><button type="button" aria-current={selectedId === set.id ? 'true' : undefined} disabled={disabled} aria-label={`Open ${set.name}`} onClick={() => onOpen(set.id)}><span>{set.name}</span><small>{set.count} saved</small></button></li>)}</ul>{page.items.length === 0 ? <span className="muted">No saved lists</span> : null}<div className="saved-set-picker-pages"><button type="button" className="text-button" disabled={busy || page.offset === 0} onClick={() => void load({ activityId, offset: Math.max(0, page.offset - 50), limit: 50 })}>Previous saved lists</button><button type="button" className="text-button" disabled={busy || page.offset + page.limit >= page.total} onClick={() => void load({ activityId, offset: page.offset + page.limit, limit: 50 })}>Next saved lists</button></div></> : null}
      {error ? <ErrorNotice error={error} onRetry={failed ? () => void load(failed) : undefined}/> : null}
    </div>
  </details>;
}

type FailedRead = { kind: 'metadata' | 'prefix'; options: Options; capacity: number } | { kind: 'more'; options: Options; offset: number };

export interface SavedSetQueryChange {
  next: Required<CandidateQueryOptions>;
  previous: Required<CandidateQueryOptions>;
  visible: CandidateView[];
  current: boolean;
  read: () => Promise<CandidateView[]>;
  apply: () => void;
}

export interface SavedSetResultsProps {
  api: SavedSetsAPI; id: string; activityId: string; active: boolean; onMetadata: (set: SavedSetView) => void;
  onOriginal: () => void; onOpenCreator: (id: string, section?: 'overview' | 'contacts' | 'works') => void;
  outreach?: CandidateOutreachControl;
  onSelectLoaded?: (candidates: CandidateView[]) => void;
  onDeselectLoaded?: (candidates: CandidateView[]) => void;
  onQueryChange?: (change: SavedSetQueryChange) => void | Promise<void>;
}

export function SavedSetResults({ api, id, activityId, active, onMetadata, onOriginal, onOpenCreator, outreach, onSelectLoaded, onDeselectLoaded, onQueryChange }: SavedSetResultsProps) {
  const [metadata, setMetadata] = useState<SavedSetView | null>(null);
  const [options, setOptions] = useState<Options>(DEFAULT_OPTIONS);
  const [candidates, setCandidates] = useState<CandidateView[]>([]);
  const [total, setTotal] = useState(0), [capacity, setCapacity] = useState(100);
  const [loading, setLoading] = useState(false), [current, setCurrent] = useState(false);
  const [error, setError] = useState<PublicError | null>(null);
  const [failed, setFailed] = useState<FailedRead | null>(null);
  const generation = useRef(0), projectionEpoch = useRef(0), keyRef = useRef(''), loadedKeyRef = useRef(''), renderedKeyRef = useRef(''), activeRef = useRef(active);
  const onMetadataRef = useRef(onMetadata), optionsRef = useRef(options), capacityRef = useRef(capacity), candidatesRef = useRef(candidates);
  const renderedKey = `${activityId}:${id}`;
  renderedKeyRef.current = renderedKey;
  activeRef.current = active;
  onMetadataRef.current = onMetadata; optionsRef.current = options; capacityRef.current = capacity; candidatesRef.current = candidates;

  const failRead = useCallback((token: number, issue: PublicError, retry: FailedRead) => {
    if (token !== generation.current) return;
    setError(issue); setFailed(retry); setLoading(false); setCurrent(false);
  }, []);

  const loadPrefix = useCallback(async (token: number, next: Options, nextCapacity: number) => {
    const items: CandidateView[] = []; let offset = 0, filteredTotal = 0;
    while (offset < Math.min(nextCapacity, 600)) {
      let result;
      try { result = await api.results({ id, evidence: next.evidence, sort: next.sort, offset, limit: 100 }); }
      catch { failRead(token, networkError, { kind: 'prefix', options: next, capacity: nextCapacity }); return; }
      if (token !== generation.current) return;
      if (!result.ok) { failRead(token, result.error, { kind: 'prefix', options: next, capacity: nextCapacity }); return; }
      const page = result.data;
      if (page.offset !== offset || (offset > 0 && page.total !== filteredTotal) || (page.items.length === 0 && offset < page.total)) {
        failRead(token, responseError, { kind: 'prefix', options: next, capacity: nextCapacity }); return;
      }
      if (offset === 0) filteredTotal = page.total;
      items.push(...page.items); offset += page.items.length;
      if (offset >= filteredTotal || page.items.length < 100) break;
    }
    if (token !== generation.current) return;
    setCandidates(items); candidatesRef.current = items; setTotal(filteredTotal); setCapacity(nextCapacity); capacityRef.current = nextCapacity;
    setOptions(next); optionsRef.current = next; loadedKeyRef.current = `${activityId}:${id}`;
    setCurrent(true); setLoading(false); setError(null); setFailed(null);
  }, [activityId, api, failRead, id]);

  const loadResults = useCallback((next: Options, nextCapacity: number) => {
    const token = ++generation.current;
    setLoading(true); setCurrent(false); setError(null); setFailed(null);
    void loadPrefix(token, next, nextCapacity);
  }, [loadPrefix]);

  const loadSet = useCallback(async (switched: boolean) => {
    const next = switched ? DEFAULT_OPTIONS : optionsRef.current;
    const nextCapacity = switched ? 100 : capacityRef.current;
    const token = ++generation.current;
    if (switched) {
      setMetadata(null); setOptions(next); optionsRef.current = next; setCandidates([]); candidatesRef.current = [];
      setTotal(0); setCapacity(nextCapacity); capacityRef.current = nextCapacity; loadedKeyRef.current = '';
    }
    setLoading(true); setCurrent(false); setError(null); setFailed(null);
    let result;
    try { result = await api.detail(id); }
    catch { failRead(token, networkError, { kind: 'metadata', options: next, capacity: nextCapacity }); return; }
    if (token !== generation.current) return;
    if (!result.ok) { failRead(token, result.error, { kind: 'metadata', options: next, capacity: nextCapacity }); return; }
    if (result.data.id !== id || result.data.activity_id !== activityId) { failRead(token, scopeError, { kind: 'metadata', options: next, capacity: nextCapacity }); return; }
    setMetadata(result.data); onMetadataRef.current(result.data);
    await loadPrefix(token, next, nextCapacity);
  }, [activityId, api, failRead, id, loadPrefix]);

  const loadMoreAt = useCallback(async (offset: number, next: Options) => {
    const token = ++generation.current;
    setLoading(true); setCurrent(false); setError(null); setFailed(null);
    let result;
    try { result = await api.results({ id, evidence: next.evidence, sort: next.sort, offset, limit: 100 }); }
    catch { failRead(token, networkError, { kind: 'more', options: next, offset }); return; }
    if (token !== generation.current) return;
    if (!result.ok) { failRead(token, result.error, { kind: 'more', options: next, offset }); return; }
    if (result.data.offset !== offset) { failRead(token, responseError, { kind: 'more', options: next, offset }); return; }
    const combined = [...candidatesRef.current, ...result.data.items];
    setCandidates(combined); candidatesRef.current = combined; setTotal(result.data.total);
    const nextCapacity = Math.min(600, Math.max(capacityRef.current, offset + 100));
    setCapacity(nextCapacity); capacityRef.current = nextCapacity; loadedKeyRef.current = `${activityId}:${id}`;
    setCurrent(true); setLoading(false); setError(null); setFailed(null);
  }, [activityId, api, failRead, id]);

  useEffect(() => {
    const key = `${activityId}:${id}`, switched = keyRef.current !== key;
    if (switched) keyRef.current = key;
    if (!active) { generation.current++; return; }
    void loadSet(switched);
    return () => { generation.current++; };
  }, [active, activityId, id, loadSet]);

  function choose(next: Options) {
    projectionEpoch.current++;
    setOptions(next); optionsRef.current = next; setCapacity(100); capacityRef.current = 100;
    loadResults(next, 100);
  }
  function chooseEvidence(evidence: CandidateEvidenceFilter) {
    const next = { ...optionsRef.current, evidence };
    if (!onQueryChange) { choose(next); return; }
    const key = renderedKey, token = generation.current, epoch = ++projectionEpoch.current;
    const projectionCurrent = current && active && loadedKeyRef.current === key;
    if (!projectionCurrent || outreach?.disabled) return;
    const valid = () => activeRef.current && renderedKeyRef.current === key && loadedKeyRef.current === key
      && token === generation.current && epoch === projectionEpoch.current;
    const candidatesAPI = {
      candidates: (input: CandidateListInput) => api.results({
        id,
        evidence: input.evidence,
        sort: input.sort,
        offset: input.offset,
        limit: input.limit,
      }),
    };
    void onQueryChange({
      next,
      previous: optionsRef.current,
      visible: candidatesRef.current,
      current: true,
      read: async () => {
        if (!valid()) throw membershipChanged;
        const matching = await readCandidateMembership(candidatesAPI, id, next);
        if (!valid()) throw membershipChanged;
        return matching;
      },
      apply: () => { if (valid()) choose(next); },
    });
  }
  function retry() {
    if (!failed) return;
    if (failed.kind === 'metadata') void loadSet(false);
    else if (failed.kind === 'prefix') loadResults(failed.options, failed.capacity);
    else if (failed.kind === 'more') void loadMoreAt(failed.offset, failed.options);
  }
  const previous = `${candidates.length} previous saved result${candidates.length === 1 ? '' : 's'}`;
  const status = current ? `${total} matching` : loading ? `Refreshing · ${previous}` : `Results unavailable · ${previous}`;
  const actionCurrent = current && active && loadedKeyRef.current === renderedKey;
  const candidateOutreach = actionCurrent ? outreach : undefined;
  return <section className="saved-set-results" aria-label="Saved list results">
    <header className="saved-set-results-header"><div><h2>{metadata?.name ?? 'Saved list'}</h2>{metadata ? <span>{metadata.count} saved</span> : null}</div><div><button type="button" className="button secondary" disabled={!metadata} onClick={onOriginal}>Original search</button><button type="button" className="icon-button" aria-label="Refresh saved list" title="Refresh saved list" disabled={loading} onClick={() => void loadSet(false)}><Icon name="refresh"/></button></div></header>
    {metadata ? <div className="saved-set-query-controls" aria-label="Saved result filters and order"><div><label>Evidence<select aria-label="Evidence" value={options.evidence} disabled={Boolean(onQueryChange) && (!actionCurrent || Boolean(outreach?.disabled))} onChange={event => chooseEvidence(event.target.value as CandidateEvidenceFilter)}><option value="all">All evidence</option><option value="current_game">Current game</option><option value="reference_game">Reference games</option><option value="related_content">Other recorded content</option><option value="none">Evidence unknown</option></select></label><label>Order<select aria-label="Order" value={options.sort} onChange={event => choose({ ...optionsRef.current, sort: event.target.value as CandidateSort })}><option value="relevance">Relevance</option><option value="followers">Followers</option><option value="recent_publish">Recently published</option><option value="recent_added">Recently added</option></select></label>{onSelectLoaded&&onDeselectLoaded ? <SelectionActions scope="Loaded saved creators" count={candidates.filter(row=>!row.identity_changed).length} selected={candidates.filter(row=>!row.identity_changed&&outreach?.isSelected(row)).length} disabled={!actionCurrent||Boolean(outreach?.disabled)} onSelect={()=>onSelectLoaded(candidatesRef.current.filter(row=>!row.identity_changed))} onClear={()=>onDeselectLoaded(candidatesRef.current.filter(row=>!row.identity_changed))}/> : onSelectLoaded ? <button type="button" className="text-button" disabled={!actionCurrent || Boolean(outreach?.disabled) || candidates.length === 0} onClick={() => { if (actionCurrent && !outreach?.disabled) onSelectLoaded(candidatesRef.current); }}>Select loaded</button> : null}</div><span role="status">{status}</span></div> : null}
    {!current && candidates.length ? <p className="saved-set-previous" role="status">Showing {previous}.</p> : null}
    {metadata && (candidates.length || loading || !error) ? <CandidateResults candidates={candidates} total={current ? total : candidates.length} loading={current ? loading : candidates.length === 0 && loading} sort={options.sort} onLoadMore={() => void loadMoreAt(candidatesRef.current.length, optionsRef.current)} onOpenCreator={onOpenCreator} outreach={candidateOutreach}/> : null}
    {error ? <ErrorNotice error={error} onRetry={error.retryable ? retry : undefined}/> : null}
  </section>;
}
