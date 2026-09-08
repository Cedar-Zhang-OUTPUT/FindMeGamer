import { useCallback, useEffect, useRef, useState } from 'react';
import type { PublicError } from '../../../shared/bridge';
import type { OutreachAPI, Preparation, RecipientBatchDetail } from '../../../shared/outreach';
import {
  OUTREACH_RETRY_WINDOW,
  canRetryOutreach,
  dispatchOutreach,
  freezeOutreachAttempt,
  outreachConnectionChanged,
  outreachOutcomeUncertain,
  outreachReconciliationMismatch,
  outreachWriteUnknown,
  reconcileOutreachBatch,
  reconcileOutreachSelections,
  withOutreachConnectionChanged,
  type OutreachAttempt,
  type OutreachCommand,
  type OutreachReceipt,
} from './outreachMutation';

export type OutreachOperationState = { phase: 'idle'; error: PublicError | null }
  | { phase: 'running' | 'uncertain'; attempt: OutreachAttempt; error: PublicError | null };

export function useOutreachOperation(api: OutreachAPI) {
  const [state, setState] = useState<OutreachOperationState>({ phase: 'idle', error: null });
  const current = useRef(state), alive = useRef(true), inFlight = useRef(false);
  const [, tick] = useState(0);
  const update = useCallback((next: OutreachOperationState) => {
    current.current = next;
    if (alive.current) setState(next);
  }, []);

  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (state.phase !== 'uncertain' || state.attempt.command.kind === 'freeze' || state.attempt.connectionChanged) return;
    const remaining = state.attempt.startedAt + OUTREACH_RETRY_WINDOW - Date.now();
    if (remaining < 0) return;
    const timer = setTimeout(() => tick(value => value + 1), remaining + 1);
    return () => clearTimeout(timer);
  }, [state]);

  const dispatch = useCallback(async (attempt: OutreachAttempt, replay: boolean): Promise<OutreachReceipt | null> => {
    if (inFlight.current) return null;
    inFlight.current = true;
    update({ phase: 'running', attempt, error: null });
    try {
      const response = await dispatchOutreach(api, attempt);
      if (!alive.current) return null;
      const visible = current.current.phase === 'idle' ? attempt : current.current.attempt;
      if (visible.connectionChanged) {
        update({ phase: 'uncertain', attempt: visible, error: outreachConnectionChanged });
        return null;
      }
      if (response.ok) {
        update({ phase: 'idle', error: null });
        return response.data;
      }
      if (!replay && !outreachOutcomeUncertain(response.error.code)) {
        update({ phase: 'idle', error: response.error });
      } else {
        const changed = response.error.code === 'connection_changed' ? withOutreachConnectionChanged(visible) : visible;
        update({ phase: 'uncertain', attempt: changed, error: response.error });
      }
      return null;
    } catch {
      if (alive.current) {
        const visible = current.current.phase === 'idle' ? attempt : current.current.attempt;
        update({ phase: 'uncertain', attempt: visible, error: visible.connectionChanged ? outreachConnectionChanged : outreachWriteUnknown });
      }
      return null;
    } finally {
      inFlight.current = false;
    }
  }, [api, update]);

  const execute = useCallback((command: OutreachCommand): Promise<OutreachReceipt | null> => {
    if (current.current.phase !== 'idle' || inFlight.current) return Promise.resolve(null);
    return dispatch(freezeOutreachAttempt(command), false);
  }, [dispatch]);
  const retry = useCallback((): Promise<OutreachReceipt | null> => {
    const latest = current.current;
    return latest.phase === 'uncertain' && canRetryOutreach(latest.attempt) ? dispatch(latest.attempt, true) : Promise.resolve(null);
  }, [dispatch]);
  const credentialsChanged = useCallback(() => {
    const latest = current.current;
    if (latest.phase === 'idle') return;
    update({ phase: 'uncertain', attempt: withOutreachConnectionChanged(latest.attempt), error: outreachConnectionChanged });
  }, [update]);
  const confirmBatch = useCallback((batch: RecipientBatchDetail): boolean => {
    const latest = current.current;
    if (inFlight.current || latest.phase !== 'uncertain' || !reconcileOutreachBatch(latest.attempt, batch)) {
      if (!inFlight.current && latest.phase === 'uncertain') update({ ...latest, error: outreachReconciliationMismatch });
      return false;
    }
    update({ phase: 'idle', error: null });
    return true;
  }, [update]);
  const confirmSelections = useCallback((preparations: Preparation[]): boolean => {
    const latest = current.current;
    if (inFlight.current || latest.phase !== 'uncertain' || !reconcileOutreachSelections(latest.attempt, preparations)) {
      if (!inFlight.current && latest.phase === 'uncertain') update({ ...latest, error: outreachReconciliationMismatch });
      return false;
    }
    update({ phase: 'idle', error: null });
    return true;
  }, [update]);
  return {
    state, execute, retry, confirmBatch, confirmSelections, credentialsChanged,
    busy: state.phase === 'running', locked: state.phase === 'uncertain',
    retryAllowed: state.phase === 'uncertain' && canRetryOutreach(state.attempt),
  };
}
