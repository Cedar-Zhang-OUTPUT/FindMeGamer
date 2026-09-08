// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PublicError, Result } from '../src/shared/bridge';
import type { SavedSetsAPI, SavedSetView } from '../src/shared/savedSets';
import { useSavedSetOperation } from '../src/renderer/components/match/useSavedSetOperation';
import { ACTIVITY_ID, CANDIDATE_ID, QUERY_ID } from './match-fixtures';
import { SECOND_CANDIDATE_ID, savedSetFixture } from './saved-set-fixtures';

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
const lost: PublicError = { code: 'save_outcome_unknown', message: 'Save unconfirmed', retryable: false };
const command = () => ({ queryId: QUERY_ID, name: '  Launch shortlist  ', candidateIds: [SECOND_CANDIDATE_ID, CANDIDATE_ID, SECOND_CANDIDATE_ID.toUpperCase()] });
const ok = (data: SavedSetView): Result<SavedSetView> => ({ ok: true, data });
function setup() {
  const api = { create: vi.fn<SavedSetsAPI['create']>().mockResolvedValue(ok(savedSetFixture())) };
  const hook = renderHook(() => useSavedSetOperation(api));
  return { ...hook, api };
}

describe('Saved-set frozen operation', () => {
  it('blocks duplicate starts and freezes independent IDs and caller input across explicit retries', async () => {
    const { api, result } = setup(); let finish!: (value: Result<SavedSetView>) => void;
    api.create.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const input = command(); let pending!: Promise<SavedSetView | null>;
    act(() => { pending = result.current.execute(input); });
    input.name = 'Changed'; input.candidateIds.reverse(); input.candidateIds.push(ACTIVITY_ID);
    await act(async () => { expect(await result.current.execute(command())).toBeNull(); });
    expect(result.current.busy).toBe(true); expect(api.create).toHaveBeenCalledTimes(1);
    const frozen = structuredClone(api.create.mock.calls[0][0]);
    expect(frozen).toMatchObject({ queryId: QUERY_ID, data: { name: '  Launch shortlist  ', candidate_ids: [SECOND_CANDIDATE_ID, CANDIDATE_ID, SECOND_CANDIDATE_ID.toUpperCase()] } });
    expect(frozen.data.request_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(frozen.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);
    expect(frozen.data.request_id).not.toBe(frozen.idempotencyKey);
    await act(async () => { finish({ ok: false, error: lost }); expect(await pending).toBeNull(); });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', error: lost, attempt: { input: frozen, connectionChanged: false } });
    await act(async () => { expect(await result.current.execute(command())).toBeNull(); });
    expect(api.create).toHaveBeenCalledTimes(1);
    await act(async () => { expect(await result.current.retry()).toEqual(savedSetFixture()); });
    expect(api.create.mock.calls[1][0]).toEqual(frozen);
    expect(result.current.state).toEqual({ phase: 'idle', error: null });
  });

  it('keeps persistent request ID and HTTP key replayable after the 24-hour HTTP retention window', async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-08T00:00:00Z'));
    const { api, result } = setup(); api.create.mockResolvedValueOnce({ ok: false, error: lost });
    await act(async () => { await result.current.execute(command()); });
    const frozen = structuredClone(api.create.mock.calls[0][0]);
    await act(async () => { await vi.advanceTimersByTimeAsync(3 * 86_400_000); });
    expect(api.create).toHaveBeenCalledTimes(1); expect(result.current.retryAllowed).toBe(true);
    await act(async () => { await result.current.retry(); });
    expect(api.create.mock.calls[1][0]).toEqual(frozen);
  });

  it.each(['success', 'rejection', 'throw'] as const)('fences late %s after credential replacement and never permits replay', async outcome => {
    const { api, result } = setup(); let resolve!: (value: Result<SavedSetView>) => void, reject!: (reason: unknown) => void;
    api.create.mockImplementationOnce(() => new Promise((done, fail) => { resolve = done; reject = fail; }));
    let pending!: Promise<SavedSetView | null>;
    act(() => { pending = result.current.execute(command()); });
    act(() => { result.current.credentialsChanged(); });
    await act(async () => {
      if (outcome === 'throw') reject(new Error('SYNTHETIC_PRIVATE_ERROR'));
      else resolve(outcome === 'success' ? ok(savedSetFixture()) : { ok: false, error: { code: 'request_invalid', message: 'Rejected', retryable: false } });
      expect(await pending).toBeNull();
    });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', attempt: { connectionChanged: true }, error: { code: 'connection_changed' } });
    expect(result.current.retryAllowed).toBe(false);
    await act(async () => { await result.current.retry(); });
    expect(api.create).toHaveBeenCalledTimes(1);
  });

  it('keeps every rejected replay uncertain, while an initial definite rejection remains editable', async () => {
    const { api, result } = setup();
    const rejection: PublicError = { code: 'saved_set_members_invalid', message: 'Choose this query’s candidates', retryable: false };
    api.create.mockResolvedValueOnce({ ok: false, error: rejection }).mockResolvedValueOnce({ ok: false, error: lost }).mockResolvedValueOnce({ ok: false, error: rejection });
    await act(async () => { await result.current.execute(command()); });
    expect(result.current.state).toEqual({ phase: 'idle', error: rejection });
    await act(async () => { await result.current.execute(command()); });
    const frozen = structuredClone(api.create.mock.calls[1][0]);
    await act(async () => { await result.current.retry(); });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', error: rejection, attempt: { input: frozen } });
    expect(result.current.locked).toBe(true); expect(result.current.retryAllowed).toBe(true);
  });

  it('converts thrown saves to a safe unknown error without repeating them', async () => {
    const { api, result } = setup(); api.create.mockRejectedValueOnce(new Error('SYNTHETIC_PRIVATE_ERROR'));
    await act(async () => { expect(await result.current.execute(command())).toBeNull(); });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', error: { code: 'save_outcome_unknown', retryable: false } });
    expect(JSON.stringify(result.current.state)).not.toContain('SYNTHETIC_PRIVATE_ERROR');
    expect(api.create).toHaveBeenCalledTimes(1);
  });

  it.each([
    { queryId: 'bad-query' }, { name: ' \t\n' }, { name: '🎮'.repeat(256) },
    { candidateIds: [] }, { candidateIds: ['bad-candidate'] }, { candidateIds: Array(601).fill(CANDIDATE_ID) },
  ])('rejects invalid intent before generating a save: %j', async patch => {
    const { api, result } = setup();
    await act(async () => { expect(await result.current.execute({ ...command(), ...patch })).toBeNull(); });
    expect(result.current.state).toMatchObject({ phase: 'idle', error: { code: 'request_invalid' } });
    expect(api.create).not.toHaveBeenCalled();
  });

  it.each([
    { query_id: ACTIVITY_ID }, { name: 'Other list' }, { candidate_ids: [CANDIDATE_ID, SECOND_CANDIDATE_ID] },
    { candidate_ids: [CANDIDATE_ID], count: 1 }, { candidate_ids: [CANDIDATE_ID, CANDIDATE_ID] }, { count: 1 },
  ])('retains the frozen attempt when reconciliation does not match: %j', async patch => {
    const { api, result } = setup(); api.create.mockResolvedValueOnce({ ok: false, error: lost });
    await act(async () => { await result.current.execute(command()); });
    act(() => { expect(result.current.confirmSaved({ ...savedSetFixture(), ...patch })).toBe(false); });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', error: { code: 'saved_set_mismatch' } });
    expect(result.current.locked).toBe(true); expect(api.create).toHaveBeenCalledTimes(1);
  });

  it('reconciles only the canonical saved membership and never clears an in-flight request', async () => {
    const { api, result } = setup(); let finish!: (value: Result<SavedSetView>) => void;
    api.create.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    let pending!: Promise<SavedSetView | null>;
    act(() => { pending = result.current.execute(command()); });
    act(() => { expect(result.current.confirmSaved(savedSetFixture())).toBe(false); });
    expect(result.current.busy).toBe(true);
    await act(async () => { finish({ ok: false, error: lost }); await pending; });
    act(() => { result.current.credentialsChanged(); });
    expect(result.current.retryAllowed).toBe(false);
    act(() => { expect(result.current.confirmSaved(savedSetFixture())).toBe(true); });
    expect(result.current.state).toEqual({ phase: 'idle', error: null });
    expect(result.current.locked).toBe(false); expect(api.create).toHaveBeenCalledTimes(1);
  });
});
