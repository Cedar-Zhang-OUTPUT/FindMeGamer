// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { DraftsWorkspace, CompositionHistory } from '../src/renderer/components/match/DraftsWorkspace';
import { useActivityDrafts } from '../src/renderer/components/match/useActivityDrafts';
import { settingsBridgeMock, ok } from './settings-fixtures';
import { gameFixture } from './game-fixtures';
import { compositionFixture, draftFixture, draftIds, draftValues, templateVersion, builtinTemplate } from './drafts-fixtures';
import { preparationFixture, recipientBatchFixture } from './outreach-fixtures';
import { freezeDraftAttempt } from '../src/renderer/components/match/draftMutation';
import type { CompositionPage } from '../src/shared/drafts';
import type { DesktopBridge, Result } from '../src/shared/bridge';
afterEach(cleanup);
function setup() {
  const api: DesktopBridge = { ...settingsBridgeMock(),
    connection: { status: vi.fn(), save: vi.fn(), test: vi.fn(), clear: vi.fn() },
    library: { list: vi.fn(), detail: vi.fn() },
    games: { list: vi.fn(), detail: vi.fn(async () => ok(gameFixture('Fixture game', draftIds.game))), create: vi.fn(), update: vi.fn() }, openExternal: vi.fn() };
  const hook = renderHook(() => useActivityDrafts({ api, activityId: draftIds.activity, gameId: draftIds.game, active: true }));
  const first = draftFixture({ status: 'succeeded', values: draftValues, rendered: { subject: 'Saved subject', html: '<p>Saved first email</p>', text: 'Saved first email', fixed_hash: builtinTemplate.fixed_hash } });
  const second = draftFixture({ id: 'second-draft', selection_id: 'second-selection', recipient_snapshot_id: 'second-recipient', input_order: 1, status: 'needs_repair', input: { ...first.input, channel_name: 'Second person' }, missing_fields: ['observation_evidence_missing'] });
  const batch = recipientBatchFixture({ id: draftIds.batch, recipient_count: 2, recipients: [first, second].map(row => ({ id: row.recipient_snapshot_id, selection_id: row.selection_id, snapshot: preparationFixture({ id: row.selection_id, public_name: row.input.channel_name as string }), preparation: preparationFixture({ id: row.selection_id }), source_changed: false, current_missing_fields: [] })) });
  const c = { ...hook.result.current, mode: { kind: 'composition' as const, id: draftIds.composition }, composition: compositionFixture({ recipient_count: 2, drafts: [first, second] }), batch, selectedId: first.id, current: true,
    game: { id: draftIds.game, name: 'Fixture game', steamAppId: '4952700' }, catalog: { items: [templateVersion], builtin: builtinTemplate }, selectedTemplate: templateVersion.id,
    create: vi.fn(async () => true), saveDraft: vi.fn(async () => false), setSelectedId: vi.fn(), setDirty: vi.fn(), regenerate: vi.fn(async () => true), retry: vi.fn(async () => true), check: vi.fn(async () => {}), reviewCurrent: vi.fn() };
  return { api, c, p: { api, controller: c, active: true, onRequest: vi.fn((action: () => void) => action()), onBack: vi.fn(), onRepairPerson: vi.fn() } };
}
it('creates drafts only through the explicit selected-template button, with no registration on mount', async () => {
  const { api, c, p } = setup(); render(<DraftsWorkspace {...p} controller={{ ...c, mode: { kind: 'template' }, composition: null }} />);
  expect(c.create).not.toHaveBeenCalled(); expect(api.drafts.registerCanonical).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Create 2 drafts' })); expect(c.create).toHaveBeenCalledTimes(1);
});
it('retains every member in server order including repair states, and guards person selection', async () => {
  const { c, p } = setup(); render(<DraftsWorkspace {...p} />);
  const roster = screen.getByRole('navigation', { name: 'Draft people' }); const choices = within(roster).getAllByRole('button');
  expect(choices).toHaveLength(2); expect(choices[0]).toHaveTextContent('Fixture Channel'); expect(choices[1]).toHaveTextContent('Second person');
  expect(choices[1]).toHaveTextContent('Needs repair');
  await userEvent.click(choices[1]); expect(p.onRequest).toHaveBeenCalledTimes(1); expect(c.setSelectedId).toHaveBeenCalledWith('second-draft');
  expect(screen.queryByRole('button', { name: /^send$/i })).not.toBeInTheDocument();
});
it('keeps the editor mounted under a people detour and opens repair without discarding', async () => {
  const { c, p } = setup(); const view = render(<DraftsWorkspace {...p} />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Observation' }), { target: { value: 'Preserved detail.' } });
  await userEvent.click(screen.getByRole('button', { name: 'Edit observation source' }));
  expect(p.onRepairPerson).toHaveBeenCalledWith(draftIds.selection, 'works'); expect(p.onRequest).not.toHaveBeenCalled();
  view.rerender(<DraftsWorkspace {...p} controller={{ ...c, mode: { kind: 'people' } }} />);
  expect(screen.queryByRole('textbox', { name: 'Observation' })).not.toBeInTheDocument();
  view.rerender(<DraftsWorkspace {...p} />); expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('Preserved detail.');
});
it('blocks template actions while credential repair invalidates the catalog and restores its fixed preview',async()=>{
 const {c,p}=setup(),state={...c,mode:{kind:'template' as const},composition:null};const view=render(<DraftsWorkspace {...p} controller={state}/>);
 expect(screen.queryByRole('button',{name:'New version'})).not.toBeInTheDocument();
 view.rerender(<DraftsWorkspace {...p} controller={{...state,game:null,catalog:null,selectedTemplate:null}}/>);
 expect(screen.getByRole('button',{name:'Use this template'})).toBeDisabled();
 view.rerender(<DraftsWorkspace {...p} controller={state}/>);expect(screen.getByTitle('Template preview')).toBeVisible();expect(screen.getByRole('button',{name:'Create 2 drafts'})).toBeEnabled();
});
it('shows only the selected recipient original snapshot and guards the return to people', async () => {
  const { c, p } = setup(); render(<DraftsWorkspace {...p} controller={{ ...c, selectedId: 'second-draft' }} />);
  await userEvent.click(screen.getByText('Original recipient snapshot'));
  expect(screen.getByRole('region', { name: 'Original preparation snapshot' })).toHaveTextContent('Second person');
  await userEvent.click(screen.getByRole('button', { name: 'Back to people' })); expect(p.onRequest).toHaveBeenCalledTimes(1); expect(p.onBack).toHaveBeenCalledTimes(1);
});
it('offers readback for uncertain revision and explicit review without offering blind revision retry', async () => {
  const { c, p } = setup(); const attempt = freezeDraftAttempt({ kind: 'refresh', id: draftIds.draft, data: { expected_revision: 0, context_token: 'a'.repeat(64) }, observedDraft: c.composition.drafts[0] });
  render(<DraftsWorkspace {...p} controller={{ ...c, locked: true, readback: c.composition, operation: { ...c.operation, state: { phase: 'uncertain', attempt, error: { code: 'draft_queue_unavailable', message: 'Queue unavailable', retryable: false } }, locked: true, retryAllowed: false } }} />);
  expect(screen.queryByRole('button', { name: 'Retry same request' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Check current version' })); expect(c.check).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole('button', { name: 'Review current version' })); expect(c.reviewCurrent).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
});
it('allows only original-request replay for uncertain durable creation', () => {
  const { c, p } = setup(); const attempt = freezeDraftAttempt({ kind: 'createComposition', activityId: draftIds.activity, data: { recipient_batch_id: draftIds.batch, template_version_id: draftIds.template } });
  render(<DraftsWorkspace {...p} controller={{ ...c, locked: true, operation: { ...c.operation, state: { phase: 'uncertain', attempt, error: null }, locked: true, retryAllowed: true } }} />);
  expect(screen.getByRole('button', { name: 'Retry same request' })).toBeEnabled(); expect(screen.queryByRole('button', { name: 'Check current version' })).not.toBeInTheDocument();
});
it('offers an explicit GET retry after a current composition read fails', async () => {
  const { c, p } = setup(); const refresh = vi.fn(async () => {});
  render(<DraftsWorkspace {...p} controller={{ ...c, refresh, current: false, error: { code: 'network_error', message: 'Could not load drafts', retryable: true } }} />);
  await userEvent.click(screen.getByRole('button', { name: 'Try again' })); expect(refresh).toHaveBeenCalledTimes(1);
  expect(c.saveDraft).not.toHaveBeenCalled();
});
it('rejects foreign history results and hides old-page actions after a read failure', async () => {
  const { api } = setup(); vi.mocked(api.drafts.compositions).mockResolvedValueOnce(ok({ items: [compositionFixture({ activity_id: 'foreign' })], offset: 0, limit: 50, total: 1 }));
  render(<CompositionHistory api={api.drafts} activityId={draftIds.activity} active epoch={0} disabled={false} onOpen={vi.fn()} />);
  await userEvent.click(screen.getByRole('button', { name: 'Draft history' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load draft history'); expect(screen.queryByRole('button', { name: 'Open draft set' })).not.toBeInTheDocument();
});
it('history reads only while expanded and active, and opens explicitly without mutations', async () => {
  const { api } = setup(); const onOpen = vi.fn(); vi.mocked(api.drafts.compositions).mockResolvedValue(ok({ items: [compositionFixture()], offset: 0, limit: 50, total: 1 }));
  const p = { api: api.drafts, activityId: draftIds.activity, active: false, epoch: 0, disabled: false, onOpen }; const view = render(<CompositionHistory {...p} />);
  expect(api.drafts.compositions).not.toHaveBeenCalled(); await userEvent.click(screen.getByRole('button', { name: 'Draft history' })); expect(api.drafts.compositions).not.toHaveBeenCalled();
  view.rerender(<CompositionHistory {...p} active />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Open draft set' })).toBeEnabled());
  expect(api.drafts.compositions).toHaveBeenCalledWith({ activityId: draftIds.activity, offset: 0, limit: 50 });
  expect(onOpen).not.toHaveBeenCalled(); await userEvent.click(screen.getByRole('button', { name: 'Open draft set' })); expect(onOpen).toHaveBeenCalledWith(draftIds.composition);
  expect(screen.getByRole('button',{name:'Draft history'})).toHaveAttribute('aria-expanded','false');
  expect(api.drafts.createComposition).not.toHaveBeenCalled(); expect(api.drafts.refresh).not.toHaveBeenCalled();
});
it('history fences late responses from an older credential epoch and paginates fifty at a time', async () => {
  const { api } = setup(); let resolve!: (value: Result<CompositionPage>) => void;
  vi.mocked(api.drafts.compositions).mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValue(ok({ items: [], offset: 0, limit: 50, total: 51 }));
  const p = { api: api.drafts, activityId: draftIds.activity, active: true, epoch: 0, disabled: false, onOpen: vi.fn() }; const view = render(<CompositionHistory {...p} />);
  await userEvent.click(screen.getByRole('button', { name: 'Draft history' })); view.rerender(<CompositionHistory {...p} epoch={1} />);
  await act(async () => { resolve(ok({ items: [compositionFixture()], offset: 0, limit: 50, total: 1 })); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Next draft sets' })).toBeEnabled());
  expect(screen.queryByRole('button', { name: 'Open draft set' })).not.toBeInTheDocument();
  vi.mocked(api.drafts.compositions).mockResolvedValueOnce(ok({ items: [compositionFixture()], offset: 50, limit: 50, total: 51 }));
  await userEvent.click(screen.getByRole('button', { name: 'Next draft sets' }));
  await waitFor(() => expect(api.drafts.compositions).toHaveBeenLastCalledWith({ activityId: draftIds.activity, offset: 50, limit: 50 }));
});
