// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { DesktopBridge, Result } from '../src/shared/bridge';
import type { CreatorDetail, CreatorPage } from '../src/shared/creators';
import { CreatorLibrary } from '../src/renderer/components/creators/CreatorLibrary';
import { creatorAPIMock } from './creator-api-mock';
import { creatorFixture } from './creator-fixtures';

const ok = <T,>(data: T): Result<T> => ({ ok: true, data });
const page = (items: CreatorDetail[] = [creatorFixture()], offset = 0, total = 51): CreatorPage => ({ items, offset, total, limit: 50 });
const apiMock = () => ({ creators: creatorAPIMock(), openExternal: vi.fn(async () => ok(undefined)) } as unknown as DesktopBridge);
afterEach(cleanup);

it('applies atomic platform/language menus and server ordering without consuming pending search', async () => {
  const api = apiMock();
  vi.mocked(api.creators.list).mockImplementation(async input => ok(page([creatorFixture()], input.offset)));
  render(<CreatorLibrary api={api} active />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Open Creator fixture' });
  expect(api.creators.list).toHaveBeenLastCalledWith({ query: '', platforms: [], languages: [], sort: 'relevance', onlyCollection: false, offset: 0, limit: 50 });

  const search = screen.getByRole('searchbox', { name: 'Search creators' });
  await user.type(search, 'pending search');
  const platformsButton = screen.getByRole('button', { name: 'Platforms: Any' });
  await user.click(platformsButton);
  let dialog = screen.getByRole('dialog', { name: 'Platforms' });
  await user.click(within(dialog).getByRole('checkbox', { name: 'Instagram' }));
  await user.keyboard('{Escape}');
  expect(platformsButton).toHaveFocus();
  expect(api.creators.list).toHaveBeenCalledOnce();

  await user.click(platformsButton);
  dialog = screen.getByRole('dialog', { name: 'Platforms' });
  await user.click(within(dialog).getByRole('checkbox', { name: 'YouTube' }));
  await user.click(within(dialog).getByRole('checkbox', { name: 'Twitch' }));
  await user.click(within(dialog).getByRole('button', { name: 'Apply' }));
  await waitFor(() => expect(api.creators.list).toHaveBeenLastCalledWith({ query: '', platforms: ['youtube', 'twitch'], languages: [], sort: 'relevance', onlyCollection: false, offset: 0, limit: 50 }));
  expect(search).toHaveValue('pending search');

  await user.click(screen.getByRole('button', { name: 'Languages: Any' }));
  dialog = screen.getByRole('dialog', { name: 'Languages' });
  await user.click(within(dialog).getByRole('checkbox', { name: 'English · en' }));
  await user.type(within(dialog).getByRole('textbox', { name: 'Other language' }), 'Klingon');
  await user.click(within(dialog).getByRole('button', { name: 'Add' }));
  await user.click(within(dialog).getByRole('button', { name: 'Apply' }));
  await waitFor(() => expect(api.creators.list).toHaveBeenLastCalledWith({ query: '', platforms: ['youtube', 'twitch'], languages: ['en', 'Klingon'], sort: 'relevance', onlyCollection: false, offset: 0, limit: 50 }));

  await user.selectOptions(screen.getByRole('combobox', { name: 'Sort creators' }), 'followers');
  await waitFor(() => expect(api.creators.list).toHaveBeenLastCalledWith({ query: '', platforms: ['youtube', 'twitch'], languages: ['en', 'Klingon'], sort: 'followers', onlyCollection: false, offset: 0, limit: 50 }));
  expect(screen.getByText('Follower count')).toBeVisible();
  expect(search).toHaveValue('pending search');

  await user.click(screen.getByRole('button', { name: 'Search' }));
  await waitFor(() => expect(api.creators.list).toHaveBeenLastCalledWith({ query: 'pending search', platforms: ['youtube', 'twitch'], languages: ['en', 'Klingon'], sort: 'followers', onlyCollection: false, offset: 0, limit: 50 }));
  await user.click(screen.getByRole('button', { name: 'Next page' }));
  await waitFor(() => expect(api.creators.list).toHaveBeenLastCalledWith({ query: 'pending search', platforms: ['youtube', 'twitch'], languages: ['en', 'Klingon'], sort: 'followers', onlyCollection: false, offset: 50, limit: 50 }));
});

it('shows recorded recent titles and current email availability without claiming gameplay', async () => {
  const api = apiMock();
  const creator = {
    ...creatorFixture(), active_email_count: 2, contact_status: 'available' as const,
    recent_works: [
      { id: '55555555-5555-4555-8555-555555555555', work_name: 'Cozy stream', content_title: null, source_url: null, published_at: null, content_type: 'video' },
      { id: '66666666-6666-4666-8666-666666666666', work_name: null, content_title: 'Update notes', source_url: null, published_at: '2026-09-01T00:00:00Z', content_type: 'post' },
    ],
  };
  vi.mocked(api.creators.list).mockResolvedValue(ok(page([creator], 0, 1)));
  render(<CreatorLibrary api={api} active />);
  const row = (await screen.findByRole('button', { name: 'Open Creator fixture' })).closest('tr')!;
  expect(within(row).getByText('Cozy stream · Update notes')).toBeVisible();
  expect(within(row).getByText('2 active emails')).toBeVisible();
  expect(within(row).queryByText(/gameplay|qualified|watched/i)).not.toBeInTheDocument();
});

it('keeps the prior successful result labeled with its own filters when a new read fails', async () => {
  const api = apiMock();
  vi.mocked(api.creators.list).mockImplementation(async input => input.query === 'cozy'
    ? { ok: false, error: { code: 'network_error', message: 'Search interrupted', retryable: true } }
    : ok(page([creatorFixture('Prior result')], 0, 1)));
  render(<CreatorLibrary api={api} active />);
  const user = userEvent.setup();
  await screen.findByRole('button', { name: 'Open Prior result' });
  await user.type(screen.getByRole('searchbox'), 'cozy');
  await user.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByText('Search interrupted');
  expect(screen.getByRole('button', { name: 'Open Prior result' })).toBeVisible();
  expect(screen.queryByText('Results for “cozy”')).not.toBeInTheDocument();
  expect(screen.getByRole('searchbox')).toHaveValue('cozy');

  vi.mocked(api.creators.list).mockResolvedValueOnce(ok(page([creatorFixture('Cozy result')], 0, 1)));
  await user.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByRole('button', { name: 'Open Cozy result' });
  expect(screen.getByText('Results for “cozy”')).toBeVisible();
});
