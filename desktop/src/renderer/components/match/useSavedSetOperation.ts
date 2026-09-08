import { useCallback, useEffect, useRef, useState } from 'react';
import type { PublicError } from '../../../shared/bridge';
import type { SavedSetsAPI, SavedSetView } from '../../../shared/savedSets';
import { matchRejected } from './matchMutation';

export interface SaveSetCommand { queryId: string; name: string; candidateIds: string[] }
export interface SavedSetAttempt { input: Parameters<SavedSetsAPI['create']>[0]; connectionChanged: boolean }
export type SavedSetOperationState = { phase: 'idle'; error: PublicError | null }
  | { phase: 'running' | 'uncertain'; attempt: SavedSetAttempt; error: PublicError | null };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isUUID = (value: unknown): value is string => typeof value === 'string' && uuid.test(value);
const invalid: PublicError = { code: 'request_invalid', message: 'Enter a name and choose 1–600 candidates from this discovery query.', retryable: false };
const unknown: PublicError = { code: 'save_outcome_unknown', message: 'The named set may already be saved. Check saved sets or retry the same request.', retryable: false };
const changed: PublicError = { code: 'connection_changed', message: 'Credentials changed. Check the original workspace for the saved set before starting another request.', retryable: false };
const mismatch: PublicError = { code: 'saved_set_mismatch', message: 'This named set does not match the original query, name, and candidate membership. Choose the matching saved set.', retryable: false };
const rejected = new Set(['saved_set_members_invalid', 'saved_set_request_conflict', 'saved_set_not_found']);

function valid(command: SaveSetCommand): boolean {
  return Boolean(command && isUUID(command.queryId) && typeof command.name === 'string' && command.name.trim()
    && [...command.name].length <= 255 && Array.isArray(command.candidateIds)
    && command.candidateIds.length >= 1 && command.candidateIds.length <= 600
    && Array.from(command.candidateIds).every(isUUID));
}
function freeze(command: SaveSetCommand): SavedSetAttempt {
  const input = { queryId: command.queryId, data: { request_id: crypto.randomUUID(), name: command.name, candidate_ids: [...command.candidateIds] }, idempotencyKey: crypto.randomUUID() };
  Object.freeze(input.data.candidate_ids); Object.freeze(input.data); Object.freeze(input);
  return { input, connectionChanged: false };
}
function matches(attempt: SavedSetAttempt, metadata: SavedSetView): boolean {
  const { queryId, data } = attempt.input, ids = [...new Set(data.candidate_ids.map(id => id.toLowerCase()))];
  return Boolean(metadata && isUUID(metadata.id) && isUUID(metadata.query_id) && metadata.query_id.toLowerCase() === queryId.toLowerCase()
    && metadata.name === data.name.trim() && metadata.count === ids.length && Array.isArray(metadata.candidate_ids)
    && metadata.candidate_ids.length === ids.length && Array.from(metadata.candidate_ids).every((id, index) => isUUID(id) && id.toLowerCase() === ids[index]));
}

/** Explicit named-set saves retain their persistent request ID beyond HTTP replay retention. */
export function useSavedSetOperation(api: Pick<SavedSetsAPI, 'create'>) {
  const [state, setState] = useState<SavedSetOperationState>({ phase: 'idle', error: null });
  const current = useRef(state), alive = useRef(true), inFlight = useRef(false);
  const update = useCallback((next: SavedSetOperationState) => { current.current = next; if (alive.current) setState(next); }, []);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const dispatch = useCallback(async (attempt: SavedSetAttempt, replay: boolean): Promise<SavedSetView | null> => {
    if (inFlight.current) return null;
    inFlight.current = true; update({ phase: 'running', attempt, error: null });
    try {
      const response = await api.create(attempt.input);
      if (!alive.current) return null;
      const latest = current.current.phase === 'idle' ? attempt : current.current.attempt;
      if (latest.connectionChanged) { update({ phase: 'uncertain', attempt: latest, error: changed }); return null; }
      if (response.ok) { update({ phase: 'idle', error: null }); return response.data; }
      if (!replay && (matchRejected(response.error.code) || rejected.has(response.error.code))) update({ phase: 'idle', error: response.error });
      else update({ phase: 'uncertain', attempt: { ...latest, connectionChanged: response.error.code === 'connection_changed' }, error: response.error });
      return null;
    } catch {
      if (alive.current) {
        const latest = current.current.phase === 'idle' ? attempt : current.current.attempt;
        update({ phase: 'uncertain', attempt: latest, error: latest.connectionChanged ? changed : unknown });
      }
      return null;
    } finally { inFlight.current = false; }
  }, [api, update]);
  const execute = useCallback((command: SaveSetCommand): Promise<SavedSetView | null> => {
    if (current.current.phase !== 'idle' || inFlight.current) return Promise.resolve(null);
    if (!valid(command)) { update({ phase: 'idle', error: invalid }); return Promise.resolve(null); }
    return dispatch(freeze(command), false);
  }, [dispatch, update]);
  const retry = useCallback((): Promise<SavedSetView | null> => {
    const latest = current.current;
    return latest.phase === 'uncertain' && !latest.attempt.connectionChanged ? dispatch(latest.attempt, true) : Promise.resolve(null);
  }, [dispatch]);
  const credentialsChanged = useCallback(() => {
    const latest = current.current;
    if (latest.phase !== 'idle') update({ ...latest, attempt: { ...latest.attempt, connectionChanged: true }, error: changed });
  }, [update]);
  const confirmSaved = useCallback((metadata: SavedSetView): boolean => {
    const latest = current.current;
    if (inFlight.current || latest.phase !== 'uncertain') return false;
    if (!matches(latest.attempt, metadata)) { update({ ...latest, error: mismatch }); return false; }
    update({ phase: 'idle', error: null }); return true;
  }, [update]);
  return { state, execute, retry, confirmSaved, credentialsChanged, busy: state.phase === 'running', locked: state.phase === 'uncertain',
    retryAllowed: state.phase === 'uncertain' && !state.attempt.connectionChanged };
}
