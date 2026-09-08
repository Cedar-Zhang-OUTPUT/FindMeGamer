// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PublicError, Result } from '../src/shared/bridge';
import type {
  OutreachAPI,
  Preparation,
  PreparationContact,
  PreparationWork,
  RecipientBatchDetail,
  SelectionBulkResult,
} from '../src/shared/outreach';
import { useOutreachOperation } from '../src/renderer/components/match/useOutreachOperation';
import {freezeOutreachAttempt,reconcileOutreachSelections} from '../src/renderer/components/match/outreachMutation';

const ACTIVITY_ID = '10000000-0000-4000-8000-000000000001';
const OTHER_ACTIVITY_ID = '10000000-0000-4000-8000-000000000002';
const SELECTION_A = '20000000-0000-4000-8000-000000000001';
const SELECTION_B = '20000000-0000-4000-8000-000000000002';
const CANDIDATE_A = '30000000-0000-4000-8000-000000000001';
const CANDIDATE_B = '30000000-0000-4000-8000-000000000002';
const CONTACT_A = '40000000-0000-4000-8000-000000000001';
const CONTACT_B = '40000000-0000-4000-8000-000000000002';
const WORK_A = '50000000-0000-4000-8000-000000000001';
const WORK_B = '50000000-0000-4000-8000-000000000002';
const EVALUATION_A = '60000000-0000-4000-8000-000000000001';
const TOKEN_A = 'a'.repeat(64), TOKEN_B = 'b'.repeat(64), TOKEN_C = 'c'.repeat(64);
const unknown: PublicError = { code: 'outreach_outcome_unknown', message: 'Result unconfirmed', retryable: false };
const rejected: PublicError = { code: 'selection_revision_conflict', message: 'Reload this selection', retryable: false };

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

function contact(id = CONTACT_A): PreparationContact {
  return {
    id, email: `${id === CONTACT_A ? 'a' : 'b'}@example.com`, purpose: 'business', source_url: 'https://example.com/contact',
    source_type: 'manual', source_fields: {}, manual_overrides: {}, validation_state: 'valid', identity_revision: 3,
    updated_at: '2026-09-08T00:00:00Z', status: 'eligible',
  };
}

function work(id = WORK_A): PreparationWork {
  return {
    id, creator_id: '70000000-0000-4000-8000-000000000001', platform: 'youtube', source_platform: 'youtube',
    origin: 'manual', revision: 1, identity_revision: 3, is_current_identity: true, source_content_id: null,
    source_collected_at: null, source_fields: {}, manual_overrides: {}, work_name: 'Recorded play', content_title: null,
    content_type: 'gameplay', source_url: 'https://example.com/work', content_id: null, published_at: null, collected_at: null,
    metrics: [], game_id: null, verification_notes: null, evidence_excerpt: null, timestamp_seconds: null,
    relation: 'current_game', evidence_status: 'recorded_evidence',
  };
}

function preparation(patch: Partial<Preparation> = {}): Preparation {
  return {
    id: SELECTION_A, activity_id: ACTIVITY_ID, creator_id: '70000000-0000-4000-8000-000000000001', candidate_id: CANDIDATE_A,
    active: true, revision: 8, identity: { platform: 'youtube', account_id: 'channel-a', revision: 3 }, identity_changed: false,
    game_changed: false, name: 'Creator A', public_name: 'Creator A', public_name_confirmed: true,
    name_confirmed_at: '2026-09-08T00:00:00Z', contact_options: [contact()], selected_contact: contact(), contact_status: 'eligible',
    works: [work()], missing_work_ids: [], evaluation: null, evaluation_run_id: EVALUATION_A, missing_fields: [], context_token: TOKEN_C,
    freeze_ready: true, send_ready: false, sender_watched: false, pending_send_requirements: ['sender_confirmation'], ...patch,
  };
}

