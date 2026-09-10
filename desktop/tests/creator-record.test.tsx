// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DesktopBridge, Result } from '../src/shared/bridge';
import type { ContactDetail, CreatorDetail, WorkDetail, WorkPage } from '../src/shared/creators';
import { CreatorRecord } from '../src/renderer/components/creators/CreatorRecord';

const ok = <T,>(data: T): Result<T> => ({ ok: true, data });
const failure = (message = 'The works could not be loaded'): Result<never> => ({ ok: false, error: { code: 'network_error', message, retryable: true } });
const contact = (overrides: Partial<ContactDetail> = {}): ContactDetail => ({
  id: 'contact-current', email: 'hello@pixel.example', purpose: 'Partnerships', source_url: 'https://pixel.example/contact',
  is_active: true, verification_notes: 'Syntax checked only', origin: 'source', source_type: 'channel_about',
  validation_state: 'valid', source_fields: { email: 'hello@pixel.example' }, manual_overrides: {},
  identity_revision: 4, is_current_identity: true, updated_at: '2026-09-07T12:00:00Z', ...overrides,
});
const creator = (overrides: Partial<CreatorDetail> = {}): CreatorDetail => ({
  id: 'creator-one', platform: 'youtube', revision: 8, favorite: true, name: 'Pixel Harbor', public_name: 'Mara',
  public_name_confirmed: false, handle: '@pixelharbor', profile_url: 'https://youtube.com/@pixelharbor',
  avatar_url: null, description: 'Thoughtful strategy reviews and design essays.', follower_count: null,
  follower_count_collected_at: null, languages: ['English', 'Japanese'], country_code: 'CA', country_name: 'Canada',
  other_contacts: [{ label: 'Press kit', value: 'pixel.example/press', url: 'https://pixel.example/press' }],
  source_notes: 'Found through a channel page.', internal_notes: 'Prefers concise briefs.', interest_notes: 'Cozy strategy games.',
  source_identity: { platform: 'youtube', account_id: 'UC-pixel', canonical_url: 'https://youtube.com/channel/UC-pixel', revision: 4 },
  source_fields: {
    name: 'Pixel Harbor Source', public_name: null, public_name_confirmed: false, handle: '@sourcehandle',
    profile_url: 'https://youtube.com/channel/UC-pixel', avatar_url: null, description: 'Source description', follower_count: null,
    follower_count_collected_at: null, languages: ['English'], country_code: 'CA', country_name: 'Canada', other_contacts: [],
    source_notes: null, internal_notes: null, interest_notes: null,
  },
  manual_overrides: { name: 'Pixel Harbor' }, overridden_fields: ['name'], contacts: [
    contact(),
    contact({ id: 'contact-hidden', email: 'old-current@pixel.example', is_active: false, origin: 'manual', source_type: 'manual', validation_state: 'unverified' }),
    contact({ id: 'contact-history', email: 'former@pixel.example', identity_revision: 2, is_current_identity: false, source_url: null }),
  ],
  work_count: 3, last_analyzed_at: null, next_analysis_at: null, analysis_available: true, ...overrides,
});
const work = (overrides: Partial<WorkDetail> = {}): WorkDetail => ({
  id: 'work-current', creator_id: 'creator-one', platform: 'youtube', source_platform: 'youtube',
  work_name: 'Harbor Tactics', content_title: 'Seven calm openings', content_type: 'gameplay',
  source_url: 'https://youtube.com/watch?v=calm', content_id: 'editable-display-id', published_at: '2026-08-01T09:00:00Z',
  collected_at: '2026-08-02T09:00:00Z', metrics: [{ name: 'views', value: 12000 }, { name: 'likes', value: 800 }],
  game_id: 'game-one', verification_notes: 'Matched by title.', evidence_excerpt: 'The creator explains the opening route.',
  timestamp_seconds: 93, origin: 'source', revision: 5, identity_revision: 4, is_current_identity: true,
  source_content_id: 'immutable-source-id', source_collected_at: '2026-08-02T08:30:00Z',
  source_fields: { content_title: 'Seven calm openings (source)', content_id: 'immutable-source-id' },
  manual_overrides: { content_title: 'Seven calm openings' }, ...overrides,
});
const page = (items: WorkDetail[] = [work()], offset = 0, total = items.length): WorkPage => ({ items, total, limit: 50, offset });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function apiMock() {
  const api = {
    creators: { works: vi.fn(async () => ok(page())) },
    games: { detail: vi.fn(async () => ok({ id: 'game-one', name: 'Harbor Tactics' })) },
    openExternal: vi.fn(async () => ok(undefined)),
  };
  return api as unknown as DesktopBridge;
}
function start(options: { api?: DesktopBridge; record?: CreatorDetail; initialSection?: 'profile' | 'emails' | 'works' } = {}) {
  const api = options.api ?? apiMock(); const onEdit = vi.fn(); const onBack = vi.fn();
  const view = render(<CreatorRecord api={api} creator={options.record ?? creator()} onBack={onBack} onEdit={onEdit} initialSection={options.initialSection}/>);
  return { api, onEdit, onBack, user: userEvent.setup(), ...view };
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('CreatorRecord', () => {
  it('shows a concise profile, explicit identity, unknown followers and safe HTTPS actions', async () => {
    const { api, user, onEdit, onBack } = start();
    expect(screen.getByRole('heading', { name: 'Pixel Harbor' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Profile' })).toHaveClass('sr-only');
    expect(within(screen.getByRole('banner')).getByText('@pixelharbor')).toBeVisible();
    expect(screen.getByText('Followers unknown')).toBeVisible();
    expect(screen.getByText('Public name not confirmed')).toBeVisible();
    expect(screen.getByText('Thoughtful strategy reviews and design essays.')).toBeVisible();
    expect(screen.getByText('English, Japanese')).toBeVisible();
    expect(screen.getByText('Prefers concise briefs.')).toBeVisible();
    expect(screen.getByText('Cozy strategy games.')).toBeVisible();
    const identity = screen.getByLabelText('Account identity');
    const identityDisclosure = identity.closest('details');
    expect(identity.querySelector('.creator-disclosure-chevron')).toBeInTheDocument();
    expect(identityDisclosure).not.toHaveAttribute('open');
    await user.click(identity);
    expect(identityDisclosure).toHaveAttribute('open');
    expect(screen.getByText('UC-pixel')).toBeVisible();
    expect(screen.getByText('https://youtube.com/@pixelharbor')).toBeVisible();
    expect(screen.getByText('https://youtube.com/channel/UC-pixel')).toBeVisible();
    expect(screen.queryByText('Metadata discovery unavailable; maintain this account manually.')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Change identity' }));
    expect(onEdit).toHaveBeenCalledWith({ kind: 'identity' });
    await user.click(screen.getByRole('button', { name: 'Open profile' }));
    expect(api.openExternal).toHaveBeenCalledWith('https://youtube.com/@pixelharbor');
    await user.click(screen.getByRole('button', { name: 'Back to creators' }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('keeps an external-open failure local to the profile', async () => {
    const api = apiMock(); vi.mocked(api.openExternal).mockRejectedValue(new Error('shell detail'));
    const { user } = start({ api });
    await user.click(screen.getByRole('button', { name: 'Open profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This profile link could not be opened.');
  });

  it('keeps identity and safety guidance behind concise disclosures', async () => {
    const { user } = start({ record: creator({ description: null, public_name: null, languages: [], country_code: null, country_name: null, other_contacts: [] }) });
    const identity = screen.getByLabelText('Account identity');
    expect(identity).toBeVisible();
    expect(screen.getByText('Profile source details', { selector: 'summary' })).toBeVisible();
    expect(screen.queryByText('Source identity is retained separately from editable profile values.')).not.toBeInTheDocument();
    expect(screen.queryByText('No profile summary recorded.')).not.toBeInTheDocument();
    expect(screen.queryByText('None recorded.')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Emails' }));
    const validation = screen.getByText('What validation means', { selector: 'summary' });
    expect(validation).toBeVisible();
    expect(screen.getByText('Validation describes recorded checks; it does not prove mailbox deliverability.')).not.toBeVisible();
    await user.click(validation);
    expect(screen.getByText('Validation describes recorded checks; it does not prove mailbox deliverability.')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Known works' }));
    const listHelp = screen.getByText('About this list', { selector: 'summary' });
    expect(listHelp).toBeVisible();
    expect(screen.getByText('Known works are saved records, not a complete viewing or play history.')).not.toBeVisible();
  });

  it('shows every email with provenance and keeps historical identities read-only', async () => {
    const unsafe = creator({ contacts: [
      ...creator().contacts,
      contact({ id: 'unsafe', email: 'unsafe@pixel.example', source_url: 'mailto:unsafe@pixel.example', validation_state: 'unverified' }),
    ] });
    const { api, user, onEdit } = start({ record: unsafe, initialSection: 'emails' });
    expect(screen.getByText('hello@pixel.example')).toBeVisible();
    expect(screen.getByText('old-current@pixel.example')).toBeVisible();
    expect(screen.getByText('former@pixel.example')).toBeVisible();
    expect(screen.getAllByText('Valid').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Unverified').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Syntax checked only').length).toBeGreaterThan(0);
    expect(screen.getByText('Previous identity')).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /send/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit hello@pixel.example' }));
    expect(onEdit).toHaveBeenCalledWith({ kind: 'contact', base: expect.objectContaining({ id: 'contact-current' }) });
    await user.click(screen.getByRole('button', { name: 'Edit or restore old-current@pixel.example' }));
    expect(onEdit).toHaveBeenCalledWith({ kind: 'contact', base: expect.objectContaining({ id: 'contact-hidden' }) });
    expect(screen.queryByRole('button', { name: /former@pixel\.example/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open source for hello@pixel.example' }));
    expect(api.openExternal).toHaveBeenCalledWith('https://pixel.example/contact');
    expect(api.openExternal).not.toHaveBeenCalledWith('mailto:unsafe@pixel.example');
  });

  it('keeps two page tabs and fetches work records only when their group is expanded', async () => {
    const { api, user } = start();
    expect(api.creators.works).not.toHaveBeenCalled();
    const profile = screen.getByRole('tab', { name:'Profile' });
    expect(profile).toHaveAttribute('tabindex', '0');
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Emails' })).toHaveAttribute('aria-expanded', 'false');
    await user.click(screen.getByRole('button', { name: 'Emails' }));
    expect(api.creators.works).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Known works' }));
    await waitFor(()=>expect(screen.getByRole('button', { name: 'Known works' })).toHaveAttribute('aria-expanded','true'));
    expect(screen.getByRole('heading', { name: 'Known works' })).toHaveClass('sr-only');
    await waitFor(() => expect(api.creators.works).toHaveBeenCalledWith({ creatorId: 'creator-one', includePreviousIdentity: false, limit: 50, offset: 0 }));
  });

  it('focuses the record title on entry and a new creator, but not same-creator refreshes', async () => {
    const onEdit = vi.fn(); const onBack = vi.fn(); const api = apiMock();
    const view = render(<CreatorRecord api={api} creator={creator()} onBack={onBack} onEdit={onEdit}/>);
    const firstTitle = screen.getByRole('heading', { name: 'Pixel Harbor' });
    expect(firstTitle).toHaveAttribute('tabindex', '-1');
    await waitFor(() => expect(firstTitle).toHaveFocus());
    const openProfile = screen.getByRole('button', { name: 'Open profile' });
    openProfile.focus();
    view.rerender(<CreatorRecord api={api} creator={creator({ revision: 9, description: 'Updated in the background.' })} onBack={onBack} onEdit={onEdit}/>);
    expect(openProfile).toHaveFocus();
    view.rerender(<CreatorRecord api={api} creator={creator({ id: 'creator-two', name: 'Second creator' })} onBack={onBack} onEdit={onEdit}/>);
    const secondTitle = screen.getByRole('heading', { name: 'Second creator' });
    await waitFor(() => expect(secondTitle).toHaveFocus());
  });

  it('renders bounded work evidence and provenance without making history claims', async () => {
    const longMetric = 'average_concurrent_viewers_across_the_entire_broadcast_window';
    const prior = work({ id: 'work-prior', content_title: 'An older review', is_current_identity: false, identity_revision: 2 });
    const currentWork = work({ metrics: [...work().metrics, { name: longMetric, value: 123 }] });
    const api = apiMock();
    vi.mocked(api.creators.works).mockResolvedValue(ok(page([currentWork, prior], 0, 2)));
    const { user, onEdit } = start({ api, initialSection: 'works' });
    const heading = await screen.findByRole('heading', { name: 'Seven calm openings' });
    const current = within(heading.closest('article')!);
    expect(current.getByText('12,000 views')).toBeVisible();
    const longMetricValue = current.getByText('123 average concurrent viewers across the entire broadcast window');
    expect(getComputedStyle(longMetricValue).overflowWrap).toBe('anywhere');
    expect(current.getByText('Gameplay')).toBeVisible();
    expect(current.getByText('The creator explains the opening route.')).toBeVisible();
    expect(current.getByText('1:33')).toBeVisible();
    await user.click(current.getByText('Record details', { selector: 'summary' }));
    expect(current.getByText('Source content ID')).toBeVisible();
    expect(current.getByText('immutable-source-id')).toBeVisible();
    expect(current.getByText('Display content ID')).toBeVisible();
    expect(current.getByText('editable-display-id')).toBeVisible();
    await user.click(screen.getByText('About this list', { selector: 'summary' }));
    expect(screen.getByText('Known works are saved records, not a complete viewing or play history.')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Add work' }));
    expect(onEdit).toHaveBeenCalledWith({ kind: 'work' });
    await user.click(screen.getByRole('button', { name: 'Edit Seven calm openings' }));
    expect(onEdit).toHaveBeenCalledWith({ kind: 'work', base: expect.objectContaining({ id: 'work-current' }) });
    expect(screen.queryByRole('button', { name: 'Edit An older review' })).not.toBeInTheDocument();
  });

  it('preserves the prior page on failure and retries the requested offset', async () => {
    const api = apiMock();
    vi.mocked(api.creators.works).mockImplementation(async input => input.offset === 50 ? failure() : ok(page([work()], 0, 51)));
    const { user } = start({ api, initialSection: 'works' });
    await screen.findByRole('heading', { name: 'Seven calm openings' });
    await user.click(screen.getByRole('button', { name: 'Next works' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The works could not be loaded');
    expect(screen.getByRole('heading', { name: 'Seven calm openings' })).toBeVisible();
    expect(screen.getByText('1–1 of 51')).toBeVisible();
    vi.mocked(api.creators.works).mockResolvedValueOnce(ok(page([work({ content_title: 'Last known work' })], 50, 51)));
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Last known work' })).toBeVisible();
    expect(vi.mocked(api.creators.works).mock.lastCall?.[0]).toMatchObject({ offset: 50, limit: 50 });
  });

  it('invalidates editable rows immediately when the same creator is rebound, even if the reload fails', async () => {
    const api = apiMock();
    vi.mocked(api.creators.works).mockResolvedValueOnce(ok(page())).mockResolvedValueOnce(failure('New identity works unavailable'));
    const onEdit = vi.fn(); const onBack = vi.fn();
    const view = render(<CreatorRecord api={api} creator={creator()} onBack={onBack} onEdit={onEdit} initialSection="works"/>);
    await screen.findByRole('button', { name: 'Edit Seven calm openings' });
    view.rerender(<CreatorRecord api={api} creator={creator({ source_identity: { platform: 'x', account_id: 'x-pixel', canonical_url: null, revision: 5 } })} onBack={onBack} onEdit={onEdit} initialSection="works"/>);
    expect(screen.queryByRole('button', { name: 'Edit Seven calm openings' })).not.toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('New identity works unavailable');
    expect(screen.queryByRole('heading', { name: 'Seven calm openings' })).not.toBeInTheDocument();
  });

  it('bounds linked-game reads to unique IDs, caches labels, and reports unavailable games honestly', async () => {
    const api = apiMock();
    vi.mocked(api.creators.works).mockResolvedValue(ok(page([
      work(),
      work({ id: 'work-two', content_title: 'Second video' }),
      work({ id: 'work-three', content_title: 'Third video', game_id: 'missing-game' }),
    ], 0, 3)));
    vi.mocked(api.games.detail).mockImplementation(async id => id === 'game-one'
      ? ok({ id: 'game-one', name: 'Actual linked game' } as never)
      : failure('Game unavailable'));
    start({ api, initialSection: 'works' });
    expect(await screen.findAllByText('Actual linked game')).toHaveLength(2);
    expect(await screen.findByText('Game unavailable')).toBeVisible();
    expect(api.games.detail).toHaveBeenCalledTimes(2);
    expect(api.games.detail).toHaveBeenCalledWith('game-one');
    expect(api.games.detail).toHaveBeenCalledWith('missing-game');
    expect(screen.queryByText('Harbor Tactics')).not.toBeInTheDocument();
  });

  it('ignores stale identity responses and refreshes the active works tab without moving focus', async () => {
    const old = deferred<Result<WorkPage>>(); const api = apiMock();
    vi.mocked(api.creators.works).mockImplementation(async input => input.creatorId === 'creator-one' ? old.promise : ok(page([work({ creator_id: 'creator-two', content_title: 'Current creator work' })])));
    const onEdit = vi.fn(); const onBack = vi.fn();
    const view = render(<CreatorRecord api={api} creator={creator()} onBack={onBack} onEdit={onEdit} initialSection="works" refreshToken={0}/>);
    view.rerender(<CreatorRecord api={api} creator={creator({ id: 'creator-two', source_identity: { platform: 'x', account_id: 'x-two', canonical_url: null, revision: 9 } })} onBack={onBack} onEdit={onEdit} refreshToken={0}/>);
    expect(await screen.findByRole('heading', { name: 'Current creator work' })).toBeVisible();
    await act(async () => old.resolve(ok(page([work({ content_title: 'Stale work' })]))));
    expect(screen.queryByRole('heading', { name: 'Stale work' })).not.toBeInTheDocument();
    const add = screen.getByRole('button', { name: 'Add work' }); add.focus();
    view.rerender(<CreatorRecord api={api} creator={creator({ id: 'creator-two', revision: 9, source_identity: { platform: 'x', account_id: 'x-two', canonical_url: null, revision: 9 } })} onBack={onBack} onEdit={onEdit} initialSection="profile" refreshToken={1}/>);
    await waitFor(() => expect(api.creators.works).toHaveBeenCalledTimes(3));
    expect(screen.getByRole('button', { name: 'Known works' })).toHaveAttribute('aria-expanded', 'true');
    expect(add).toHaveFocus();
  });

  it('resets paging when explicitly including prior identities', async () => {
    const api = apiMock(); vi.mocked(api.creators.works).mockResolvedValue(ok(page([work()], 0, 51)));
    const { user } = start({ api, initialSection: 'works' });
    await screen.findByRole('heading', { name: 'Seven calm openings' });
    await user.click(screen.getByRole('button', { name: 'Next works' }));
    await waitFor(() => expect(vi.mocked(api.creators.works).mock.lastCall?.[0].offset).toBe(50));
    await user.click(screen.getByRole('checkbox', { name: 'Include previous identities' }));
    await waitFor(() => expect(vi.mocked(api.creators.works).mock.lastCall?.[0]).toEqual({ creatorId: 'creator-one', includePreviousIdentity: true, limit: 50, offset: 0 }));
  });
});
