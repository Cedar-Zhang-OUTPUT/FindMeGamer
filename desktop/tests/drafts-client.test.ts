import { describe, expect, it, vi } from 'vitest';
import { DraftsClient } from '../src/main/drafts-client';
import { decodeCatalog, decodeComposition, decodeDraft, fixed, slots, draftSlots } from '../src/main/drafts-validation';
import { builtinTemplate, compositionFixture, draftFixture, draftIds, draftValues, templateVersion } from './drafts-fixtures';

const id = '11111111-1111-4111-8111-111111111111';
describe('drafts client boundary', () => {
  it.each(['manual_note', 'metadata', 'unavailable'])('decodes bounded reusable prefill and %s evidence while preserving historical sources', evidenceKind => {
    const draft = draftFixture();
    draft.input.prefill_values = { ...draftValues, observation: '' };
    const work = { ...(draft.input.work as object), evidence_kind: evidenceKind };
    draft.input.work = work;
    draft.input.slot_sources = { ...(draft.input.slot_sources as object), reference: work, observation: work };
    draft.slot_sources = structuredClone(draft.input.slot_sources as typeof draft.slot_sources);
    expect(decodeDraft(draft).input.prefill_values).toEqual({ ...draftValues, observation: '' });
    expect(() => decodeDraft({ ...draft, input: { ...draft.input, prefill_values: { firstName: 'Only one' } } })).toThrow();
    expect(() => decodeDraft({ ...draft, input: { ...draft.input, work: { ...work, evidence_kind: 'watched_full_video' } } })).toThrow();
    expect(() => decodeDraft({ ...draft, input: { ...draft.input, prefill_values: { ...draftValues, observation: '<script>' } } })).toThrow();
  });
  it('accepts safe unfinished draft values but still rejects markup and malformed fields', () => {
    expect(draftSlots({ ...draftValues, firstName: '', observation: 'Unfinished thought' }, 'input')).toEqual({ ...draftValues, firstName: '', observation: 'Unfinished thought' });
    expect(() => slots({ ...draftValues, firstName: '', observation: 'Unfinished thought' }, 'response')).toThrow();
    expect(() => slots({ ...draftValues, reference: '<script>' }, 'input')).toThrow();
    expect(() => slots({ ...draftValues, channelName: null }, 'input')).toThrow();
  });
  it('decodes rendered per-draft overrides independently of shared source values', () => {
    const values = { firstName: 'Hello creator', channelName: 'Your channel', reference: '', observation: 'My unfinished observation' };
    const fragments = builtinTemplate.fixed_fragments;
    const html = fragments.reduce((body, fragment, index) => body + fragment + (index < 4 ? `<span background-color="rgba(255,246,122,0.8)">${Object.values(values)[index]}</span>` : ''), '');
    const draft = draftFixture({ status: 'needs_repair', values, rendered: { subject: builtinTemplate.subject, html, text: 'Preview', fixed_hash: builtinTemplate.fixed_hash } });
    expect(decodeDraft(draft).values).toEqual(values);
    expect(decodeDraft(draft).input.public_name).toBe('Ari');
    expect(decodeDraft(draft).send_ready).toBe(false);
    expect(() => decodeDraft({ ...draft, status: 'succeeded' })).toThrow();
    expect(() => decodeDraft({ ...draft, rendered: { ...draft.rendered!, html: html.replace('Hello creator', 'Wrong value') } })).toThrow();
  });
  it('accepts fractional recorded work timestamps and rejects nonfinite or negative numbers', () => {
    const d = draftFixture(); const source = { ...(d.input.work as object), timestamp_seconds: 42.5 }; d.input.work = source; d.input.slot_sources = { ...(d.input.slot_sources as object), reference: source, observation: source }; d.slot_sources = structuredClone(d.input.slot_sources as typeof d.slot_sources);
    expect(decodeDraft(d).input.work).toMatchObject({ timestamp_seconds: 42.5 });
    for (const timestamp_seconds of [-1, Infinity, NaN]) expect(() => decodeDraft({ ...d, input: { ...d.input, work: { ...source, timestamp_seconds } } })).toThrow();
  });
  it('rejects invalid pagination before invoking the request', async () => {
    const request = vi.fn();
    await expect(new DraftsClient(request).compositions({ activityId: id, limit: 101 })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it('uses the literal edit PATCH with no key and treats malformed receipt as unknown', async () => {
    const request = vi.fn().mockResolvedValue({}); const data = { expected_revision: 0, context_token: 'a'.repeat(64), values: { firstName: 'A', channelName: 'B', reference: 'C', observation: 'D.' } };
    await expect(new DraftsClient(request).edit({ id, data })).rejects.toMatchObject({ code: 'draft_write_unknown' });
    expect(request).toHaveBeenCalledWith({ method: 'PATCH', path: `/api/v2/outreach/drafts/${id}`, body: data });
  });
  it('accepts the exact immutable canonical source and rejects altered provenance/content', () => {
    expect(decodeCatalog({ items: [templateVersion], builtin: builtinTemplate }, draftIds.game).items).toHaveLength(1);
    for (const change of [{ fixed_hash: 'a'.repeat(64) }, { source_metadata: { ...builtinTemplate.source_metadata, revision: 68 } }, { fixed_fragments: ['a','b','c','d','e'] }]) {
      expect(() => decodeCatalog({ items: [], builtin: { ...builtinTemplate, ...change } }, draftIds.game)).toThrow();
    }
  });
  it('checks all N members, order, scope, false send_ready, and bounded source objects', () => {
    expect(decodeComposition(compositionFixture())).toEqual(compositionFixture());
    for (const change of [{ recipient_count: 2 }, { send_ready: true }, { drafts: [draftFixture({ input_order: 1 })] }, { drafts: [draftFixture(), draftFixture()], recipient_count: 2 }]) expect(() => decodeComposition({ ...compositionFixture(), ...change })).toThrow();
    expect(() => decodeDraft(draftFixture({ input: { ...draftFixture().input, sender: { username: 'x', secret: 'never' } } }))).toThrow();
    expect(() => decodeDraft(draftFixture({ slot_sources: {} }))).toThrow();
  });
  it('rejects unsafe fixed HTML, placeholders, nonplain values, and slots inside attributes', () => {
    for (const fragments of [['<script>', '', '', '', '</script>'], ['<a href="https://example.test/', '">', '', '', '</a>'], ['<p onclick="x">', '', '', '', '</p>'], ['<p>', '', '', '', ''], ['<p>{{', '', '', '', '}}</p>']]) expect(() => fixed('Subject', fragments, 'input')).toThrow();
    for (const observation of ['<b>unsafe.</b>', 'line\nbreak.', '[unfilled].']) expect(() => slots({ ...draftValues, observation }, 'input')).toThrow();
  });
  it('uses exact catalog/template/composition reads and validates creation scope', async () => {
    const request = vi.fn().mockResolvedValueOnce({ items: [templateVersion], builtin: builtinTemplate }).mockResolvedValueOnce(templateVersion).mockResolvedValueOnce(compositionFixture()).mockResolvedValueOnce({ items: [compositionFixture()], total: 1, offset: 0, limit: 100 }).mockResolvedValueOnce(compositionFixture({ recipient_batch_id: draftIds.request }));
    const client = new DraftsClient(request);
    await client.templates({ gameId: draftIds.game }); await client.template(draftIds.template); await client.composition(draftIds.composition); await client.compositions({ activityId: draftIds.activity, limit: 100 });
    const data = { request_id: draftIds.request, recipient_batch_id: draftIds.batch, template_version_id: draftIds.template };
    await expect(client.createComposition({ activityId: draftIds.activity, data, idempotencyKey: 'fixture-key' })).rejects.toMatchObject({ code: 'draft_write_unknown' });
    expect(request.mock.calls.map(call => call[0])).toEqual([
      { method: 'GET', path: '/api/v2/outreach/template-versions', query: { game_id: draftIds.game } },
      { method: 'GET', path: `/api/v2/outreach/template-versions/${draftIds.template}` },
      { method: 'GET', path: `/api/v2/outreach/compositions/${draftIds.composition}` },
      { method: 'GET', path: `/api/v2/activities/${draftIds.activity}/compositions`, query: { offset: '0', limit: '100' } },
      { method: 'POST', path: `/api/v2/activities/${draftIds.activity}/compositions`, body: data, idempotencyKey: 'fixture-key' },
    ]);
  });
  it('emits all remaining write routes and only gives creation requests keys', async () => {
    const fragments = ['<p>Hi ', ', ', ' / ', ' — ', '</p>'];
    const custom = { ...templateVersion, name: 'Custom', subject: 'Subject', fixed_fragments: fragments, fixed_hash: fixed('Subject', fragments, 'input'), source_metadata: { kind: 'user_saved' as const, document_id: null, revision: null, steam_app_id: null, raw_hash: null } };
    const revision = { expected_revision: 0, context_token: 'a'.repeat(64) };
    const facts = { members: [{ draft_id: draftIds.draft, ...revision }], following: false, enjoyed: false, liked: false };
    const request = vi.fn().mockResolvedValueOnce(templateVersion).mockResolvedValueOnce(custom).mockResolvedValueOnce(draftFixture({ revision: 1 })).mockResolvedValueOnce(draftFixture({ revision: 1 })).mockResolvedValueOnce({});
    const c = new DraftsClient(request); await c.registerCanonical({ gameId: draftIds.game, idempotencyKey: 'fixture-key' });
    const data = { game_id: draftIds.game, request_id: draftIds.request, name: 'Custom', subject: 'Subject', fixed_fragments: fragments };
    await c.createTemplate({ data, idempotencyKey: 'fixture-key' }); await c.refresh({ id: draftIds.draft, data: revision }); await c.retry({ id: draftIds.draft, data: revision });
    await expect(c.senderFacts({ compositionId: draftIds.composition, data: facts })).rejects.toMatchObject({ code: 'draft_write_unknown' });
    expect(request.mock.calls.map(call => call[0])).toEqual([
      { method: 'POST', path: '/api/v2/outreach/template-versions/canonical', body: { game_id: draftIds.game }, idempotencyKey: 'fixture-key' },
      { method: 'POST', path: '/api/v2/outreach/template-versions', body: data, idempotencyKey: 'fixture-key' },
      { method: 'POST', path: `/api/v2/outreach/drafts/${draftIds.draft}/refresh`, body: revision },
      { method: 'POST', path: `/api/v2/outreach/drafts/${draftIds.draft}/retry`, body: revision },
      { method: 'POST', path: `/api/v2/outreach/compositions/${draftIds.composition}/sender-facts`, body: facts },
    ]);
  });
});
