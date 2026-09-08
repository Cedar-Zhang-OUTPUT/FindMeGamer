import { useCallback, useEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../shared/bridge';
import type { ProfileKind, ProfileSummary } from '../../shared/library';

interface TabState {
  draft: string;
  query: string;
  onlyCollection: boolean;
  items: ProfileSummary[];
  nextCursor: string | null;
  /** Successful page cursors are scoped to this tab and submitted filter. */
  history: (string | undefined)[];
  loaded: boolean;
  phase: 'idle' | 'loading' | 'more';
  error: PublicError | null;
  failedCursor: string | undefined;
}
const initialTab = (): TabState => ({ draft: '', query: '', onlyCollection: false, items: [], nextCursor: null, history: [], loaded: false, phase: 'idle', error: null, failedCursor: undefined });
const unexpected: PublicError = { code: 'bridge_unavailable', message: 'The desktop connection was interrupted.', retryable: true };

/** One instance lives for one verified connection. Unmount invalidates all pending results. */
export function useLibrary(api: DesktopBridge, enabled: boolean, active: boolean) {
  const [kind, setKind] = useState<ProfileKind>('creators');
  const [tabs, setTabs] = useState<Record<ProfileKind, TabState>>({ creators: initialTab(), games: initialTab() });
  const tabsRef = useRef(tabs); tabsRef.current = tabs;
  const generations = useRef({ creators: 0, games: 0 });
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; generations.current.creators++; generations.current.games++; }; }, []);

  const load = useCallback(async (target: ProfileKind, cursor?: string, filter?: { query: string; onlyCollection: boolean }) => {
    if (!enabled) return;
    const generation = ++generations.current[target];
    const current = tabsRef.current[target];
    const query = filter?.query ?? current.query;
    const onlyCollection = filter?.onlyCollection ?? current.onlyCollection;
    setTabs(previous => ({ ...previous, [target]: { ...previous[target], query, onlyCollection, ...(cursor ? {} : { items: [], nextCursor: null, history: [] }), phase: cursor ? 'more' : 'loading', error: null, failedCursor: undefined } }));
    try {
      const result = await api.library.list({ kind: target, ...(query ? { query } : {}), ...(onlyCollection ? { onlyCollection: true } : {}), ...(cursor ? { cursor } : {}), limit: 24 });
      if (!alive.current || generations.current[target] !== generation) return;
      if (!result.ok) {
        setTabs(previous => ({ ...previous, [target]: { ...previous[target], loaded: true, phase: 'idle', error: result.error, failedCursor: cursor } }));
        return;
      }
      setTabs(previous => {
        const existing = cursor ? previous[target].items : [];
        const merged = new Map(existing.map(item => [item.id, item]));
        for (const item of result.data.items) merged.set(item.id, item);
        return { ...previous, [target]: { ...previous[target], items: [...merged.values()], nextCursor: result.data.nextCursor, history: [...(cursor ? previous[target].history : []), cursor], loaded: true, phase: 'idle', error: null } };
      });
    } catch {
      if (alive.current && generations.current[target] === generation) setTabs(previous => ({ ...previous, [target]: { ...previous[target], loaded: true, phase: 'idle', error: unexpected, failedCursor: cursor } }));
    }
  }, [api, enabled]);

  useEffect(() => { const state = tabsRef.current[kind]; if (enabled && active && !state.loaded && state.phase === 'idle') void load(kind); }, [kind, enabled, active, load]);
  return {
    kind, setKind, state: tabs[kind],
    setDraft: (draft: string) => setTabs(previous => ({ ...previous, [kind]: { ...previous[kind], draft } })),
    search: () => void load(kind, undefined, { query: tabsRef.current[kind].draft.trim(), onlyCollection: tabsRef.current[kind].onlyCollection }),
    setCollection: (onlyCollection: boolean) => void load(kind, undefined, { query: tabsRef.current[kind].query, onlyCollection }),
    clearFilters: () => { setTabs(previous => ({ ...previous, [kind]: { ...previous[kind], draft: '' } })); void load(kind, undefined, { query: '', onlyCollection: false }); },
    loadMore: () => { const state = tabsRef.current[kind]; if (state.nextCursor && state.phase === 'idle') void load(kind, state.nextCursor); },
    retry: () => void load(kind, tabsRef.current[kind].failedCursor),
    refresh: () => void load(kind),
  };
}
