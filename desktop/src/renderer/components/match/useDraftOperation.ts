import { useCallback, useEffect, useRef, useState } from 'react';
import type { PublicError } from '../../../shared/bridge';
import type { CompositionView, DraftsAPI } from '../../../shared/drafts';
import { canRetryDraft, DRAFT_RETRY_WINDOW, dispatchDraft, draftConnectionChanged, draftOutcomeUncertain, draftReadbackMismatch,
  draftWriteUnknown, freezeDraftAttempt, reconcileDraftReadback, reviewDraftReadback, withDraftConnectionChanged,
  type DraftAttempt, type DraftCommand, type DraftReadback, type DraftReceipt } from './draftMutation';
export type DraftOperationState = { phase: 'idle'; error: PublicError | null } | { phase: 'running' | 'uncertain'; attempt: DraftAttempt; error: PublicError | null };
export function useDraftOperation(api: DraftsAPI) {
  const [state, setState] = useState<DraftOperationState>({ phase: 'idle', error: null });
  const current = useRef(state), alive = useRef(true), inFlight = useRef(false);
  const [, tick] = useState(0);
  const update = useCallback((next: DraftOperationState) => {
    current.current = next;
    if (alive.current) setState(next);
  }, []);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (state.phase !== 'uncertain' || state.attempt.command.kind !== 'registerCanonical' || state.attempt.connectionChanged) return;
    const remaining = state.attempt.startedAt + DRAFT_RETRY_WINDOW - Date.now();
    if (remaining <= 0) return;
    const timer = setTimeout(() => tick(value => value + 1), remaining);
    return () => clearTimeout(timer);
  }, [state]);

  const dispatch = useCallback(async (attempt: DraftAttempt, replay: boolean): Promise<DraftReceipt | null> => {
    if (inFlight.current || !alive.current) return null;
    inFlight.current = true;
    update({ phase: 'running', attempt, error: null });
    try {
      const response = await dispatchDraft(api, attempt);
      if (!alive.current) return null;
      const visible = current.current.phase === 'idle' ? attempt : current.current.attempt;
      if (visible.connectionChanged) {
        update({ phase: 'uncertain', attempt: visible, error: draftConnectionChanged });
        return null;
      }
      if (response.ok) {
        update({ phase: 'idle', error: null });
        return response.data;
      }
      if (!replay && !draftOutcomeUncertain(response.error.code)) update({ phase: 'idle', error: response.error });
      else update({ phase: 'uncertain', attempt: response.error.code === 'connection_changed' ? withDraftConnectionChanged(visible) : visible, error: response.error });
      return null;
    } catch {
      if (alive.current) {
        const visible = current.current.phase === 'idle' ? attempt : current.current.attempt;
        update({ phase: 'uncertain', attempt: visible, error: visible.connectionChanged ? draftConnectionChanged : draftWriteUnknown });
      }
      return null;
    } finally { inFlight.current = false; }
  }, [api, update]);
  const execute = useCallback((command: DraftCommand): Promise<DraftReceipt | null> => {
    if (current.current.phase !== 'idle' || inFlight.current || !alive.current) return Promise.resolve(null);
    return dispatch(freezeDraftAttempt(command), false);
  }, [dispatch]);
  const retry = useCallback((): Promise<DraftReceipt | null> => {
    const latest = current.current;
    return latest.phase === 'uncertain' && canRetryDraft(latest.attempt) ? dispatch(latest.attempt, true) : Promise.resolve(null);
  }, [dispatch]);
  const credentialsChanged = useCallback(() => {
    const latest = current.current;
    if (latest.phase !== 'idle') update({ phase: 'uncertain', attempt: withDraftConnectionChanged(latest.attempt), error: draftConnectionChanged });
  }, [update]);
  const confirmReadback = useCallback((readback: DraftReadback): DraftReceipt | null => {
    const latest = current.current;
    if (inFlight.current || !alive.current || latest.phase !== 'uncertain' || latest.attempt.connectionChanged) return null;
    const receipt = reconcileDraftReadback(latest.attempt, readback);
    update(receipt ? { phase: 'idle', error: null } : { ...latest, error: draftReadbackMismatch });
    return receipt;
  }, [update]);
  const reviewReadback = useCallback((data: CompositionView): boolean => {
    const latest = current.current;
    if (inFlight.current || !alive.current || latest.phase !== 'uncertain' || latest.attempt.connectionChanged) return false;
    const reviewed = reviewDraftReadback(latest.attempt, data);
    update(reviewed ? { phase: 'idle', error: null } : { ...latest, error: draftReadbackMismatch });
    return reviewed;
  }, [update]);
  return { state, execute, retry, credentialsChanged, confirmReadback, reviewReadback,
    busy: state.phase === 'running', locked: state.phase === 'uncertain', retryAllowed: state.phase === 'uncertain' && canRetryDraft(state.attempt) };
}
