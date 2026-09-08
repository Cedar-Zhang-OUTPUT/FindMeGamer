// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import type { DesktopBridge, Result } from '../src/shared/bridge';
import type { GameDetail, GameFields, GamePage, NavigationGuard } from '../src/shared/games';
import { GameLibrary } from '../src/renderer/components/GameLibrary';
import { settingsBridgeMock } from './settings-fixtures';

const ok = <T,>(data: T): Result<T> => ({ ok: true, data });
const error = (code = 'network_error', message = 'Connection interrupted'): Result<never> => ({ ok: false, error: { code, message, retryable: code === 'network_error' } });
const fields: GameFields = { name: 'Harbor Lights', website_url: 'https://harbor.example', steam_app_id: null, developer: 'Tide Studio', description: 'Explore an island at dusk.', tags: ['Adventure'], languages: ['English'], release_date: null, cover_url: null };
const game = (overrides: Partial<GameDetail> = {}): GameDetail => ({ ...fields, id: '00000000-0000-4000-8000-000000000001', revision: 7, favorite: false, reference_works: [], source_fields: { ...fields, developer: 'Original Studio' }, manual_overrides: { developer: 'Tide Studio' }, overridden_fields: ['developer'], source_identity: { steam_app_id: '12345', canonical_url: 'https://store.steampowered.com/app/12345/' }, last_analyzed_at: null, next_analysis_at: null, ...overrides });
const page = (items = [game()], offset = 0, total = items.length): GamePage => ({ items, total, offset, limit: 24 });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
function apiMock(): DesktopBridge {
  return { ...settingsBridgeMock(), connection: {} as DesktopBridge['connection'], library: {} as DesktopBridge['library'], openExternal: vi.fn(async () => ok(undefined)), games: {
    list: vi.fn(async () => ok(page())), detail: vi.fn(async () => ok(game())),
    create: vi.fn(async () => ok(game({ revision: 1 }))), update: vi.fn(async () => ok(game({ revision: 8 }))),
  } };
}
function start(api = apiMock()) {
  let guard: NavigationGuard | null = null;
  const onGuard = vi.fn((value: NavigationGuard | null) => { guard = value; });
  const view = render(<GameLibrary api={api} active onNavigationGuardChange={onGuard}/>);
  return { api, user: userEvent.setup(), navigate: async (proceed: () => void) => await act(async () => { if (guard) guard(proceed); else proceed(); }), onGuard, ...view };
}
async function edit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Open Harbor Lights' }));
  await user.click(await screen.findByRole('button', { name: 'Edit game' }));
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('editable Games Library', () => {
  it('uses direct reference entry and contextual controls without duplicate instruction paragraphs', async () => {
    const {user} = start();
    await user.click(await screen.findByRole('button',{name:'New game'}));
    expect(screen.queryByText('No references added.')).not.toBeInTheDocument();
    expect(screen.queryByText('No changes')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'Add reference'}));
    await waitFor(() => expect(screen.getByRole('textbox',{name:'Reference name'})).toHaveFocus());
    await user.type(screen.getByRole('textbox',{name:'Reference name'}),'Nearby inspiration');
    await user.click(screen.getByRole('button',{name:'Edit reference Nearby inspiration'}));
    expect(screen.queryByRole('textbox',{name:'Reference name'})).not.toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'Edit reference Nearby inspiration'}));
    expect(screen.getByRole('textbox',{name:'Reference name'})).toHaveValue('Nearby inspiration');
  });
  it('submits searches, ignores older results and preserves offset when returning from a profile', async () => {
    const old = deferred<Result<GamePage>>(); const api = apiMock();
    vi.mocked(api.games.list).mockImplementation(async input => input.query === 'old' ? old.promise : ok(page([game({ name: input.query || 'Harbor Lights' })], input.offset || 0, 50)));
    const { user } = start(api); await screen.findByRole('button', { name: 'Open Harbor Lights' });
    const search = screen.getByRole('searchbox', { name: 'Search games' });
    await user.type(search, 'old'); expect(api.games.list).toHaveBeenCalledOnce();
    await user.keyboard('{Enter}'); await user.clear(search); await user.type(search, 'new{Enter}');
    await screen.findByRole('button', { name: 'Open new' });
    await act(async () => old.resolve(ok(page([game({ name: 'Old result' })]))));
    expect(screen.queryByRole('button', { name: 'Open Old result' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(vi.mocked(api.games.list).mock.lastCall?.[0]).toMatchObject({ query: 'new', offset: 24 }));
    await user.click(await screen.findByRole('button', { name: 'Open new' }));
    await screen.findByRole('button', { name: 'Edit game' });
    await user.click(screen.getByRole('button', { name: 'Back to games' }));
    expect(screen.getByRole('searchbox')).toHaveValue('new');
    expect(screen.getByText('25–25 of 50')).toBeVisible();
  });

  it('creates with a name and no Steam ID, then fetches authoritative current detail', async () => {
    const api = apiMock(); vi.mocked(api.games.detail).mockResolvedValue(ok(game({ name: 'New current title', revision: 4 })));
    const { user } = start(api); await screen.findByRole('button', { name: 'New game' });
    await user.click(screen.getByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Manual title');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    expect(await screen.findByRole('heading', { name: 'New current title' })).toBeVisible();
    expect(api.games.create).toHaveBeenCalledOnce();
    const request = vi.mocked(api.games.create).mock.calls[0][0];
    expect(request.data.name).toBe('Manual title');
    expect(request.data.steam_app_id).toBeUndefined();
    expect(request.idempotencyKey).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
    expect(api.games.detail).toHaveBeenCalledWith(game().id);
  });

  it('allows a URL-only manual game without requiring optional metadata', async () => {
    const { api, user } = start(); await user.click(await screen.findByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Website URL' }), 'https://new.example/game');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await waitFor(() => expect(api.games.create).toHaveBeenCalledOnce());
    expect(vi.mocked(api.games.create).mock.calls[0][0].data).toEqual({ website_url: 'https://new.example/game' });
  });

  it('only patches changed fields, sends explicit scalar/list clears, and uses the loaded revision', async () => {
    const { api, user } = start(); await edit(user);
    await user.clear(screen.getByRole('textbox', { name: 'Developer' }));
    await user.clear(screen.getByRole('textbox', { name: 'Tags' }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(api.games.update).toHaveBeenCalledOnce());
    expect(vi.mocked(api.games.update).mock.calls[0][0]).toEqual({ id: game().id, data: { expected_revision: 7, developer: null, tags: [] } });
  });

  it('retains reference UUIDs and displays server deduplication instead of the submitted draft', async () => {
    const id = '00000000-0000-4000-8000-000000000099';
    const api = apiMock(); const original = game({ reference_works: [{ id, name: 'Beacon', url: null, similarities: [], reason: null }] });
    vi.mocked(api.games.detail).mockResolvedValue(ok(original));
    vi.mocked(api.games.update).mockResolvedValue(ok({ ...original, revision: 8, reference_works: [{ id, name: 'Beacon definitive', url: null, similarities: ['Mood'], reason: 'Atmosphere' }] }));
    const { user } = start(api); await edit(user);
    await user.click(screen.getByRole('button', { name: 'Edit reference Beacon' }));
    const ref = screen.getByRole('group', { name: 'Reference 1' });
    await user.type(within(ref).getByRole('textbox', { name: 'Reason' }), 'Atmosphere');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('Beacon definitive')).toBeVisible();
    expect(vi.mocked(api.games.update).mock.calls[0][0].data.reference_works?.[0]).toMatchObject({ id, reason: 'Atmosphere' });
    expect(screen.queryByRole('textbox', { name: 'Reason' })).not.toBeInTheDocument();
  });

  it('restores one source field without setting that same field or changing the source binding', async () => {
    const { api, user } = start(); await edit(user);
    await user.click(screen.getByText('Source comparison', { selector: 'summary' }));
    await user.click(screen.getByRole('button', { name: 'Use source Developer' }));
    expect(screen.getByRole('textbox', { name: 'Developer' })).toHaveValue('Original Studio');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(api.games.update).toHaveBeenCalledOnce());
    expect(vi.mocked(api.games.update).mock.calls[0][0].data).toEqual({ expected_revision: 7, reset_fields: ['developer'] });
  });

  it('preserves every draft on validation failure and does not leave on failed Save and leave', async () => {
    const api = apiMock(); vi.mocked(api.games.update).mockResolvedValue(error('request_invalid', 'Website is invalid'));
    const { user, navigate } = start(api); await edit(user);
    await user.type(screen.getByRole('textbox', { name: 'Description' }), ' More detail.');
    const leave = vi.fn(); await navigate(leave);
    const dialog = screen.getByRole('dialog', { name: 'Unsaved game changes' });
    await user.click(within(dialog).getByRole('button', { name: 'Save and leave' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Website is invalid');
    expect(screen.getByRole('textbox', { name: 'Description' })).toHaveValue('Explore an island at dusk. More detail.');
    expect(leave).not.toHaveBeenCalled();
  });

  it('requires explicit conflict choices and does not overwrite untouched newer fields', async () => {
    const api = apiMock(); const latest = game({ revision: 9, developer: 'Another editor', description: 'New server description' });
    vi.mocked(api.games.detail).mockResolvedValueOnce(ok(game())).mockResolvedValueOnce(ok(latest));
    vi.mocked(api.games.update).mockResolvedValueOnce(error('game_revision_conflict', 'Changed by another editor')).mockResolvedValueOnce(ok({ ...latest, revision: 10, developer: 'My studio' }));
    const { user } = start(api); await edit(user);
    const developer = screen.getByRole('textbox', { name: 'Developer' }); await user.clear(developer); await user.type(developer, 'My studio');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('heading', { name: 'Resolve changes' })).toBeVisible();
    expect(screen.getByText('Another editor')).toBeVisible(); expect(screen.getByText('My studio')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Apply choices' })).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'Keep mine: Developer' }));
    await user.click(screen.getByRole('button', { name: 'Apply choices' }));
    expect(screen.getByRole('textbox', { name: 'Description' })).toHaveValue('New server description');
    expect(api.games.update).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(api.games.update).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.games.update).mock.calls[1][0].data).toEqual({ expected_revision: 9, developer: 'My studio' });
  });

  it('freezes an uncertain POST, reuses identical payload/key and only retries GET after creation is known', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValueOnce(error()).mockResolvedValueOnce(ok(game({ revision: 1 })));
    vi.mocked(api.games.detail).mockResolvedValueOnce(error()).mockResolvedValueOnce(ok(game({ name: 'Current after replay', revision: 12 })));
    const { user } = start(api); await user.click(await screen.findByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'A new game');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await screen.findByRole('button', { name: 'Retry creation' });
    expect(screen.getByRole('textbox', { name: 'Name' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Retry creation' }));
    expect(await screen.findByRole('heading', { name: 'Game created' })).toBeVisible();
    expect(screen.getByText(game().id)).toBeVisible();
    expect(vi.mocked(api.games.create).mock.calls[0][0]).toEqual(vi.mocked(api.games.create).mock.calls[1][0]);
    await user.click(screen.getByRole('button', { name: 'Retry latest' }));
    expect(await screen.findByRole('heading', { name: 'Current after replay' })).toBeVisible();
    expect(api.games.create).toHaveBeenCalledTimes(2);
    expect(api.games.detail).toHaveBeenCalledTimes(2);
  });

  it('does not retry an uncertain creation after the 24-hour idempotency window', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValue(error());
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_800_000_000_000);
    const { user, rerender } = start(api); await user.click(await screen.findByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Expired request');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await screen.findByRole('button', { name: 'Retry creation' });
    now.mockReturnValue(1_800_000_000_000 + 24 * 60 * 60 * 1000);
    rerender(<GameLibrary api={api} active/>);
    expect(screen.getByRole('button', { name: 'Retry creation' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check Library' })).toBeEnabled();
    expect(api.games.create).toHaveBeenCalledOnce();
  });

  it('checks retry expiry at dispatch even when the clock changes without rendering', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValue(error());
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_800_000_000_000);
    const {user} = start(api); await user.click(await screen.findByRole('button',{name:'New game'}));
    await user.type(screen.getByRole('textbox',{name:'Name'}),'Clock change');
    await user.click(screen.getByRole('button',{name:'Create game'}));
    const retry = await screen.findByRole('button',{name:'Retry creation'});
    now.mockReturnValue(1_800_000_000_000 + 24 * 60 * 60 * 1000);
    await user.click(retry);
    expect(api.games.create).toHaveBeenCalledOnce();
    expect(retry).toBeDisabled();
  });

  it('bounds recovery queries and pages results without issuing another creation', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValue(error());
    const url = `https://例子.example/游戏/${'long-path-'.repeat(35)}`;
    const recovered = game({name:null,website_url:url});
    const {user} = start(api); await user.click(await screen.findByRole('button',{name:'New game'}));
    await user.type(screen.getByRole('textbox',{name:'Website URL'}),url);
    await user.click(screen.getByRole('button',{name:'Create game'}));
    await screen.findByRole('button',{name:'Retry creation'});
    vi.mocked(api.games.list).mockImplementation(async input => ok(page(input.offset === 24 ? [recovered] : Array.from({length:24},(_,index) => game({id:`record-${index}`})),input.offset ?? 0,25)));
    vi.mocked(api.games.detail).mockResolvedValue(ok(recovered));
    await user.click(screen.getByRole('button',{name:'Check Library'}));
    await screen.findByRole('heading',{name:'Choose only if this is the game you created'});
    const lookupQuery = vi.mocked(api.games.list).mock.lastCall?.[0].query ?? '';
    expect(Array.from(lookupQuery).length).toBeLessThanOrEqual(255);
    expect(new URL(url).href.startsWith(lookupQuery)).toBe(true);
    await user.click(screen.getByRole('button',{name:'Next matches'}));
    await waitFor(() => expect(vi.mocked(api.games.list).mock.lastCall?.[0]).toMatchObject({offset:24}));
    await user.click(await screen.findByRole('button',{name:'Use this record'}));
    expect(await screen.findByRole('heading',{name:url})).toBeVisible();
    expect(api.games.create).toHaveBeenCalledOnce();
  });

  it('keeps editing on Escape, discards only explicitly, and unregisters the guard on unmount', async () => {
    const { user, navigate, onGuard, unmount } = start(); await edit(user);
    await user.type(screen.getByRole('textbox', { name: 'Name' }), ' changed');
    const leave = vi.fn(); await navigate(leave);
    await user.keyboard('{Escape}'); expect(leave).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Harbor Lights changed');
    await navigate(leave); await user.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(leave).toHaveBeenCalledOnce();
    unmount(); expect(onGuard).toHaveBeenLastCalledWith(null);
  });

  it('loads normally under StrictMode and retries a failed next page without erasing the current page', async () => {
    const api = apiMock();
    vi.mocked(api.games.list).mockImplementation(async input => input.offset ? error() : ok(page([game()], 0, 50)));
    render(<StrictMode><GameLibrary api={api} active/></StrictMode>);
    const user = userEvent.setup(); await screen.findByRole('button', { name: 'Open Harbor Lights' });
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted');
    expect(screen.getByRole('button', { name: 'Open Harbor Lights' })).toBeVisible();
    expect(screen.getByText('1–1 of 50')).toBeVisible();
    vi.mocked(api.games.list).mockResolvedValueOnce(ok(page([game({ name: 'Second page' })], 24, 50)));
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: 'Open Second page' })).toBeVisible();
    expect(vi.mocked(api.games.list).mock.lastCall?.[0].offset).toBe(24);
  });

  it('saves favorite only, refreshes filtered totals and returns from an out-of-range page', async () => {
    const api = apiMock(); const savedGame = game({ favorite: true });
    let afterSave = false;
    vi.mocked(api.games.list).mockImplementation(async input => afterSave ? ok(page([game({ name: 'Remaining game', favorite: true })], input.offset || 0, 1)) : ok(page([savedGame], input.offset || 0, 25)));
    vi.mocked(api.games.detail).mockResolvedValue(ok(savedGame));
    vi.mocked(api.games.update).mockImplementation(async () => { afterSave = true; return ok(game({ favorite: false, revision: 8 })); });
    const { user } = start(api); await screen.findByRole('button', { name: 'Open Harbor Lights' });
    await user.click(screen.getByRole('checkbox', { name: 'Saved only' }));
    await screen.findByRole('button', { name: 'Open Harbor Lights' });
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(screen.getByText('25–25 of 25')).toBeVisible());
    await edit(user); await user.click(screen.getByRole('checkbox', { name: 'Saved' }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByRole('button', { name: 'Edit game' });
    expect(vi.mocked(api.games.update).mock.calls[0][0].data).toEqual({ expected_revision: 7, favorite: false });
    await waitFor(() => expect(vi.mocked(api.games.list).mock.lastCall?.[0]).toMatchObject({ onlyCollection: true, offset: 0 }));
    await user.click(screen.getByRole('button', { name: 'Back to games' }));
    expect(screen.getByRole('checkbox', { name: 'Saved only' })).toBeChecked();
    expect(screen.getByText('1–1 of 1')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Open Remaining game' })).toBeVisible();
  });

  it('does not normalize or replace untouched source fields and 101 existing references', async () => {
    const api = apiMock(); const original = game({ developer: 'Original developer ', tags: ['A tag\nwith a newline'], reference_works: Array.from({ length: 101 }, (_, index) => ({ name: `Reference ${index}`, reason: 'Existing trailing space ', similarities: [] })) });
    vi.mocked(api.games.detail).mockResolvedValue(ok(original));
    const { user } = start(api); await edit(user);
    await user.type(screen.getByRole('textbox', { name: 'Description' }), ' More.');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(api.games.update).toHaveBeenCalledOnce());
    expect(vi.mocked(api.games.update).mock.calls[0][0].data).toEqual({ expected_revision: 7, description: 'Explore an island at dusk. More.' });
  });

  it('adds name-only references, removes draft entries and shows the deduplicated server list', async () => {
    const api = apiMock(); const id = '00000000-0000-4000-8000-000000000090';
    vi.mocked(api.games.update).mockResolvedValue(ok(game({ revision: 8, reference_works: [{ id, name: 'One lighthouse', url: null, similarities: [], reason: null }] })));
    const { user } = start(api); await edit(user);
    for (const name of ['Beacon', 'Beacon', 'Remove me']) {
      await user.click(screen.getByRole('button', { name: 'Add reference' }));
      const groups = screen.getAllByRole('group', { name: /^Reference \d+$/ });
      await user.type(within(groups.at(-1)!).getByRole('textbox', { name: 'Reference name' }), name);
    }
    await user.click(screen.getByRole('button', { name: 'Remove reference Remove me' }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('One lighthouse')).toBeVisible();
    expect(vi.mocked(api.games.update).mock.calls[0][0].data.reference_works).toEqual([
      { name: 'Beacon', url: null, similarities: [], reason: null }, { name: 'Beacon', url: null, similarities: [], reason: null },
    ]);
    expect(screen.queryByText('Remove me')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Reference works 1' })).toBeVisible();
  });

  it('shows the latest source value during reset conflict and allows discarding the rejected edit', async () => {
    const api = apiMock(); const latest = game({ revision: 9, source_fields: { ...fields, developer: 'Fresh source studio' } });
    vi.mocked(api.games.detail).mockResolvedValueOnce(ok(game())).mockResolvedValueOnce(ok(latest));
    vi.mocked(api.games.update).mockResolvedValue(error('game_revision_conflict'));
    const { user, navigate } = start(api); await edit(user);
    await user.click(screen.getByText('Source comparison', { selector: 'summary' }));
    await user.click(screen.getByRole('button', { name: 'Use source Developer' }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('Fresh source studio');
    expect(screen.queryByText('Original Studio')).not.toBeInTheDocument();
    const leave = vi.fn(); await navigate(leave);
    expect(screen.getByRole('button', { name: 'Save and leave' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Discard changes' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Discard changes' }));
    expect(leave).toHaveBeenCalledOnce(); expect(api.games.update).toHaveBeenCalledOnce();
  });

  it('does not unlock an uncertain original POST when its retry is rejected', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValueOnce(error()).mockResolvedValueOnce(error('workspace_key_invalid', 'Key rejected')).mockResolvedValueOnce(ok(game()));
    const { user } = start(api); await user.click(await screen.findByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Uncertain original');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await user.click(await screen.findByRole('button', { name: 'Retry creation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Key rejected');
    expect(screen.getByRole('textbox', { name: 'Name' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Retry creation' }));
    await waitFor(() => expect(api.games.create).toHaveBeenCalledTimes(3));
    const requests = vi.mocked(api.games.create).mock.calls.map(call => call[0]);
    expect(requests[1]).toEqual(requests[0]); expect(requests[2]).toEqual(requests[0]);
  });

  it('unlocks a first definitively rejected creation but blocks replay after a workspace change', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValueOnce(error('access_denied', 'Permission denied')).mockResolvedValueOnce(error('connection_changed', 'Workspace changed'));
    const { user } = start(api); await user.click(await screen.findByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Local draft');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied');
    expect(screen.getByRole('textbox', { name: 'Name' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await screen.findByRole('button', { name: 'Retry creation' });
    expect(screen.getByRole('button', { name: 'Retry creation' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check Library' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Name' })).toBeDisabled();
  });

  it('renders a navigation confirmation outside hidden ancestors and freezes all fields while saving', async () => {
    let guard: NavigationGuard | null = null;
    const api = apiMock(); const saving = deferred<Result<GameDetail>>(); vi.mocked(api.games.update).mockReturnValue(saving.promise);
    const onGuard = (value: NavigationGuard | null) => { guard = value; };
    const { rerender } = render(<div><GameLibrary api={api} active onNavigationGuardChange={onGuard}/></div>);
    const user = userEvent.setup(); await edit(user); await user.type(screen.getByRole('textbox', { name: 'Developer' }), ' revised');
    rerender(<div hidden><GameLibrary api={api} active={false} onNavigationGuardChange={onGuard}/></div>);
    const leave = vi.fn(); act(() => guard?.(leave));
    expect(screen.getByRole('dialog', { name: 'Unsaved game changes' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Continue editing' }));
    rerender(<div><GameLibrary api={api} active onNavigationGuardChange={onGuard}/></div>);
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(screen.getByRole('textbox', { name: 'Developer' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Saved' })).toBeDisabled();
    await act(async () => saving.resolve(ok(game({ revision: 8, developer: 'Tide Studio revised' }))));
    expect(await screen.findByRole('button', { name: 'Edit game' })).toBeVisible();
  });

  it('keeps a successful save successful when refreshing the Library fails', async () => {
    const api = apiMock(); vi.mocked(api.games.list).mockResolvedValueOnce(ok(page())).mockResolvedValue(error('network_error', 'Library refresh failed'));
    vi.mocked(api.games.update).mockResolvedValue(ok(game({ revision: 8, name: 'Renamed successfully' })));
    const { user } = start(api); await edit(user); const name = screen.getByRole('textbox', { name: 'Name' }); await user.clear(name); await user.type(name, 'Renamed successfully');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('heading', { name: 'Renamed successfully' })).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('Saved');
    await user.click(screen.getByRole('button', { name: 'Back to games' }));
    expect(screen.getByRole('button', { name: 'Open Renamed successfully' })).toBeVisible();
    expect(screen.getByRole('alert')).toHaveTextContent('Library refresh failed');
    expect(api.games.update).toHaveBeenCalledOnce();
  });

  it('permits credential recovery after an uncertain POST but never replays it after the key changes', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValueOnce(error()).mockResolvedValueOnce(error('workspace_key_invalid', 'Key rejected'));
    const { user, onGuard } = start(api); await user.click(await screen.findByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Keep the original draft');
    await user.type(screen.getByRole('textbox', { name: 'Description' }), 'Original description');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await user.click(await screen.findByRole('button', { name: 'Retry creation' }));
    await screen.findByText('Key rejected');
    const recovery = onGuard.mock.lastCall?.[0]?.recovery;
    expect(recovery).toBeDefined();
    act(() => recovery!.credentialsChanged());
    expect(screen.getByText('Credentials changed. Check the original Library to confirm the saved game.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Retry creation' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Check Library' })).toBeEnabled();
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Keep the original draft');
    expect(screen.getByRole('textbox', { name: 'Description' })).toHaveValue('Original description');
    expect(onGuard.mock.lastCall?.[0]?.recovery).toBeDefined();
    await user.click(screen.getByRole('button', { name: 'Retry creation' }));
    expect(api.games.create).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: 'Check Library' }));
    await user.click(await screen.findByRole('button', { name: 'Use this record' }));
    expect(await screen.findByRole('heading', { name: 'Harbor Lights' })).toBeVisible();
    expect(api.games.create).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.games.create).mock.calls[1][0]).toEqual(vi.mocked(api.games.create).mock.calls[0][0]);
  });

  it('keeps a first rejected creation editable during same-origin credential repair', async () => {
    const api = apiMock(); vi.mocked(api.games.create).mockResolvedValueOnce(error('workspace_key_invalid', 'Key rejected')).mockResolvedValueOnce(ok(game()));
    const { user, onGuard } = start(api); await user.click(await screen.findByRole('button', { name: 'New game' }));
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'An unsubmitted game');
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await screen.findByText('Key rejected');
    expect(onGuard.mock.lastCall?.[0]?.recovery).toBeDefined();
    act(() => onGuard.mock.lastCall?.[0]?.recovery?.credentialsChanged());
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('An unsubmitted game');
    expect(screen.getByRole('textbox', { name: 'Name' })).toBeEnabled();
    expect(api.games.create).toHaveBeenCalledOnce();
    expect(onGuard.mock.lastCall?.[0]?.recovery).toBeDefined();
    await user.click(screen.getByRole('button', { name: 'Create game' }));
    await screen.findByRole('button', { name: 'Edit game' });
    expect(api.games.create).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.games.create).mock.calls[1][0].idempotencyKey).not.toBe(vi.mocked(api.games.create).mock.calls[0][0].idempotencyKey);
  });

  it('preserves PATCH fields and expected revision during credential repair without auto-saving', async () => {
    const api = apiMock(); vi.mocked(api.games.update).mockResolvedValueOnce(error('access_denied', 'Permission denied')).mockResolvedValueOnce(ok(game({ revision: 8, developer: 'Repaired studio' })));
    const { user, onGuard } = start(api); await edit(user);
    const developer = screen.getByRole('textbox', { name: 'Developer' }); await user.clear(developer); await user.type(developer, 'Repaired studio');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('Permission denied');
    expect(onGuard.mock.lastCall?.[0]?.recovery).toBeDefined();
    act(() => onGuard.mock.lastCall?.[0]?.recovery?.credentialsChanged());
    expect(screen.getByRole('textbox', { name: 'Developer' })).toHaveValue('Repaired studio');
    expect(api.games.update).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByRole('button', { name: 'Edit game' });
    expect(vi.mocked(api.games.update).mock.calls[1][0].data).toEqual({ expected_revision: 7, developer: 'Repaired studio' });
  });
});
