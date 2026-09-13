// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Result } from '../src/shared/bridge';
import type { CompositionView, DraftsAPI, DraftView, TemplateVersion } from '../src/shared/drafts';
import { canRetryDraft, freezeDraftAttempt, reconcileDraftReadback, reviewDraftReadback, type DraftCommand } from '../src/renderer/components/match/draftMutation';
import { useDraftOperation } from '../src/renderer/components/match/useDraftOperation';

const token = 'a'.repeat(64), hash = 'b'.repeat(64);
const values = { firstName: 'Alex', channelName: 'Channel', reference: 'Recorded work', observation: 'A recorded detail.' };
function draft(patch: Partial<DraftView> = {}): DraftView {
  return { id: 'draft', composition_id: 'composition', recipient_snapshot_id: 'recipient', selection_id: 'selection', input_order: 0,
    revision: 2, context_token: token, source_changed: false, status: 'succeeded', error_code: null,
    input: { public_name: 'Alex', channel_name: 'Channel', reference: 'Recorded work', template_version_id: 'template', fixed_hash: hash,
      sender: { username: 'synthetic@example.invalid' }, work: { evidence_excerpt: 'Recorded detail' } },
    values: { ...values }, missing_fields: [], slot_sources: { observation: { evidence_excerpt: 'Recorded detail' } },
    rendered: { subject: 'Subject', html: '<p>Mail</p>', text: 'Mail', fixed_hash: hash }, sender_facts: {}, sender_facts_valid: false, send_ready: false, ...patch };
}
function composition(drafts = [draft()]): CompositionView {
  return { id: 'composition', activity_id: 'activity', recipient_batch_id: 'batch', template_version_id: 'template', created_at: '2026-09-08T00:00:00Z', recipient_count: drafts.length, drafts, send_ready: false };
}
function template(): TemplateVersion {
  return { id: 'template', game_id: 'game', name: 'Name', subject: 'Subject', fixed_fragments: ['<p>', ' ', ' ', ' ', '</p>'], fixed_hash: hash,
    source_metadata: { kind: 'canonical', revision: 69, steam_app_id: '4952700', document_id: 'doc', raw_hash: hash }, created_at: '2026-09-08T00:00:00Z' };
}
const unknown = { ok: false as const, error: { code: 'draft_queue_unavailable', message: 'Queue unavailable', retryable: true } };
const rejected = { ok: false as const, error: { code: 'draft_context_changed', message: 'Read current', retryable: false } };
function apiMock() {
  return { templates: vi.fn<DraftsAPI['templates']>(), template: vi.fn<DraftsAPI['template']>(),
    registerCanonical: vi.fn<DraftsAPI['registerCanonical']>().mockResolvedValue({ ok: true, data: template() }),
    createTemplate: vi.fn<DraftsAPI['createTemplate']>().mockResolvedValue({ ok: true, data: template() }),
    compositions: vi.fn<DraftsAPI['compositions']>(), composition: vi.fn<DraftsAPI['composition']>(),
    createComposition: vi.fn<DraftsAPI['createComposition']>().mockResolvedValue({ ok: true, data: composition() }),
    edit: vi.fn<DraftsAPI['edit']>().mockResolvedValue({ ok: true, data: draft() }),
    refresh: vi.fn<DraftsAPI['refresh']>().mockResolvedValue({ ok: true, data: draft() }),
    retry: vi.fn<DraftsAPI['retry']>().mockResolvedValue({ ok: true, data: draft() }),
    senderFacts: vi.fn<DraftsAPI['senderFacts']>().mockResolvedValue({ ok: true, data: composition() }) };
}
const edit = (): DraftCommand => ({ kind: 'edit', id: 'draft', data: { expected_revision: 2, context_token: token, values: { ...values } }, observedDraft: draft() });
const create: DraftCommand = { kind: 'createComposition', activityId: 'activity', data: { recipient_batch_id: 'batch', template_version_id: 'template' } };
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe('frozen draft operations', () => {
  it.each(['draft_write_unknown', 'network_error', 'invalid_response'])('locks adapter %s failures against a fresh revision action', async code => {
    const api = apiMock(); api.edit.mockResolvedValueOnce({ ok: false, error: { code, message: 'Uncertain', retryable: false } });
    const hook = renderHook(() => useDraftOperation(api));
    await act(async () => { await hook.result.current.execute(edit()); await hook.result.current.execute(edit()); });
    expect(hook.result.current.state.phase).toBe('uncertain'); expect(api.edit).toHaveBeenCalledTimes(1);
  });

  it('routes all seven mutations with only exact API inputs and tagged successful results', async () => {
    const api = apiMock(), hook = renderHook(() => useDraftOperation(api));
    const commands: DraftCommand[] = [
      { kind: 'registerCanonical', gameId: 'game', canonicalFixedHash: hash },
      { kind: 'createTemplate', data: { game_id: 'game', name: 'Name', subject: 'Subject', fixed_fragments: template().fixed_fragments } },
      create, edit(), { kind: 'refresh', id: 'draft', data: { expected_revision: 2, context_token: token }, observedDraft: draft() },
      { kind: 'retry', id: 'draft', data: { expected_revision: 2, context_token: token }, observedDraft: draft() },
      { kind: 'senderFacts', compositionId: 'composition', observedComposition: composition(), data: { members: [{ draft_id: 'draft', expected_revision: 2, context_token: token }], following: true, enjoyed: false, liked: true } },
    ];
    for (const command of commands) {
      await act(async () => { expect((await hook.result.current.execute(command))?.kind).toBe(command.kind); });
      expect(api[command.kind]).toHaveBeenCalledTimes(1);
      const input = api[command.kind].mock.calls[0][0];
      expect(input).not.toHaveProperty('kind'); expect(input).not.toHaveProperty('observedDraft'); expect(input).not.toHaveProperty('observedComposition');
      if (command.kind === 'createTemplate' || command.kind === 'createComposition') {
        expect(input).toHaveProperty('data.request_id', expect.stringMatching(/^[0-9a-f-]{36}$/));
        expect(input).toHaveProperty('idempotencyKey', expect.stringMatching(/^[0-9a-f-]{36}$/));
      } else if (command.kind !== 'registerCanonical') expect(input).not.toHaveProperty('idempotencyKey');
    }
  });

  it('expires canonical retry in the rendered hook exactly at the 24-hour boundary', async () => {
    vi.useFakeTimers(); vi.setSystemTime(0);
    const api = apiMock(); api.registerCanonical.mockResolvedValueOnce(unknown);
    const hook = renderHook(() => useDraftOperation(api));
    await act(async () => { await hook.result.current.execute({ kind: 'registerCanonical', gameId: 'game' }); });
    expect(hook.result.current.retryAllowed).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(86_400_000); });
    expect(hook.result.current.retryAllowed).toBe(false);
    await act(async () => { await hook.result.current.retry(); });
    expect(api.registerCanonical).toHaveBeenCalledTimes(1);
  });

  it('requires every submitted facts member to advance before explicit review unlocks', () => {
    const before = composition([draft(), draft({ id: 'second', input_order: 1 })]);
    const attempt = freezeDraftAttempt({ kind: 'senderFacts', compositionId: 'composition', observedComposition: before,
      data: { members: before.drafts.map(row => ({ draft_id: row.id, expected_revision: 2, context_token: token })), following: true, enjoyed: true, liked: true } });
    const advanced = composition(before.drafts.map(row => ({ ...row, revision: 3 })));
    expect(reviewDraftReadback(attempt, advanced)).toBe(true);
    expect(reviewDraftReadback(attempt, composition([advanced.drafts[0], before.drafts[1]]))).toBe(false);
    expect(reviewDraftReadback(attempt, composition([advanced.drafts[0]]))).toBe(false);
    expect(reviewDraftReadback(attempt, { ...advanced, activity_id: 'other' })).toBe(false);
    expect(reviewDraftReadback(attempt, composition([...advanced.drafts].reverse()))).toBe(false);
  });

  it('generates keys for only three creations and durable IDs for only the two persistent creations', () => {
    const random = vi.spyOn(crypto, 'randomUUID');
    const revision = freezeDraftAttempt(edit());
    expect(random).not.toHaveBeenCalled();
    expect(revision.input).toEqual({ id: 'draft', data: { expected_revision: 2, context_token: token, values } });
    const canonical = freezeDraftAttempt({ kind: 'registerCanonical', gameId: 'game', canonicalFixedHash: hash });
    expect(random).toHaveBeenCalledTimes(1); expect(canonical.input).not.toHaveProperty('data');
    const persistent = freezeDraftAttempt(create);
    expect(random).toHaveBeenCalledTimes(3); expect(persistent.input).toHaveProperty('data.request_id');
    expect(Object.isFrozen(persistent.input)).toBe(true);
    expect(Object.isFrozen(revision.command)).toBe(true);
  });

  it('freezes caller edits and suppresses duplicate submits while returning tagged receipts', async () => {
    const api = apiMock(); let finish!: (value: Result<DraftView>) => void;
    api.edit.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const hook = renderHook(() => useDraftOperation(api)); const command = edit(); let pending!: Promise<unknown>;
    act(() => { pending = hook.result.current.execute(command); void hook.result.current.execute(command); });
    if (command.kind === 'edit') command.data.values.observation = 'Changed after click.';
    expect(api.edit).toHaveBeenCalledTimes(1); expect(api.edit.mock.calls[0][0].data.values.observation).toBe('A recorded detail.');
    expect(Object.isFrozen(api.edit.mock.calls[0][0].data.values)).toBe(true);
    await act(async () => { finish({ ok: true, data: draft() }); expect(await pending).toEqual({ kind: 'edit', data: draft() }); });
    expect(hook.result.current.state.phase).toBe('idle');
  });

  it('replays persistent creation with the same key and request ID after 24 hours, preserving uncertainty after rejection', async () => {
    vi.useFakeTimers(); vi.setSystemTime(1000);
    const api = apiMock(); api.createComposition.mockResolvedValueOnce(unknown).mockResolvedValueOnce(rejected);
    const hook = renderHook(() => useDraftOperation(api));
    await act(async () => { await hook.result.current.execute(create); });
    const original = api.createComposition.mock.calls[0][0];
    await act(async () => { await vi.advanceTimersByTimeAsync(3 * 86_400_000); await hook.result.current.retry(); });
    expect(api.createComposition.mock.calls[1][0]).toBe(original);
    expect(hook.result.current.state.phase).toBe('uncertain'); expect(hook.result.current.retryAllowed).toBe(true);
    const canonical = freezeDraftAttempt({ kind: 'registerCanonical', gameId: 'game' }, 0);
    expect(canRetryDraft(canonical, 86_399_999)).toBe(true); expect(canRetryDraft(canonical, 86_400_000)).toBe(false);
  });

  it('keeps a thrown template creation private and replays its frozen original body after caller changes', async () => {
    const api = apiMock(); api.createTemplate.mockRejectedValueOnce(new Error('PRIVATE transport URL and credential'));
    const hook = renderHook(() => useDraftOperation(api));
    const command: DraftCommand = { kind: 'createTemplate', data: { game_id: 'game', name: 'Original', subject: 'Subject', fixed_fragments: [...template().fixed_fragments] } };
    await act(async () => { await hook.result.current.execute(command); });
    command.data.name = 'Changed'; command.data.fixed_fragments[0] = '<p>Changed';
    expect(hook.result.current.state.phase).toBe('uncertain'); expect(JSON.stringify(hook.result.current.state)).not.toContain('PRIVATE');
    const input = api.createTemplate.mock.calls[0][0];
    expect(input.data.name).toBe('Original'); expect(Object.isFrozen(input.data.fixed_fragments)).toBe(true);
    act(() => { expect(hook.result.current.reviewReadback(composition())).toBe(false); });
    await act(async () => { expect((await hook.result.current.retry())?.kind).toBe('createTemplate'); });
    expect(api.createTemplate.mock.calls[1][0]).toBe(input); expect(hook.result.current.state.phase).toBe('idle');
  });

  it.each(['edit', 'refresh', 'retry', 'senderFacts'] as const)('never replays %s after a queue failure or rebases the revision', async kind => {
    const api = apiMock(); api[kind].mockResolvedValueOnce(unknown);
    const hook = renderHook(() => useDraftOperation(api));
    const command: DraftCommand = kind === 'senderFacts'
      ? { kind, compositionId: 'composition', observedComposition: composition(), data: { members: [{ draft_id: 'draft', expected_revision: 2, context_token: token }], following: true, enjoyed: true, liked: true } }
      : kind === 'edit' ? edit() : { kind, id: 'draft', data: { expected_revision: 2, context_token: token }, observedDraft: draft() };
    await act(async () => { await hook.result.current.execute(command); await hook.result.current.retry(); await hook.result.current.execute(command); });
    expect(hook.result.current.state.phase).toBe('uncertain'); expect(hook.result.current.retryAllowed).toBe(false);
    expect(api[kind]).toHaveBeenCalledTimes(1); expect(api[kind].mock.calls[0][0]).not.toHaveProperty('idempotencyKey');
  });

  it('does not infer identity of persistent creations from same-content readback', () => {
    expect(reconcileDraftReadback(freezeDraftAttempt(create), { kind: 'composition', data: composition() })).toBeNull();
    const version = freezeDraftAttempt({ kind: 'createTemplate', data: { game_id: 'game', name: 'Name', subject: 'Subject', fixed_fragments: template().fixed_fragments } });
    expect(reconcileDraftReadback(version, { kind: 'templates', items: [template()] })).toBeNull();
    const canonical = freezeDraftAttempt({ kind: 'registerCanonical', gameId: 'game', canonicalFixedHash: hash });
    expect(reconcileDraftReadback(canonical, { kind: 'templates', items: [template()] })?.kind).toBe('registerCanonical');
    expect(reconcileDraftReadback(canonical, { kind: 'templates', items: [{ ...template(), game_id: 'other' }] })).toBeNull();
    expect(reconcileDraftReadback(canonical, { kind: 'templates', items: [template(), template()] })).toBeNull();
    expect(reconcileDraftReadback(freezeDraftAttempt({ kind: 'registerCanonical', gameId: 'game' }), { kind: 'templates', items: [template()] })).toBeNull();
  });

  it('proves edit only from exact revision, values, context, source binding, completion and cleared facts', () => {
    const attempt = freezeDraftAttempt(edit()), saved = draft({ revision: 3 });
    expect(reconcileDraftReadback(attempt, { kind: 'composition', data: composition([saved]) })?.kind).toBe('edit');
    const variants: Partial<DraftView>[] = [{ revision: 4 }, { context_token: 'c'.repeat(64) }, { source_changed: true }, { status: 'running' },
      { values: { ...values, observation: 'Other.' } }, { input: { ...saved.input, work: { evidence_excerpt: 'Other source' } } },
      { slot_sources: {} }, { sender_facts: { following: true } }, { composition_id: 'foreign' }];
    for (const patch of variants) expect(reconcileDraftReadback(attempt, { kind: 'composition', data: composition([{ ...saved, ...patch }]) })).toBeNull();
    expect(reconcileDraftReadback(freezeDraftAttempt({ kind: 'edit', id: 'draft', data: { expected_revision: 2, context_token: token, values } }), { kind: 'composition', data: composition([saved]) })).toBeNull();
  });

  it.each([
    ['firstName', 'A different greeting', [true, true, true]],
    ['firstName', '', [true, true, true]],
    ['channelName', 'Different channel wording', [false, true, true]],
    ['reference', 'Another reference', [true, false, false]],
    ['observation', '', [true, true, false]],
  ] as const)('reconciles a %s override and only its affected confirmations', (key, value, flags) => {
    const facts = { following: true, enjoyed: true, liked: true, at: '2026-09-08T00:00:00Z', fingerprint: hash };
    const before = draft({ sender_facts: facts, sender_facts_valid: true });
    const updated = { ...values, [key]: value };
    const command: DraftCommand = { kind: 'edit', id: before.id, observedDraft: before, data: { expected_revision: 2, context_token: token, values: updated } };
    const saved = draft({ revision: 3, values: updated, status: value ? 'succeeded' : 'needs_repair', sender_facts_valid: !!value && flags.every(Boolean), sender_facts: { ...facts, following: flags[0], enjoyed: flags[1], liked: flags[2], fingerprint: 'c'.repeat(64) } });
    const read = (row: DraftView) => reconcileDraftReadback(freezeDraftAttempt(command), { kind: 'composition', data: composition([row]) });
    expect(read(saved)?.kind).toBe('edit');
    expect(read({ ...saved, sender_facts: {} })).toBeNull();
    expect(read({ ...saved, revision: 4 })).toBeNull();
    expect(read({ ...saved, sender_facts: { ...saved.sender_facts, following: !flags[0] } })).toBeNull();
  });

  it.each([true, false])('restores complete greeting without inventing a sender account: sender=%s', hasSender => {
    const facts = { following: true, enjoyed: true, liked: true, at: '2026-09-08T00:00:00Z', fingerprint: hash };
    const before = draft({ values: { ...values, firstName: '' }, status: 'needs_repair', sender_facts: facts, sender_facts_valid: false });
    before.input.sender = { username: hasSender ? 'synthetic@example.invalid' : null };
    const command: DraftCommand = { kind: 'edit', id: before.id, observedDraft: before, data: { expected_revision: 2, context_token: token, values } };
    const saved = { ...before, values, revision: 3, status: 'succeeded' as const, sender_facts_valid: hasSender, sender_facts: { ...facts, fingerprint: 'c'.repeat(64) } };
    expect(reconcileDraftReadback(freezeDraftAttempt(command), { kind: 'composition', data: composition([saved]) })?.kind).toBe('edit');
  });

  it('retains an existing false confirmation while saving an unfinished observation', () => {
    const facts = { following: false, enjoyed: true, liked: true, at: '2026-09-08T00:00:00Z', fingerprint: hash };
    const before = draft({ sender_facts: facts });
    const updated = { ...values, observation: 'Unfinished observation' };
    const command: DraftCommand = { kind: 'edit', id: before.id, observedDraft: before, data: { expected_revision: 2, context_token: token, values: updated } };
    const saved = { ...before, values: updated, revision: 3, status: 'needs_repair' as const, sender_facts: { ...facts, liked: false, fingerprint: 'c'.repeat(64) } };
    const read = (row: DraftView) => reconcileDraftReadback(freezeDraftAttempt(command), { kind: 'composition', data: composition([row]) });
    expect(read(saved)?.kind).toBe('edit');
    expect(read({ ...saved, sender_facts: { ...saved.sender_facts, following: true } })).toBeNull();
    expect(read({ ...saved, sender_facts: { ...saved.sender_facts, at: '2026-09-09T00:00:00Z' } })).toBeNull();
  });

  it('proves all facts members and flags against their unchanged recorded values and source versions', () => {
    const before = composition([draft(), draft({ id: 'second', input_order: 1, recipient_snapshot_id: 'second-recipient', selection_id: 'second-selection' })]);
    const command: DraftCommand = { kind: 'senderFacts', compositionId: 'composition', observedComposition: before,
      data: { members: before.drafts.map(row => ({ draft_id: row.id, expected_revision: 2, context_token: token })), following: true, enjoyed: true, liked: true } };
    const saved = composition(before.drafts.map(row => ({ ...row, revision: 3, sender_facts_valid: true,
      sender_facts: { following: true, enjoyed: true, liked: true, at: '2026-09-08T00:00:00Z', fingerprint: hash } })));
    const attempt = freezeDraftAttempt(command);
    expect(reconcileDraftReadback(attempt, { kind: 'composition', data: saved })?.kind).toBe('senderFacts');
    for (const patch of [{ revision: 2 }, { revision: 4 }, { sender_facts_valid: false }, { values: { ...values, observation: 'Different.' } },
      { sender_facts: { following: true, enjoyed: false, liked: true } }, { input: { ...draft().input, sender: { username: 'other@example.invalid' } } }]) {
      expect(reconcileDraftReadback(attempt, { kind: 'composition', data: { ...saved, drafts: [saved.drafts[0], { ...saved.drafts[1], ...patch }] } })).toBeNull();
    }
    expect(reconcileDraftReadback(attempt, { kind: 'composition', data: composition([saved.drafts[0]]) })).toBeNull();
  });

  it('reviews an advanced scoped version without claiming refresh success, refusing equal, foreign, partial and cross-credential reads', () => {
    const command: DraftCommand = { kind: 'refresh', id: 'draft', data: { expected_revision: 2, context_token: token }, observedDraft: draft() };
    const attempt = freezeDraftAttempt(command), advanced = composition([draft({ revision: 4, context_token: 'c'.repeat(64), status: 'running' })]);
    expect(reconcileDraftReadback(attempt, { kind: 'composition', data: advanced })).toBeNull();
    expect(reviewDraftReadback(attempt, advanced)).toBe(true);
    expect(reviewDraftReadback(attempt, composition())).toBe(false);
    expect(reviewDraftReadback(attempt, { ...advanced, id: 'foreign' })).toBe(false);
    expect(reviewDraftReadback(attempt, composition([]))).toBe(false);
    expect(reviewDraftReadback({ ...attempt, connectionChanged: true }, advanced)).toBe(false);
    expect(reviewDraftReadback(attempt, composition([draft({ revision: 4, context_token: '' })]))).toBe(false);
  });

  it('only unlocks exact confirmation or explicit advanced-version review after the write settles', async () => {
    const api = apiMock(); api.edit.mockResolvedValueOnce(unknown);
    const hook = renderHook(() => useDraftOperation(api));
    await act(async () => { await hook.result.current.execute(edit()); });
    act(() => { expect(hook.result.current.confirmReadback({ kind: 'composition', data: composition() })).toBeNull(); });
    expect(hook.result.current.locked).toBe(true);
    act(() => { expect(hook.result.current.reviewReadback(composition([draft({ revision: 4 })]))).toBe(true); });
    expect(hook.result.current.state.phase).toBe('idle');
    api.edit.mockResolvedValueOnce(unknown);
    await act(async () => { await hook.result.current.execute(edit()); });
    act(() => { expect(hook.result.current.confirmReadback({ kind: 'composition', data: composition([draft({ revision: 3 })]) })?.kind).toBe('edit'); });
    expect(hook.result.current.state.phase).toBe('idle');
  });

  it.each(['success', 'rejection', 'throw'] as const)('fences late %s from replaced credentials and prevents readback unlock', async outcome => {
    const api = apiMock(); let finish!: (value: Result<DraftView>) => void, fail!: (error: Error) => void;
    api.edit.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }));
    const hook = renderHook(() => useDraftOperation(api)); let pending!: Promise<unknown>;
    act(() => { pending = hook.result.current.execute(edit()); hook.result.current.credentialsChanged();
      expect(hook.result.current.reviewReadback(composition([draft({ revision: 3 })]))).toBe(false); });
    await act(async () => { if (outcome === 'throw') fail(new Error('PRIVATE')); else finish(outcome === 'success' ? { ok: true, data: draft() } : rejected); expect(await pending).toBeNull(); });
    expect(hook.result.current.state).toMatchObject({ phase: 'uncertain', error: { code: 'connection_changed' } });
    expect(JSON.stringify(hook.result.current.state)).not.toContain('PRIVATE');
    act(() => { expect(hook.result.current.confirmReadback({ kind: 'composition', data: composition([draft({ revision: 3 })]) })).toBeNull(); });
  });

  it('keeps definitive first rejection editable and ignores late success after unmount', async () => {
    const api = apiMock(); api.edit.mockResolvedValueOnce(rejected);
    const hook = renderHook(() => useDraftOperation(api));
    await act(async () => { await hook.result.current.execute(edit()); });
    expect(hook.result.current.state).toEqual({ phase: 'idle', error: rejected.error });
    let finish!: (value: Result<DraftView>) => void;
    api.edit.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })); let pending!: Promise<unknown>;
    act(() => { pending = hook.result.current.execute(edit()); }); hook.unmount();
    await act(async () => { finish({ ok: true, data: draft() }); expect(await pending).toBeNull(); });
  });
});