function batch(input: { requestId: string; recipients?: Array<{ selectionId: string; revision: number; token: string }> }): RecipientBatchDetail {
  const choices = input.recipients ?? [{ selectionId: SELECTION_A, revision: 7, token: TOKEN_A }, { selectionId: SELECTION_B, revision: 4, token: TOKEN_B }];
  return {
    id: '80000000-0000-4000-8000-000000000001', activity_id: ACTIVITY_ID, request_id: input.requestId, status: 'frozen',
    send_ready: false, recipient_count: choices.length, send_ready_count: 0, needs_repair_count: choices.length,
    created_at: '2026-09-08T00:00:00Z', source_snapshot: {}, recipients: choices.map((choice, index) => ({
      id: `90000000-0000-4000-8000-00000000000${index + 1}`, selection_id: choice.selectionId,
      snapshot: preparation({ id: choice.selectionId, candidate_id: index ? CANDIDATE_B : CANDIDATE_A, revision: choice.revision, context_token: choice.token }),
      preparation: preparation({ id: choice.selectionId, candidate_id: index ? CANDIDATE_B : CANDIDATE_A, revision: choice.revision, context_token: choice.token }),
      source_changed: false, current_missing_fields: [],
    })),
  };
}

function apiMock(): { api: OutreachAPI; methods: { [K in keyof OutreachAPI]: ReturnType<typeof vi.fn<OutreachAPI[K]>> } } {
  const methods = {
    selections: vi.fn<OutreachAPI['selections']>(), selection: vi.fn<OutreachAPI['selection']>(),
    add: vi.fn<OutreachAPI['add']>(), bulk: vi.fn<OutreachAPI['bulk']>(), update: vi.fn<OutreachAPI['update']>(),
    cancel: vi.fn<OutreachAPI['cancel']>(), batches: vi.fn<OutreachAPI['batches']>(), batch: vi.fn<OutreachAPI['batch']>(),
    freeze: vi.fn<OutreachAPI['freeze']>(),
  };
  methods.add.mockResolvedValue({ ok: true, data: preparation() });
  methods.bulk.mockResolvedValue({ ok: true, data: { added_selection_ids: [], cancelled_selection_ids: [] } });
  methods.update.mockResolvedValue({ ok: true, data: preparation() }); methods.cancel.mockResolvedValue({ ok: true, data: preparation({ active: false }) });
  return { api: methods, methods };
}

