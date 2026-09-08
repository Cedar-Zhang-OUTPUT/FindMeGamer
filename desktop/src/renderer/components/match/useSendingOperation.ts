import type { PublicError } from '../../../shared/bridge';
import type { SendBatch, SendingAPI } from '../../../shared/sending';
import { canRetrySending, dispatchSending, freezeSendingAttempt, reconcileSendingReadback, reviewSendingReadback, sendingConnectionChanged,
  sendingInvalidCommand, sendingOutcomeUncertain, sendingReadbackMismatch, sendingWriteUnknown, withSendingConnectionChanged,
  type SendCommand, type SendingAttempt, type SendingReceipt } from './sendingMutation';
export type SendingOperationState = { phase: 'idle'; error: PublicError | null } | { phase: 'running' | 'uncertain'; attempt: SendingAttempt; error: PublicError | null };
export function useSendingOperation(api: SendingAPI) {
  const [state, setState] = useState<SendingOperationState>({ phase: 'idle', error: null });
  const current = useRef(state), alive = useRef(true), inFlight = useRef(false);
  const update = useCallback((next: SendingOperationState) => { current.current = next; if (alive.current) setState(next); }, []);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const dispatch = useCallback(async (attempt: SendingAttempt, replay: boolean): Promise<SendingReceipt | null> => {
    if (inFlight.current || !alive.current) return null;
    inFlight.current = true; update({ phase: 'running', attempt, error: null });
    try {
      const response = await dispatchSending(api, attempt);
      if (!alive.current) return null;
      const visible = current.current.phase === 'idle' ? attempt : current.current.attempt;
      if (visible.connectionChanged) { update({ phase: 'uncertain', attempt: visible, error: sendingConnectionChanged }); return null; }
      if (response.ok) { update({ phase: 'idle', error: null }); return response.data; }
      if (!replay && !sendingOutcomeUncertain(response.error.code)) update({ phase: 'idle', error: response.error });
      else update({ phase: 'uncertain', attempt: response.error.code === 'connection_changed' ? withSendingConnectionChanged(visible) : visible, error: response.error });
      return null;
    } catch {
      if (alive.current) {
        const visible = current.current.phase === 'idle' ? attempt : current.current.attempt;
        update({ phase: 'uncertain', attempt: visible, error: visible.connectionChanged ? sendingConnectionChanged : sendingWriteUnknown });
      }
      return null;
    } finally { inFlight.current = false; }
  }, [api, update]);
  const execute = useCallback((command: SendCommand): Promise<SendingReceipt | null> => {
    if (current.current.phase !== 'idle' || inFlight.current || !alive.current) return Promise.resolve(null);
    let attempt: SendingAttempt;
    try { attempt = freezeSendingAttempt(command); } catch { update({ phase: 'idle', error: sendingInvalidCommand }); return Promise.resolve(null); }
    return dispatch(attempt, false);
  }, [dispatch, update]);
  const retry = useCallback((): Promise<SendingReceipt | null> => {
    const latest = current.current;
    return latest.phase === 'uncertain' && canRetrySending(latest.attempt) ? dispatch(latest.attempt, true) : Promise.resolve(null);
  }, [dispatch]);
  const credentialsChanged = useCallback(() => {
    const latest = current.current;
    if (latest.phase !== 'idle') update({ phase: 'uncertain', attempt: withSendingConnectionChanged(latest.attempt), error: sendingConnectionChanged });
  }, [update]);
  const confirmReadback = useCallback((batch: SendBatch): SendingReceipt | null => {
    const latest = current.current;
    if (inFlight.current || !alive.current || latest.phase !== 'uncertain' || latest.attempt.connectionChanged) return null;
    const receipt = reconcileSendingReadback(latest.attempt, batch);
    update(receipt ? { phase: 'idle', error: null } : { ...latest, error: sendingReadbackMismatch }); return receipt;
  }, [update]);
  const reviewReadback = useCallback((batch: SendBatch): boolean => {
    const latest = current.current;
    if (inFlight.current || !alive.current || latest.phase !== 'uncertain' || latest.attempt.connectionChanged) return false;
    const reviewed = reviewSendingReadback(latest.attempt, batch);
    update(reviewed ? { phase: 'idle', error: null } : { ...latest, error: sendingReadbackMismatch }); return reviewed;
  }, [update]);
  return { state, execute, retry, credentialsChanged, confirmReadback, reviewReadback,
    busy: state.phase === 'running', locked: state.phase === 'uncertain', retryAllowed: state.phase === 'uncertain' && canRetrySending(state.attempt) };
}
import { useCallback, useEffect, useRef, useState } from 'react';
