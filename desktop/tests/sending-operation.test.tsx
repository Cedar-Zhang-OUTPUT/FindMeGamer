// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Delivery, Qualification, SendBatch, SendingAPI } from '../src/shared/sending';
import type { Result } from '../src/shared/bridge';
import { freezeSendingAttempt, reconcileSendingReadback, reviewSendingReadback, type SendCommand } from '../src/renderer/components/match/sendingMutation';
import { useSendingOperation } from '../src/renderer/components/match/useSendingOperation';
const token = 'a'.repeat(64), stamp = '2026-09-08T12:00:00Z';
function qualification(): Qualification {
  return { composition_id: 'composition', activity_id: 'activity', qualification_token: token, sending_account_token: 'b'.repeat(64), total_count: 1, eligible_count: 1, repair_count: 0, excluded_count: 0,
    sender: { address: 'synthetic@example.invalid', name: 'Synthetic sender', reply_to: 'reply@example.invalid' }, send_ready: true,
    members: [{ draft_id: 'draft', recipient_snapshot_id: 'recipient', status: 'eligible', missing_fields: [], exclusion_reason: null,
      recipient_email: 'recipient@example.invalid', subject: 'Frozen subject', html: '<p>Frozen message</p>', text: 'Frozen message',
      values: { firstName: 'Ari', channelName: 'Channel', reference: 'Recorded work', observation: 'A recorded detail.' }, slot_sources: { source: 'recorded' },
      template_version_id: 'template', fixed_hash: token, revision: 1, context_token: token, sender_facts: { following: true, enjoyed: true, liked: true },
      identity: { platform: 'youtube', account_id: 'synthetic', revision: 1 }, blocking_delivery_id: null }] };
}
function delivery(patch: Partial<Delivery> = {}): Delivery {
  const q = qualification();
  return { id: 'delivery', send_batch_id: 'batch', draft_id: 'draft', recipient_snapshot_id: 'recipient', snapshot: { ...q.members[0], status: 'eligible', sender: q.sender, sending_account_token: q.sending_account_token },
    state: 'failed', attempt: 2, retryable: true, error_code: 'smtp_temporarily_unavailable', sending_at: stamp, sent_at: null, failed_at: stamp, resolution: {}, ...patch };
}
function batch(row = delivery()): SendBatch { return { id: 'batch', composition_id: 'composition', activity_id: 'activity', qualification: qualification(), created_at: stamp, deliveries: [row] }; }
const send = (): Extract<SendCommand, { kind: 'send' }> => ({ kind: 'send', compositionId: 'composition', data: { qualification_token: token, excluded: [] }, observedQualification: qualification() });
const retry = (row = delivery()): Extract<SendCommand, { kind: 'retry' }> => ({ kind: 'retry', id: row.id, data: { expected_attempt: row.attempt }, observedDelivery: row });
const resolve = (outcome: 'sent' | 'not_sent' = 'sent'): Extract<SendCommand, { kind: 'resolve' }> => ({ kind: 'resolve', id: 'delivery', data: { expected_attempt: 2, outcome, source_note: 'Verified against synthetic capture log.' }, observedDelivery: delivery({ state: 'unknown', retryable: false, error_code: 'smtp_outcome_unknown' }) });
function resolved(outcome: 'sent' | 'not_sent' = 'sent'): Delivery {
  return delivery({ state: outcome === 'sent' ? 'sent' : 'failed', retryable: outcome === 'not_sent', error_code: outcome === 'sent' ? null : 'submission_verified_not_sent',
    sent_at: outcome === 'sent' ? stamp : null, failed_at: outcome === 'not_sent' ? stamp : null,
    resolution: { outcome, source_note: 'Verified against synthetic capture log.', at: stamp, attempt: 2 } });
}
const unknown = { ok: false as const, error: { code: 'send_queue_unavailable', message: 'Saved; queue unavailable', retryable: false } };
function mock(): { [K in keyof SendingAPI]: ReturnType<typeof vi.fn<SendingAPI[K]>> } {
  return { qualify: vi.fn(), batches: vi.fn(), batch: vi.fn(), send: vi.fn(async () => ({ ok: true as const, data: batch(delivery({ state: 'queued', retryable: false, error_code: null })) })),
    retry: vi.fn(async () => ({ ok: true as const, data: delivery({ state: 'queued', retryable: false, error_code: null }) })), resolve: vi.fn(async () => ({ ok: true as const, data: resolved() })) };
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it('freezes one durable send UUID/key/body and never generates mutation keys for retry or resolution', () => {
  const random = vi.spyOn(crypto, 'randomUUID'), command = send(); const attempt = freezeSendingAttempt(command);
  expect(random).toHaveBeenCalledTimes(2); expect(attempt.input).toHaveProperty('data.request_id'); expect(attempt.input).toHaveProperty('idempotencyKey');
  expect(attempt.input).not.toHaveProperty('observedQualification'); expect(Object.isFrozen(attempt.command)).toBe(true);
  command.observedQualification.members[0].text = 'Caller changed content'; expect(attempt.command).toHaveProperty('observedQualification.members.0.text', 'Frozen message');
  expect(freezeSendingAttempt(retry()).input).toEqual({ id: 'delivery', data: { expected_attempt: 2 } });
  expect(freezeSendingAttempt(resolve()).input).not.toHaveProperty('idempotencyKey'); expect(random).toHaveBeenCalledTimes(2);
});
it('rejects stale qualification, false readiness, omitted or mismatched exclusions before a send is dispatched', async () => {
  const api = mock(), hook = renderHook(() => useSendingOperation(api));
  const variants = [send(), send(), send(), send()];
  if (variants[0].kind === 'send') variants[0].data.qualification_token = 'c'.repeat(64);
  if (variants[1].kind === 'send') variants[1].observedQualification.send_ready = false;
  if (variants[2].kind === 'send') variants[2].observedQualification.total_count = 2;
  if (variants[3].kind === 'send') variants[3].data.excluded = [{ draft_id: 'foreign', reason: 'Not selected' }];
  for (const command of variants) await act(async () => { expect(await hook.result.current.execute(command)).toBeNull(); });
  expect(api.send).not.toHaveBeenCalled(); expect(hook.result.current.state.phase).toBe('idle');
});
it('preserves every excluded member and its reason, rejecting a success that silently drops the excluded member', async () => {
  const api = mock(), command = send(), q = command.observedQualification;
  q.members.push({ ...q.members[0], draft_id: 'excluded-draft', recipient_snapshot_id: 'excluded-recipient', status: 'excluded', exclusion_reason: 'Different audience', recipient_email: null, html: null, text: null });
  q.total_count = 2; q.excluded_count = 1; command.data.excluded = [{ draft_id: 'excluded-draft', reason: 'Different audience' }];
  const exact = { ...batch(), qualification: q }; api.send.mockResolvedValueOnce({ ok: true, data: exact }).mockResolvedValueOnce({ ok: true, data: batch() });
  const hook = renderHook(() => useSendingOperation(api));
  await act(async () => { expect((await hook.result.current.execute(command))?.data).toEqual(exact); });
  expect(api.send.mock.calls[0][0].data.excluded).toEqual([{ draft_id: 'excluded-draft', reason: 'Different audience' }]);
  await act(async () => { expect(await hook.result.current.execute(command)).toBeNull(); }); expect(hook.result.current.locked).toBe(true);
});
it.each(['unknown', 'sent', 'sending'] as const)('never dispatches a normal retry from %s', async state => {
  const api = mock(), hook = renderHook(() => useSendingOperation(api));
  await act(async () => { await hook.result.current.execute(retry(delivery({ state }))); }); expect(api.retry).not.toHaveBeenCalled();
});
it('rejects wrong attempts, blank resolution notes, and resolution of a definite failure', async () => {
  const api = mock(), hook = renderHook(() => useSendingOperation(api));
  const first = retry(); first.data.expected_attempt = 1; const second = resolve(); second.data.source_note = '  '; const third = resolve(); third.observedDelivery.state = 'failed';
  for (const command of [first, second, third]) await act(async () => { await hook.result.current.execute(command); });
  expect(api.retry).not.toHaveBeenCalled(); expect(api.resolve).not.toHaveBeenCalled();
});
it('suppresses duplicate sends and replays the original durable request after days without requalification', async () => {
  const api = mock(); let finish!: (value: Result<SendBatch>) => void;
  api.send.mockImplementationOnce(() => new Promise(done => { finish = done; })); const hook = renderHook(() => useSendingOperation(api)); let pending!: Promise<unknown>;
  act(() => { pending = hook.result.current.execute(send()); void hook.result.current.execute(send()); }); expect(api.send).toHaveBeenCalledTimes(1);
  await act(async () => { finish(unknown); await pending; }); const input = api.send.mock.calls[0][0];
  vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 4 * 86_400_000);
  await act(async () => { expect((await hook.result.current.retry())?.kind).toBe('send'); });
  expect(api.send.mock.calls[1][0]).toBe(input); expect(api.qualify).not.toHaveBeenCalled(); expect(hook.result.current.state.phase).toBe('idle');
});
it.each(['sending_write_unknown', 'send_queue_unavailable', 'network_error'])('locks %s and never blindly replays attempt writes', async code => {
  const api = mock(); api.retry.mockResolvedValueOnce({ ok: false, error: { code, message: 'Uncertain', retryable: false } }); const hook = renderHook(() => useSendingOperation(api));
  await act(async () => { await hook.result.current.execute(retry()); await hook.result.current.retry(); await hook.result.current.execute(retry()); });
  expect(api.retry).toHaveBeenCalledTimes(1); expect(hook.result.current.locked).toBe(true); expect(hook.result.current.retryAllowed).toBe(false);
});
it('does not infer lost final-send identity from matching qualification and delivery snapshots', () => {
  const attempt = freezeSendingAttempt(send()); expect(reconcileSendingReadback(attempt, batch())).toBeNull(); expect(reviewSendingReadback(attempt, batch())).toBe(false);
});
it('reconciles exact resolution or explicitly reviews advanced attempts only after the request settles', async () => {
  const api = mock(); api.resolve.mockResolvedValueOnce(unknown); const hook = renderHook(() => useSendingOperation(api));
  await act(async () => { await hook.result.current.execute(resolve()); });
  act(() => { expect(hook.result.current.confirmReadback(batch(resolved()))?.kind).toBe('resolve'); }); expect(hook.result.current.locked).toBe(false);
  let finish!: (value: Result<Delivery>) => void; api.retry.mockImplementationOnce(() => new Promise(done => { finish = done; })); let pending!: Promise<unknown>;
  act(() => { pending = hook.result.current.execute(retry()); expect(hook.result.current.reviewReadback(batch(delivery({ attempt: 3 })))).toBe(false); });
  await act(async () => { finish(unknown); await pending; });
  act(() => { expect(hook.result.current.reviewReadback(batch(delivery({ state: 'queued' })))).toBe(false); }); expect(hook.result.current.locked).toBe(true);
  act(() => { expect(hook.result.current.reviewReadback(batch(delivery({ attempt: 3, state: 'unknown' })))).toBe(true); }); expect(hook.result.current.state.phase).toBe('idle');
});
it('ignores a late final-send success after unmount', async () => {
  const api = mock(); let finish!: (value: Result<SendBatch>) => void; api.send.mockImplementationOnce(() => new Promise(done => { finish = done; }));
  const hook = renderHook(() => useSendingOperation(api)); let pending!: Promise<unknown>;
  act(() => { pending = hook.result.current.execute(send()); }); hook.unmount();
  await act(async () => { finish({ ok: true, data: batch() }); expect(await pending).toBeNull(); });
});
it('requires a strictly advanced attempt to review an uncertain retry, never same-attempt queued or terminal state', () => {
  const attempt = freezeSendingAttempt(retry());
  for (const state of ['queued', 'sending', 'sent', 'failed', 'unknown'] as const) {
    expect(reconcileSendingReadback(attempt, batch(delivery({ state })))).toBeNull(); expect(reviewSendingReadback(attempt, batch(delivery({ state })))).toBe(false);
  }
  expect(reviewSendingReadback(attempt, batch(delivery({ attempt: 3, state: 'sending' })))).toBe(true);
  expect(reviewSendingReadback(attempt, batch(delivery({ attempt: 3, snapshot: { ...delivery().snapshot, text: 'Different frozen mail' } })))).toBe(false);
  expect(reviewSendingReadback(attempt, { ...batch(delivery({ attempt: 3 })), id: 'foreign' })).toBe(false);
});
it.each(['sent', 'not_sent'] as const)('confirms resolution %s only with exact attempt, note, terminal flags and frozen identity/content', outcome => {
  const attempt = freezeSendingAttempt(resolve(outcome)), exact = resolved(outcome);
  expect(reconcileSendingReadback(attempt, batch(exact))).toEqual({ kind: 'resolve', data: exact });
  for (const patch of [{ attempt: 3 }, { retryable: !exact.retryable }, { error_code: 'other' }, { snapshot: { ...exact.snapshot, identity: { account_id: 'other' } } },
    { resolution: { outcome, source_note: 'Different verification', at: stamp, attempt: 2 } }, { snapshot: { ...exact.snapshot, sender: { ...exact.snapshot.sender, address: 'other@example.invalid' } } }]) {
    expect(reconcileSendingReadback(attempt, batch({ ...exact, ...patch }))).toBeNull();
  }
});
it('treats a success response with changed frozen content as uncertain rather than a receipt', async () => {
  const api = mock(); api.send.mockResolvedValueOnce({ ok: true, data: batch(delivery({ snapshot: { ...delivery().snapshot, html: '<p>Wrong body</p>' } })) });
  const hook = renderHook(() => useSendingOperation(api)); await act(async () => { expect(await hook.result.current.execute(send())).toBeNull(); }); expect(hook.result.current.locked).toBe(true);
});
it('keeps deterministic initial rejection editable but never unlocks a rejected durable replay', async () => {
  const api = mock(); const rejected = { ok: false as const, error: { code: 'qualification_changed', message: 'Recheck', retryable: false } };
  api.send.mockResolvedValueOnce(rejected).mockResolvedValueOnce(unknown).mockResolvedValueOnce(rejected); const hook = renderHook(() => useSendingOperation(api));
  await act(async () => { await hook.result.current.execute(send()); }); expect(hook.result.current.state.phase).toBe('idle');
  await act(async () => { await hook.result.current.execute(send()); await hook.result.current.retry(); }); expect(hook.result.current.locked).toBe(true);
});
it.each(['success', 'throw', 'rejection'] as const)('fences late %s after credential replacement including matching readback', async outcome => {
  const api = mock(); let finish!: (value: Result<Delivery>) => void, fail!: (reason: unknown) => void;
  api.resolve.mockImplementationOnce(() => new Promise((done, reject) => { finish = done; fail = reject; })); const hook = renderHook(() => useSendingOperation(api)); let pending!: Promise<unknown>;
  act(() => { pending = hook.result.current.execute(resolve()); hook.result.current.credentialsChanged(); });
  await act(async () => { if (outcome === 'throw') fail(new Error('PRIVATE transport')); else finish(outcome === 'success' ? { ok: true, data: resolved() } : unknown); expect(await pending).toBeNull(); });
  expect(hook.result.current.state).toMatchObject({ phase: 'uncertain', error: { code: 'connection_changed' } });
  act(() => { expect(hook.result.current.confirmReadback(batch(resolved()))).toBeNull(); expect(hook.result.current.reviewReadback(batch(delivery({ attempt: 3 })))).toBe(false); });
  expect(JSON.stringify(hook.result.current.state)).not.toContain('PRIVATE');
});