describe('frozen outreach operations', () => {
  it('never confirms a same-UUID contact choice from an old or different source version',()=>{
    const current={...contact(),purpose:'Updated source',updated_at:'2026-09-09T00:00:00Z'};
    const command={kind:'update' as const,activityId:ACTIVITY_ID,id:SELECTION_A,data:{expected_revision:7,context_token:TOKEN_A,contact_id:CONTACT_A},observedContact:current};
    const attempt=freezeOutreachAttempt(command);
    expect(reconcileOutreachSelections(attempt,[preparation({contact_status:'changed',selected_contact:contact(),contact_options:[current]})])).toBe(false);
    expect(reconcileOutreachSelections(attempt,[preparation({selected_contact:{...current,purpose:'A different later source'}})])).toBe(false);
    expect(reconcileOutreachSelections(attempt,[preparation({selected_contact:current,contact_options:[current]})])).toBe(true);
    const withoutProof=freezeOutreachAttempt({kind:'update',activityId:ACTIVITY_ID,id:SELECTION_A,data:command.data});
    expect(reconcileOutreachSelections(withoutProof,[preparation({selected_contact:current})])).toBe(false);
    expect(attempt.input).not.toHaveProperty('observedContact');expect(attempt.input.data).not.toHaveProperty('observedContact');
  });
  it('submits a double click once and freezes the delayed command, actual input, body, and key against caller mutation', async () => {
    const { api, methods } = apiMock(); let finish!: (value: Result<Preparation>) => void;
    methods.update.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useOutreachOperation(api));
    const data = { expected_revision: 7, context_token: TOKEN_A, contact_id: CONTACT_A, work_ids: [WORK_A] };
    const command = { kind: 'update' as const, activityId: ACTIVITY_ID, id: SELECTION_A, data };
    let pending!: Promise<unknown>;
    act(() => { pending = result.current.execute(command); void result.current.execute(command); });
    data.contact_id = CONTACT_B; data.work_ids.reverse(); data.work_ids.push(WORK_B);
    expect(methods.update).toHaveBeenCalledTimes(1);
    const input = methods.update.mock.calls[0][0];
    expect(input).toMatchObject({ activityId: ACTIVITY_ID, id: SELECTION_A, data: { contact_id: CONTACT_A, work_ids: [WORK_A] } });
    expect(input.idempotencyKey).toMatch(/^[0-9a-f-]{36}$/i);
    expect(Object.isFrozen(input)).toBe(true); expect(Object.isFrozen(input.data)).toBe(true); expect(Object.isFrozen(input.data.work_ids)).toBe(true);
    expect(result.current.state).toMatchObject({ phase: 'running', attempt: { command: { data: { contact_id: CONTACT_A, work_ids: [WORK_A] } }, input } });
    expect(Object.isFrozen(result.current.state.phase === 'idle' ? null : result.current.state.attempt)).toBe(true);
    expect(result.current.state.phase === 'idle' ? null : result.current.state.attempt.startedAt).toEqual(expect.any(Number));
    await act(async () => { finish({ ok: false, error: unknown }); await pending; });
  });

  it('routes every command exactly once and returns a kind-tagged receipt; freeze creates one durable request ID', async () => {
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api));
    const cases = [
      { command: { kind: 'add' as const, activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_A } }, method: methods.add, receipt: preparation() },
      { command: { kind: 'bulk' as const, activityId: ACTIVITY_ID, data: { add_candidate_ids: [CANDIDATE_A] } }, method: methods.bulk, receipt: { added_selection_ids: [SELECTION_A], cancelled_selection_ids: [] } satisfies SelectionBulkResult },
      { command: { kind: 'update' as const, activityId: ACTIVITY_ID, id: SELECTION_A, data: { expected_revision: 7, context_token: TOKEN_A } }, method: methods.update, receipt: preparation() },
      { command: { kind: 'cancel' as const, activityId: ACTIVITY_ID, id: SELECTION_A, data: { expected_revision: 7 } }, method: methods.cancel, receipt: preparation({ active: false }) },
    ];
    for (const item of cases) {
      item.method.mockResolvedValueOnce({ ok: true, data: item.receipt } as never);
      await act(async () => { expect(await result.current.execute(item.command)).toEqual({ kind: item.command.kind, data: item.receipt }); });
      expect(item.method).toHaveBeenCalledTimes(1);
    }
    methods.freeze.mockImplementationOnce(async input => ({ ok: true, data: batch({ requestId: input.data.request_id }) }));
    const command = { kind: 'freeze' as const, activityId: ACTIVITY_ID, data: { recipients: [
      { selection_id: SELECTION_A, expected_revision: 7, context_token: TOKEN_A },
      { selection_id: SELECTION_B, expected_revision: 4, context_token: TOKEN_B },
    ] } };
    await act(async () => { expect((await result.current.execute(command))?.kind).toBe('freeze'); });
    expect(methods.freeze).toHaveBeenCalledTimes(1);
    const input = methods.freeze.mock.calls[0][0];
    expect(input.data.request_id).toMatch(/^[0-9a-f-]{36}$/i); expect(input.data.request_id).not.toBe(input.idempotencyKey);
    expect(input.data.recipients).toEqual(command.data.recipients); expect(Object.isFrozen(input.data.recipients)).toBe(true);
  });

  it('keeps only unknown initial outcomes locked and keeps every deterministic replay rejection locked', async () => {
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api));
    methods.add.mockResolvedValueOnce({ ok: false, error: rejected });
    await act(async () => { expect(await result.current.execute({ kind: 'add', activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_A } })).toBeNull(); });
    expect(result.current.state).toEqual({ phase: 'idle', error: rejected });
    methods.add.mockResolvedValueOnce({ ok: false, error: unknown }).mockResolvedValueOnce({ ok: false, error: rejected });
    await act(async () => { await result.current.execute({ kind: 'add', activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_A } }); });
    expect(result.current.locked).toBe(true);
    await act(async () => { await result.current.retry(); });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', error: rejected }); expect(result.current.retryAllowed).toBe(true);
    expect(methods.add.mock.calls[1][0]).toEqual(methods.add.mock.calls[2][0]);
  });

  it('sanitizes thrown writes, expires nonpersistent replay at 24 hours, and keeps freeze request ID replayable after it', async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-08T00:00:00Z'));
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api));
    methods.add.mockRejectedValueOnce(new Error('SYNTHETIC_PRIVATE_ERROR'));
    await act(async () => { await result.current.execute({ kind: 'add', activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_A } }); });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', error: { code: 'outreach_outcome_unknown' } });
    expect(JSON.stringify(result.current.state)).not.toContain('SYNTHETIC_PRIVATE_ERROR');
    await act(async () => { await vi.advanceTimersByTimeAsync(86_400_001); });
    expect(result.current.retryAllowed).toBe(false); await act(async () => { await result.current.retry(); }); expect(methods.add).toHaveBeenCalledTimes(1);

    const second = apiMock(); const frozen = renderHook(() => useOutreachOperation(second.api));
    second.methods.freeze.mockImplementationOnce(async input => ({ ok: false, error: unknown })).mockImplementationOnce(async input => ({ ok: true, data: batch({ requestId: input.data.request_id }) }));
    await act(async () => { await frozen.result.current.execute({ kind: 'freeze', activityId: ACTIVITY_ID, data: { recipients: [{ selection_id: SELECTION_A, expected_revision: 7, context_token: TOKEN_A }] } }); });
    const initial = structuredClone(second.methods.freeze.mock.calls[0][0]);
    await act(async () => { await vi.advanceTimersByTimeAsync(3 * 86_400_000); });
    expect(frozen.result.current.retryAllowed).toBe(true);
    await act(async () => { await frozen.result.current.retry(); });
    expect(second.methods.freeze.mock.calls[1][0]).toEqual(initial);
  });

  it('reconciles only the exact batch activity, request ID, member order, and snapshot revisions and contexts', async () => {
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api));
    methods.freeze.mockResolvedValueOnce({ ok: false, error: unknown });
    await act(async () => { await result.current.execute({ kind: 'freeze', activityId: ACTIVITY_ID, data: { recipients: [
      { selection_id: SELECTION_A, expected_revision: 7, context_token: TOKEN_A },
      { selection_id: SELECTION_B, expected_revision: 4, context_token: TOKEN_B },
    ] } }); });
    const requestId = methods.freeze.mock.calls[0][0].data.request_id, matching = batch({ requestId });
    const mutations: RecipientBatchDetail[] = [
      { ...matching, activity_id: OTHER_ACTIVITY_ID }, { ...matching, request_id: '80000000-0000-4000-8000-000000000009' },
      { ...matching, recipients: [...matching.recipients].reverse() },
      { ...matching, recipients: matching.recipients.map((item, index) => index ? item : { ...item, snapshot: { ...item.snapshot, revision: 8 } }) },
      { ...matching, recipients: matching.recipients.map((item, index) => index ? item : { ...item, snapshot: { ...item.snapshot, context_token: TOKEN_C } }) },
    ];
    for (const candidate of mutations) act(() => { expect(result.current.confirmBatch(candidate)).toBe(false); });
    expect(result.current.state).toMatchObject({ phase: 'uncertain', error: { code: 'outreach_reconciliation_mismatch' } });
    act(() => { expect(result.current.confirmBatch(matching)).toBe(true); });
    expect(result.current.state).toEqual({ phase: 'idle', error: null });
  });

  it('reconciles add only from the actual requested candidate and never from a cross-query dedup or unrelated record', async () => {
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api)); methods.add.mockResolvedValueOnce({ ok: false, error: unknown });
    await act(async () => { await result.current.execute({ kind: 'add', activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_A } }); });
    act(() => { expect(result.current.confirmSelections([preparation({ candidate_id: CANDIDATE_B })])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([preparation({ activity_id: OTHER_ACTIVITY_ID })])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([preparation({ id: SELECTION_B, candidate_id: CANDIDATE_A, active: false })])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([preparation()])).toBe(true); });
  });

  it('reconciles bulk only when every requested addition and cancellation is proven by its target and newer revision', async () => {
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api)); methods.bulk.mockResolvedValueOnce({ ok: false, error: unknown });
    await act(async () => { await result.current.execute({ kind: 'bulk', activityId: ACTIVITY_ID, data: {
      add_candidate_ids: [CANDIDATE_A], cancel_selections: [{ selection_id: SELECTION_B, expected_revision: 4 }],
    } }); });
    const added = preparation(), cancelled = preparation({ id: SELECTION_B, candidate_id: CANDIDATE_B, active: false, revision: 5 });
    act(() => { expect(result.current.confirmSelections([added])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([added, { ...cancelled, active: true }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([added, { ...cancelled, revision: 4 }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([added, { ...cancelled, revision: 6 }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([added, cancelled])).toBe(true); });
  });

  it('reconciles update only from the target, newer revision, and every explicitly supplied contact, work, evaluation, and name field', async () => {
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api)); methods.update.mockResolvedValueOnce({ ok: false, error: unknown });
    await act(async () => { await result.current.execute({ kind: 'update', activityId: ACTIVITY_ID, id: SELECTION_A, observedContact:contact(), data: {
      expected_revision: 7, context_token: TOKEN_A, contact_id: CONTACT_A, evaluation_run_id: EVALUATION_A,
      work_ids: [WORK_A, WORK_B], confirm_public_name: true,
    } }); });
    const updated = preparation({ works: [work(WORK_A), work(WORK_B)] });
    act(() => { expect(result.current.confirmSelections([{ ...updated, id: SELECTION_B }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([{ ...updated, revision: 7 }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([{ ...updated, selected_contact: contact(CONTACT_B) }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([{ ...updated, works: [work(WORK_A)] }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([{ ...updated, works: [work(WORK_B), work(WORK_A)] }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([{ ...updated, evaluation_run_id: null }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([{ ...updated, public_name_confirmed: false }])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([updated])).toBe(true); });
  });

  it('does not treat omitted update fields as clears and requires an inactive newer cancellation', async () => {
    const { api, methods } = apiMock(); const { result } = renderHook(() => useOutreachOperation(api));
    methods.update.mockResolvedValueOnce({ ok: false, error: unknown });
    await act(async () => { await result.current.execute({ kind: 'update', activityId: ACTIVITY_ID, id: SELECTION_A, data: { expected_revision: 7, context_token: TOKEN_A, confirm_public_name: false } }); });
    act(() => { expect(result.current.confirmSelections([preparation({ selected_contact: contact(), works: [work()], evaluation_run_id: EVALUATION_A, public_name_confirmed: false, name_confirmed_at: null })])).toBe(true); });
    methods.cancel.mockResolvedValueOnce({ ok: false, error: unknown });
    await act(async () => { await result.current.execute({ kind: 'cancel', activityId: ACTIVITY_ID, id: SELECTION_A, data: { expected_revision: 8 } }); });
    act(() => { expect(result.current.confirmSelections([preparation({ active: true, revision: 9 })])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([preparation({ active: false, revision: 8 })])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([preparation({ active: false, revision: 10 })])).toBe(false); });
    act(() => { expect(result.current.confirmSelections([preparation({ active: false, revision: 9 })])).toBe(true); });
  });

  it.each(['success', 'rejection', 'throw'] as const)('fences late %s after credential replacement and blocks retry and reconciliation while in flight', async outcome => {
    const { api, methods } = apiMock(); let resolve!: (value: Result<Preparation>) => void, reject!: (reason: unknown) => void;
    methods.add.mockImplementationOnce(() => new Promise((done, fail) => { resolve = done; reject = fail; }));
    const hook = renderHook(() => useOutreachOperation(api)); let pending!: Promise<unknown>;
    act(() => { pending = hook.result.current.execute({ kind: 'add', activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_A } }); });
    act(() => { expect(hook.result.current.confirmSelections([preparation()])).toBe(false); hook.result.current.credentialsChanged(); });
    await act(async () => {
      if (outcome === 'throw') reject(new Error('SYNTHETIC_PRIVATE_ERROR'));
      else resolve(outcome === 'success' ? { ok: true, data: preparation() } : { ok: false, error: rejected });
      expect(await pending).toBeNull();
    });
    expect(hook.result.current.state).toMatchObject({ phase: 'uncertain', attempt: { connectionChanged: true }, error: { code: 'connection_changed' } });
    expect(hook.result.current.retryAllowed).toBe(false);
    act(() => { expect(hook.result.current.confirmSelections([preparation()])).toBe(true); });
    expect(hook.result.current.state).toEqual({ phase: 'idle', error: null });
    await act(async () => { await hook.result.current.retry(); }); expect(methods.add).toHaveBeenCalledTimes(1);
  });

  it('ignores a late success after unmount', async () => {
    const { api, methods } = apiMock(); let finish!: (value: Result<Preparation>) => void;
    methods.add.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const hook = renderHook(() => useOutreachOperation(api)); let pending!: Promise<unknown>;
    act(() => { pending = hook.result.current.execute({ kind: 'add', activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_A } }); });
    hook.unmount();
    await act(async () => { finish({ ok: true, data: preparation() }); expect(await pending).toBeNull(); });
    expect(methods.add).toHaveBeenCalledTimes(1);
  });
});
