// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DesktopBridge, Result } from '../src/shared/bridge';
import type { CreatorDetail, CreatorPage } from '../src/shared/creators';
import { App } from '../src/renderer/App';
import { gameFixture } from './game-fixtures';
import { settingsBridgeMock } from './settings-fixtures';
import { creatorFixture, contactFixture } from './creator-fixtures';

const ok = <T,>(data: T): Result<T> => ({ ok: true, data });
const failed = (message = 'Connection interrupted'): Result<never> => ({ ok: false, error: { code: 'network_error', message, retryable: true } });
const profile = (name:string,id=name):CreatorDetail => ({...creatorFixture(name,id),description:'Thoughtful indie game discoveries.'});
const creatorPage = (items:CreatorDetail[],offset=0,total=items.length):CreatorPage => ({items,total,offset,limit:50});
function detail(name:string):CreatorDetail {
  const creator=profile(name);
  return {...creator,contacts:[{...contactFixture(),email:'hello@example.com',purpose:'Business',validation_state:'valid'},
    {...contactFixture(),id:'second-contact',email:'press@example.com',purpose:'Press',validation_state:'unknown'}],
    internal_notes:'Interested in atmospheric games.',country_name:'Canada',
    source_fields:{...creator.source_fields,description:'<script>not executable</script>'},
    manual_overrides:{...creator.manual_overrides,arbitrary_future_field:{retained:true}}};
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
function bridge(overrides: Partial<DesktopBridge> = {}): DesktopBridge {
  return {
    ...settingsBridgeMock(),
    connection: {
      status: vi.fn(async () => ok({ serviceUrl: 'https://workspace.example.com', hasKey: true, storageAvailable: true })),
      save: vi.fn(async () => ok({ serviceUrl: 'https://workspace.example.com', hasKey: true, storageAvailable: true })),
      test: vi.fn(async () => ok({ authenticated: true as const, proxy: 'system' as const, route: 'direct' as const })),
      clear: vi.fn(async () => ok({ serviceUrl: '', hasKey: false, storageAvailable: true })),
    },
    library: {
      list: vi.fn(async () => ok({items:[],nextCursor:null})),
      detail: vi.fn(async () => failed('Legacy detail unused')),
    },
    games: {
      list: vi.fn(async () => ok({items:[gameFixture()],total:1,limit:24,offset:0})),
      detail: vi.fn(async id => ok(gameFixture('A game', id))),
      create: vi.fn(async () => ok(gameFixture())),
      update: vi.fn(async () => ok(gameFixture())),
    },
    openExternal: vi.fn(async () => ok(undefined)),
    ...overrides,
  };
}
function start(api = bridge()) { window.desktop = api; render(<App />); return { api, user: userEvent.setup() }; }
afterEach(() => { cleanup(); vi.restoreAllMocks(); Reflect.deleteProperty(window, 'desktop'); });

describe('desktop renderer', () => {
  it('repairs same-origin authentication without losing an uncertain creation or replaying after credentials change', async () => {
    const api = bridge();
    vi.mocked(api.games.create).mockResolvedValueOnce(failed()).mockResolvedValueOnce({ok:false,error:{code:'workspace_key_invalid',message:'Update your workspace key',retryable:false}});
    vi.mocked(api.games.detail).mockResolvedValue(ok(gameFixture('Recovered creation')));
    const {user} = start(api);
    await screen.findByRole('button',{name:'Open Pixel Harbor'});
    await user.click(screen.getByRole('button',{name:'Settings'}));
    await user.clear(screen.getByLabelText('Service URL'));
    await user.type(screen.getByLabelText('Service URL'),'https://unsubmitted.example.com');
    await user.click(screen.getByRole('button',{name:'Library'}));
    await user.click(screen.getByRole('button',{name:'Discard changes'}));
    await user.click(screen.getByRole('tab',{name:'Games'}));
    await user.click(await screen.findByRole('button',{name:'New game'}));
    await user.type(screen.getByRole('textbox',{name:'Name'}),'Recovery draft');
    await user.click(screen.getByRole('button',{name:'Create game'}));
    await user.click(await screen.findByRole('button',{name:'Retry creation'}));
    await screen.findByText('Update your workspace key');
    await user.click(screen.getByRole('button',{name:'Repair connection'}));
    expect(await screen.findByRole('heading',{name:'Settings'})).toBeVisible();
    expect(screen.getByLabelText('Service URL')).toBeDisabled();
    expect(screen.getByLabelText('Service URL')).toHaveValue('https://workspace.example.com');
    expect(screen.getByRole('button',{name:'Disconnect'})).toBeDisabled();
    await user.type(screen.getByLabelText('Workspace key'),'repaired-test-key');
    await user.click(screen.getByRole('button',{name:'Connect'}));
    await waitFor(() => expect(api.connection.save).toHaveBeenCalledOnce());
    await screen.findByText('Connection verified');
    await user.click(screen.getByRole('button',{name:'Open Library'}));
    expect(screen.getByRole('textbox',{name:'Name'})).toHaveValue('Recovery draft');
    expect(screen.getByRole('button',{name:'Retry creation'})).toBeDisabled();
    await user.click(screen.getByRole('button',{name:'Check Library'}));
    await user.click(await screen.findByRole('button',{name:'Use this record'}));
    expect(await screen.findByRole('heading',{name:'Recovered creation'})).toBeVisible();
    expect(api.games.create).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.games.create).mock.calls[0][0]).toEqual(vi.mocked(api.games.create).mock.calls[1][0]);
  // Full cross-page recovery flow; allow contention with packaged desktop checks.
  }, 10_000);

  it('keeps an uncertain request replayable when testing unchanged credentials, and retains it through a failed repair', async () => {
    const api = bridge();
    vi.mocked(api.games.create).mockResolvedValueOnce(failed()).mockResolvedValueOnce({ok:false,error:{code:'workspace_key_invalid',message:'Repair key',retryable:false}});
    const {user} = start(api);
    await screen.findByRole('button',{name:'Open Pixel Harbor'});
    await user.click(screen.getByRole('tab',{name:'Games'}));
    await user.click(await screen.findByRole('button',{name:'New game'}));
    await user.type(screen.getByRole('textbox',{name:'Name'}),'Retained draft');
    await user.click(screen.getByRole('button',{name:'Create game'}));
    await user.click(await screen.findByRole('button',{name:'Retry creation'}));
    await screen.findByText('Repair key');
    await user.click(screen.getByRole('button',{name:'Settings'}));
    await user.click(screen.getByRole('button',{name:'Test connection'}));
    await user.click(await screen.findByRole('button',{name:'Open Library'}));
    expect(screen.getByRole('button',{name:'Retry creation'})).toBeEnabled();
    expect(api.connection.save).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button',{name:'Settings'}));
    vi.mocked(api.connection.test).mockResolvedValueOnce({ok:false,error:{code:'workspace_key_invalid',message:'Key still invalid',retryable:false}});
    await user.type(screen.getByLabelText('Workspace key'),'still-invalid-test-key');
    await user.click(screen.getByRole('button',{name:'Connect'}));
    await within(screen.getByRole('region',{name:'Settings page'})).findByText('Key still invalid');
    expect(screen.getByDisplayValue('Retained draft')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Workspace key'),'corrected-test-key');
    await user.click(screen.getByRole('button',{name:'Connect'}));
    await user.click(await screen.findByRole('button',{name:'Open Library'}));
    expect(screen.getByRole('textbox',{name:'Name'})).toHaveValue('Retained draft');
    expect(screen.getByRole('button',{name:'Retry creation'})).toBeDisabled();
    expect(api.games.create).toHaveBeenCalledTimes(2);
  });

  it('guards both workspace navigation and Library tabs while a game draft is dirty', async () => {
    const {api,user} = start();
    await screen.findByRole('button',{name:'Open Pixel Harbor'});
    await user.click(screen.getByRole('tab',{name:'Games'}));
    await user.click(await screen.findByRole('button',{name:'Open A game'}));
    await user.click(await screen.findByRole('button',{name:'Edit game'}));
    await user.type(screen.getByRole('textbox',{name:'Description'}),'Keep this draft');
    await user.click(screen.getByRole('button',{name:'Settings'}));
    expect(screen.getByRole('dialog',{name:'Unsaved game changes'})).toBeVisible();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('textbox',{name:'Description'})).toHaveValue('Keep this draft');
    await user.click(screen.getByRole('tab',{name:'Creators'}));
    expect(screen.getByRole('tab',{name:'Games'})).toHaveAttribute('aria-selected','true');
    await user.click(screen.getByRole('button',{name:'Discard changes'}));
    expect(screen.getByRole('button',{name:'Open Pixel Harbor'})).toBeVisible();
    expect(api.games.update).not.toHaveBeenCalled();
    expect(api.creators.list).toHaveBeenCalledOnce();
  });

  it('does not navigate away or clear the game draft when Save and leave fails', async () => {
    const api = bridge(); vi.mocked(api.games.update).mockResolvedValue({ok:false,error:{code:'request_invalid',message:'Review this game',retryable:false}});
    const {user} = start(api);
    await screen.findByRole('button',{name:'Open Pixel Harbor'});
    await user.click(screen.getByRole('tab',{name:'Games'}));
    await user.click(await screen.findByRole('button',{name:'Open A game'}));
    await user.click(await screen.findByRole('button',{name:'Edit game'}));
    await user.type(screen.getByRole('textbox',{name:'Developer'}),'Draft Studio');
    await user.click(screen.getByRole('button',{name:'Settings'}));
    await user.click(screen.getByRole('button',{name:'Save and leave'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Review this game');
    expect(screen.getByRole('textbox',{name:'Developer'})).toHaveValue('Draft Studio');
    expect(screen.queryByRole('heading',{name:'Settings'})).not.toBeInTheDocument();
    expect(api.games.update).toHaveBeenCalledWith({id:gameFixture().id,data:{expected_revision:0,developer:'Draft Studio'}});
  });

  it('requires the desktop bridge and never fabricates a connected browser demo', async () => {
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Open the desktop app' })).toBeVisible();
    expect(screen.queryByText('Pixel Harbor')).not.toBeInTheDocument();
  });

  it('verifies a saved key before reading Library and keeps unfinished features honest', async () => {
    const check = deferred<Result<{ authenticated: true; proxy: 'system'; route: 'direct' }>>();
    const api = bridge(); vi.mocked(api.connection.test).mockReturnValue(check.promise);
    const { user } = start(api);
    await waitFor(() => expect(api.connection.test).toHaveBeenCalledOnce());
    expect(api.creators.list).not.toHaveBeenCalled();
    await act(async () => check.resolve(ok({ authenticated: true, proxy: 'system', route: 'direct' })));
    expect(await screen.findByRole('button', { name: 'Open Pixel Harbor' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: /^Match$/ }));
    expect(screen.getByRole('heading', { name: 'Match' })).toBeVisible();
    expect(within(screen.getByRole('region', { name: 'match page' })).getByText('Not connected yet')).toBeVisible();
    expect(screen.queryByRole('button', { name: /create|run match|send/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Outreach$/ }));
    expect(screen.getByRole('heading', { name: 'Outreach' })).toBeVisible();
    expect(within(screen.getByRole('region', { name: 'outreach page' })).getByText('Not connected yet')).toBeVisible();
  });

  it('submits search explicitly and preserves separate tab queries and pages', async () => {
    const api = bridge();
    vi.mocked(api.creators.list).mockImplementation(async input => ok(creatorPage([profile(`creators:${input.query || 'all'}`)])));
    vi.mocked(api.games.list).mockImplementation(async input => ok({items:[gameFixture(`games:${input.query || 'all'}`)],total:1,limit:24,offset:0}));
    const { user } = start(api);
    await screen.findByRole('button', { name: 'Open creators:all' });
    const search = screen.getByRole('searchbox', { name: 'Search creators' });
    await user.type(search, 'cozy');
    expect(api.creators.list).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: /^Search$/ }));
    await screen.findByRole('button', { name: 'Open creators:cozy' });
    await user.click(screen.getByRole('tab', { name: 'Games' }));
    await screen.findByRole('button', { name: 'Open games:all' });
    await user.type(screen.getByRole('searchbox', { name: 'Search games' }), 'ocean{Enter}');
    await screen.findByRole('button', { name: 'Open games:ocean' });
    await user.click(screen.getByRole('tab', { name: 'Creators' }));
    expect(screen.getByRole('searchbox', { name: 'Search creators' })).toHaveValue('cozy');
    expect(screen.getByRole('button', { name: 'Open creators:cozy' })).toBeVisible();
    expect(api.creators.list).toHaveBeenCalledTimes(2);
    expect(api.games.list).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.creators.list).mock.calls.every(([input]) => input.limit === 50)).toBe(true);
    expect(api.library.list).not.toHaveBeenCalled();
  });

  it('does not let an older search replace the current results', async () => {
    const older = deferred<Result<CreatorPage>>(); const newer = deferred<Result<CreatorPage>>();
    const api = bridge();
    vi.mocked(api.creators.list).mockImplementation(async input => input.query === 'old' ? older.promise : input.query === 'new' ? newer.promise : ok(creatorPage([])));
    const { user } = start(api); await screen.findByRole('heading', { name: 'No creators yet' });
    const search = screen.getByRole('searchbox');
    await user.type(search, 'old{Enter}');
    await user.clear(search); await user.type(search, 'new{Enter}');
    await act(async () => newer.resolve(ok(creatorPage([profile('New result')]))));
    await screen.findByRole('button', { name: 'Open New result' });
    await act(async () => older.resolve(ok(creatorPage([profile('Stale result')]))));
    expect(screen.queryByRole('button', { name: 'Open Stale result' })).not.toBeInTheDocument();
  });

  it('keeps the current page when the next page fails and retries the same offset', async () => {
    const api = bridge();
    vi.mocked(api.creators.list).mockResolvedValueOnce(ok(creatorPage([profile('First')],0,51)))
      .mockResolvedValueOnce(failed()).mockResolvedValueOnce(ok(creatorPage([profile('Second')],50,51)));
    const { user } = start(api); await screen.findByRole('button', { name: 'Open First' });
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted');
    expect(screen.getByRole('button', { name: 'Open First' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: 'Open Second' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Open First' })).not.toBeInTheDocument();
    expect(vi.mocked(api.creators.list).mock.calls[2][0].offset).toBe(50);
  });

  it('shows all v2 contacts and retained source fields, then returns to the same list', async () => {
    const api=bridge();vi.mocked(api.creators.detail).mockResolvedValue(ok(detail('Pixel Harbor')));
    const { user } = start(api); await screen.findByRole('button', { name: 'Open Pixel Harbor' });
    await user.click(screen.getByRole('button', { name: 'Open Pixel Harbor' }));
    expect(await screen.findByRole('heading', { name: 'Pixel Harbor' })).toBeVisible();
    expect(within(screen.getByRole('article')).getByText('Followers unknown')).toBeVisible();
    await user.click(screen.getByText('Profile source details',{selector:'summary'}));
    expect(screen.getByText(/<script>not executable<\/script>/)).toBeVisible();
    expect(screen.getByText(/arbitrary_future_field/)).toBeVisible();
    expect(screen.getByRole('button',{name:'Edit profile'})).toBeEnabled();
    await user.click(screen.getByRole('tab',{name:'Emails'}));
    expect(screen.getByText('hello@example.com')).toBeVisible();
    expect(screen.getByText('press@example.com')).toBeVisible();
    expect(screen.getByText('Business')).toBeVisible();
    expect(screen.getByText('Press')).toBeVisible();
    expect(screen.queryByText('0 followers')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /send|analyze/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Back to creators' }));
    expect(screen.getByRole('button', { name: 'Open Pixel Harbor' })).toBeVisible();
  });

  it('clears private results on disconnect and ignores a late detail response', async () => {
    const pending = deferred<Result<CreatorDetail>>(); const api = bridge();
    vi.mocked(api.creators.detail).mockReturnValue(pending.promise);
    const { user } = start(api); await screen.findByRole('button', { name: 'Open Pixel Harbor' });
    await user.click(screen.getByRole('button', { name: 'Open Pixel Harbor' }));
    await user.click(screen.getByRole('button', { name: /^Settings$/ }));
    await user.click(screen.getByRole('button', { name: /^Disconnect$/ }));
    const dialog = screen.getByRole('dialog', { name: 'Disconnect workspace?' });
    await user.click(within(dialog).getByRole('button', { name: /^Disconnect$/ }));
    await waitFor(() => expect(api.connection.clear).toHaveBeenCalledOnce());
    await act(async () => pending.resolve(ok(detail('Private late result'))));
    await user.click(screen.getByRole('button', { name: /^Library$/ }));
    expect(screen.getByRole('heading', { name: 'Connect your workspace' })).toBeVisible();
    expect(screen.queryByText('Private late result')).not.toBeInTheDocument();
    expect(screen.queryByText('hello@example.com')).not.toBeInTheDocument();
  });

  it('clears a submitted key, never writes it to storage, and distinguishes saved from verified', async () => {
    const api = bridge(); vi.mocked(api.connection.status).mockResolvedValue(ok({ serviceUrl: '', hasKey: false, storageAvailable: true }));
    const save = deferred<Result<{serviceUrl: string; hasKey: boolean; storageAvailable: boolean}>>();
    const check = deferred<Result<{authenticated: true; proxy: 'system'; route: 'direct'}>>();
    vi.mocked(api.connection.save).mockReturnValue(save.promise);
    vi.mocked(api.connection.test).mockReturnValue(check.promise);
    const storage = vi.spyOn(Storage.prototype, 'setItem'); const { user } = start(api);
    await screen.findByRole('heading', { name: 'Connect your workspace' });
    await user.click(screen.getByRole('button', { name: 'Open Settings' }));
    await user.type(screen.getByRole('textbox', { name: 'Service URL' }), 'https://workspace.example.com');
    const key = screen.getByLabelText('Workspace key');
    await user.type(key, 'test-only-secret');
    await user.click(screen.getByRole('button', { name: /^Connect$/ }));
    expect(key).toHaveValue('');
    expect(storage).not.toHaveBeenCalled();
    expect(api.connection.save).toHaveBeenCalledWith({ serviceUrl: 'https://workspace.example.com', key: 'test-only-secret' });
    await act(async () => save.resolve(ok({ serviceUrl: 'https://workspace.example.com', hasKey: true, storageAvailable: true })));
    expect(screen.getByText('Saved · Verifying workspace…')).toBeVisible();
    expect(screen.queryByText('Connection verified')).not.toBeInTheDocument();
    expect(api.creators.list).not.toHaveBeenCalled();
    await waitFor(() => expect(api.connection.test).toHaveBeenCalledOnce());
    await act(async () => check.resolve(ok({ authenticated: true, proxy: 'system', route: 'direct' })));
    expect(await screen.findByText('Connection verified')).toBeVisible();
  });

  it('keeps blocking authentication errors visible and offers a real retry', async () => {
    const api = bridge(); vi.mocked(api.connection.test).mockResolvedValueOnce(failed('Workspace key was rejected'))
      .mockResolvedValueOnce(ok({ authenticated: true, proxy: 'system', route: 'direct' }));
    const { user } = start(api);
    expect(await screen.findByRole('alert')).toHaveTextContent('Workspace key was rejected');
    expect(api.creators.list).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: 'Open Pixel Harbor' })).toBeVisible();
  });

  it('distinguishes an empty filtered result and recovers a failed detail locally', async () => {
    const api = bridge(); vi.mocked(api.creators.list).mockResolvedValueOnce(ok(creatorPage([])))
      .mockResolvedValue(ok(creatorPage([profile('Recovered')])));
    vi.mocked(api.creators.detail).mockResolvedValueOnce(failed('Profile unavailable')).mockResolvedValueOnce(ok(detail('Recovered')));
    const { user } = start(api); await screen.findByRole('heading', { name: 'No creators yet' });
    await user.type(screen.getByRole('searchbox'), 'cozy{Enter}');
    await user.click(await screen.findByRole('button', { name: 'Open Recovered' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Profile unavailable');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Recovered' })).toBeVisible();
  });

  it('keeps tab controls keyboard accessible and clears submitted filters explicitly', async () => {
    const api = bridge(); vi.mocked(api.creators.list).mockImplementation(async input => ok(creatorPage(input.query ? [] : [profile('creators')])));
    vi.mocked(api.games.list).mockImplementation(async input => ok({items:input.query?[]:[gameFixture('games')],total:input.query?0:1,limit:24,offset:0}));
    const { user } = start(api); await screen.findByRole('button', { name: 'Open creators' });
    screen.getByRole('tab', { name: 'Creators' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Games' })).toHaveFocus();
    expect(screen.getByRole('tab', { name: 'Games' })).toHaveAttribute('aria-selected', 'true');
    await screen.findByRole('button', { name: 'Open games' });
    await user.type(screen.getByRole('searchbox', { name: 'Search games' }), 'unmatched{Enter}');
    expect(await screen.findByRole('heading', { name: 'No matching games' })).toBeVisible();
    const empty = screen.getByRole('heading', { name: 'No matching games' }).parentElement!;
    await user.click(within(empty).getByRole('button', { name: 'Clear filters' }));
    expect(await screen.findByRole('button', { name: 'Open games' })).toBeVisible();
    expect(screen.getByRole('searchbox', { name: 'Search games' })).toHaveValue('');
  });

  it('keeps collection filters and successful pagination independent across tabs and navigation', async () => {
    const api = bridge(); vi.mocked(api.creators.list).mockImplementation(async input => {
      if (input.offset) return ok(creatorPage([profile('Second saved')],50,51));
      return ok(creatorPage([profile(input.onlyCollection ? 'First saved' : 'All creator')],0,input.onlyCollection?51:1));
    });
    const { user } = start(api); await screen.findByRole('button', { name: 'Open All creator' });
    await user.click(screen.getByRole('checkbox', { name: 'Saved only' }));
    await screen.findByRole('button', { name: 'Open First saved' });
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    await screen.findByRole('button', { name: 'Open Second saved' });
    await user.click(screen.getByRole('tab', { name: 'Games' }));
    await screen.findByRole('button', { name: 'Open A game' });
    expect(screen.getByRole('checkbox', { name: 'Saved only' })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: /^Settings$/ }));
    await user.click(screen.getByRole('button', { name: /^Library$/ }));
    await user.click(screen.getByRole('tab', { name: 'Creators' }));
    expect(screen.getByRole('checkbox', { name: 'Saved only' })).toBeChecked();
    expect(screen.queryByRole('button', { name: 'Open First saved' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open Second saved' })).toBeVisible();
    expect(api.creators.list).toHaveBeenCalledTimes(3);
    expect(api.games.list).toHaveBeenCalledOnce();
    expect(vi.mocked(api.creators.list).mock.calls[2][0]).toMatchObject({ onlyCollection: true, offset: 50 });
  });

  it('ignores late list data from a replaced connection', async () => {
    const old = deferred<Result<CreatorPage>>(); const api = bridge();
    vi.mocked(api.creators.list).mockReturnValueOnce(old.promise).mockResolvedValueOnce(ok(creatorPage([profile('New workspace profile')])));
    vi.mocked(api.connection.save).mockResolvedValue(ok({ serviceUrl: 'https://new.example.com', hasKey: true, storageAvailable: true }));
    const { user } = start(api); await waitFor(() => expect(api.creators.list).toHaveBeenCalledOnce());
    await user.click(screen.getByRole('button', { name: /^Settings$/ }));
    const url = screen.getByRole('textbox', { name: 'Service URL' });
    await user.clear(url); await user.type(url, 'https://new.example.com');
    await user.type(screen.getByLabelText('Workspace key'), 'new-test-key');
    await user.click(screen.getByRole('button', { name: /^Connect$/ }));
    await screen.findByText('Connection verified');
    await user.click(screen.getByRole('button', { name: /^Library$/ }));
    expect(await screen.findByRole('button', { name: 'Open New workspace profile' })).toBeVisible();
    await act(async () => old.resolve(ok(creatorPage([profile('Old private profile')]))));
    expect(screen.queryByRole('button', { name: 'Open Old private profile' })).not.toBeInTheDocument();
  });

  it('can cancel disconnect with Escape without losing data or executing a mutation', async () => {
    const { user, api } = start(); await screen.findByRole('button', { name: 'Open Pixel Harbor' });
    await user.click(screen.getByRole('button', { name: /^Settings$/ }));
    const disconnect = screen.getByRole('button', { name: /^Disconnect$/ });
    await user.click(disconnect);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(within(dialog).getByRole('button', { name: /^Disconnect$/ })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(disconnect).toHaveFocus();
    expect(api.connection.clear).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /^Library$/ }));
    expect(screen.getByRole('button', { name: 'Open Pixel Harbor' })).toBeVisible();
  });

  it('reports unavailable secure storage and never attempts to save a key', async () => {
    const api = bridge(); vi.mocked(api.connection.status).mockResolvedValue(ok({ serviceUrl: '', hasKey: false, storageAvailable: false }));
    const { user } = start(api); await screen.findByRole('heading', { name: 'Connect your workspace' });
    await user.click(screen.getByRole('button', { name: 'Open Settings' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Secure storage is unavailable');
    expect(screen.getByLabelText('Workspace key')).toBeDisabled();
    expect(screen.getByRole('button', { name: /^Connect$/ })).toBeDisabled();
    expect(api.connection.save).not.toHaveBeenCalled();
  });

  it('preserves searches, pages and the open profile after verifying unchanged credentials', async () => {
    const api = bridge(); vi.mocked(api.creators.list).mockImplementation(async input => ok(creatorPage([profile(input.query || 'Initial')])));
    const recheck = deferred<Result<{authenticated: true; proxy: 'system'; route: 'direct'}>>();
    const { user } = start(api); await screen.findByRole('button', { name: 'Open Initial' });
    await user.type(screen.getByRole('searchbox'), 'Saved context{Enter}');
    await user.click(await screen.findByRole('button', { name: 'Open Saved context' }));
    await screen.findByRole('heading', { name: 'Saved context' });
    await user.click(screen.getByRole('button', { name: /^Settings$/ }));
    vi.mocked(api.connection.test).mockReturnValueOnce(recheck.promise);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));
    await user.click(screen.getByRole('button', { name: /^Library$/ }));
    expect(screen.queryByRole('heading', { name: 'Saved context' })).not.toBeInTheDocument();
    await act(async () => recheck.resolve(ok({ authenticated: true, proxy: 'system', route: 'direct' })));
    expect(await screen.findByRole('heading', { name: 'Saved context' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Back to creators' }));
    expect(screen.getByRole('searchbox')).toHaveValue('Saved context');
    expect(screen.getByRole('button', { name: 'Open Saved context' })).toBeVisible();
    expect(api.creators.list).toHaveBeenCalledTimes(2);
    expect(api.creators.detail).toHaveBeenCalledOnce();
  });
});
