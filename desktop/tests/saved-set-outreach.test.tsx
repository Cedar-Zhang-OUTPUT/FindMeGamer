// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { Result } from '../src/shared/bridge';
import type { CandidatePage, CandidateView } from '../src/shared/match';
import type { SavedSetsAPI, SavedSetView } from '../src/shared/savedSets';
import {
  SavedSetResults,
  type SavedSetQueryChange,
} from '../src/renderer/components/match/SavedSetBrowser';
import { candidateFixture } from './match-api-mock';
import { ACTIVITY_ID } from './match-fixtures';
import { savedSetFixture, SET_ID } from './saved-set-fixtures';

const SECOND_SET_ID = '789abcde-789a-489a-889a-789abcdef012';
const ok = <T,>(data: T): Result<T> => ({ ok: true, data });

function apiMock(): SavedSetsAPI {
  return {
    list: vi.fn(async () => ok({ items: [], total: 0, offset: 0, limit: 50 })),
    detail: vi.fn(async id => ok({
      ...savedSetFixture(),
      id,
      name: id === SET_ID ? 'Launch shortlist' : 'Second list',
    })),
    results: vi.fn(async input => ok({
      items: [candidateFixture(input.id === SET_ID ? 1 : 2)],
      total: 1,
      offset: input.offset ?? 0,
      limit: input.limit ?? 100,
    })),
    create: vi.fn(async () => ok(savedSetFixture())),
  };
}

const baseProps = (api: SavedSetsAPI) => ({
  api,
  id: SET_ID,
  activityId: ACTIVITY_ID,
  active: true,
  onMetadata: (_set: SavedSetView) => {},
  onOriginal: () => {},
  onOpenCreator: () => {},
});

afterEach(cleanup);

it('offers outreach selection only for an explicit current saved-list read', async () => {
  const api = apiMock();
  const loaded = [candidateFixture(1), candidateFixture(2)];
  let holdRefresh = false;
  let finishRefresh!: (value: Result<CandidatePage>) => void;
  vi.mocked(api.results).mockImplementation(input => {
    if (holdRefresh) return new Promise(resolve => { finishRefresh = resolve; });
    return Promise.resolve(ok({ items: loaded, total: loaded.length, offset: input.offset ?? 0, limit: input.limit ?? 100 }));
  });
  const onToggle = vi.fn(), onSelectLoaded = vi.fn();
  const outreach = { isSelected: vi.fn(() => false), disabled: false, onToggle };
  const props = { ...baseProps(api), outreach, onSelectLoaded };
  const view = render(<SavedSetResults {...props} />);
  const user = userEvent.setup();

  const first = await screen.findByRole('checkbox', { name: 'Select Creator 1 for outreach' });
  expect(onToggle).not.toHaveBeenCalled();
  expect(onSelectLoaded).not.toHaveBeenCalled();
  await user.click(first);
  expect(onToggle).toHaveBeenCalledExactlyOnceWith(loaded[0]);
  await user.click(screen.getByRole('button', { name: 'Select loaded' }));
  expect(onSelectLoaded).toHaveBeenCalledExactlyOnceWith(loaded);

  holdRefresh = true;
  await user.click(screen.getByRole('button', { name: 'Refresh saved list' }));
  await waitFor(() => expect(screen.queryByRole('checkbox', { name: 'Select Creator 1 for outreach' })).not.toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'Select loaded' })).toBeDisabled();
  expect(onToggle).toHaveBeenCalledOnce();
  expect(onSelectLoaded).toHaveBeenCalledOnce();
  finishRefresh(ok({ items: loaded, total: loaded.length, offset: 0, limit: 100 }));
  expect(await screen.findByRole('checkbox', { name: 'Select Creator 1 for outreach' })).toBeEnabled();

  view.rerender(<SavedSetResults {...props} outreach={{ ...outreach, disabled: true }} />);
  expect(screen.getByRole('checkbox', { name: 'Select Creator 1 for outreach' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Select loaded' })).toBeDisabled();
  holdRefresh = false;
  view.rerender(<SavedSetResults {...props} id={SECOND_SET_ID} />);
  expect(await screen.findByRole('heading', { name: 'Second list' })).toBeVisible();
  expect(onToggle).toHaveBeenCalledOnce();
  expect(onSelectLoaded).toHaveBeenCalledOnce();
  expect(api.create).not.toHaveBeenCalled();
});

it('delegates an evidence change with complete stable saved membership, while sorting stays read-only', async () => {
  const api = apiMock();
  const visible = [candidateFixture(1), candidateFixture(2)];
  const membership = Array.from({ length: 101 }, (_, index) => candidateFixture(index + 20));
  vi.mocked(api.results).mockImplementation(async input => {
    if (input.evidence === 'current_game' && input.sort === 'added') {
      const offset = input.offset ?? 0;
      return ok({ items: membership.slice(offset, offset + 100), total: membership.length, offset, limit: input.limit ?? 100 });
    }
    if (input.evidence === 'current_game') {
      return ok({ items: [membership[0]], total: 1, offset: input.offset ?? 0, limit: input.limit ?? 100 });
    }
    return ok({ items: visible, total: visible.length, offset: input.offset ?? 0, limit: input.limit ?? 100 });
  });
  let change: SavedSetQueryChange | undefined;
  const onQueryChange = vi.fn((next: SavedSetQueryChange) => { change = next; });
  render(<SavedSetResults {...baseProps(api)} onQueryChange={onQueryChange} />);
  const user = userEvent.setup();

  await screen.findByRole('heading', { name: 'Creator 1' });
  await user.selectOptions(screen.getByLabelText('Evidence'), 'current_game');
  expect(onQueryChange).toHaveBeenCalledOnce();
  expect(change).toMatchObject({
    next: { evidence: 'current_game', sort: 'relevance' },
    previous: { evidence: 'all', sort: 'relevance' },
    visible,
    current: true,
  });
  expect(screen.getByLabelText('Evidence')).toHaveValue('all');
  expect(api.results).not.toHaveBeenCalledWith(expect.objectContaining({ evidence: 'current_game', sort: 'relevance' }));

  const complete = await change!.read();
  expect(complete).toEqual(membership);
  expect(api.results).toHaveBeenCalledWith({ id: SET_ID, evidence: 'current_game', sort: 'added', offset: 0, limit: 100 });
  expect(api.results).toHaveBeenCalledWith({ id: SET_ID, evidence: 'current_game', sort: 'added', offset: 100, limit: 100 });
  act(() => change!.apply());
  await waitFor(() => expect(screen.getByLabelText('Evidence')).toHaveValue('current_game'));
  expect(api.results).toHaveBeenCalledWith({ id: SET_ID, evidence: 'current_game', sort: 'relevance', offset: 0, limit: 100 });

  await user.selectOptions(screen.getByLabelText('Order'), 'followers');
  await waitFor(() => expect(api.results).toHaveBeenCalledWith({ id: SET_ID, evidence: 'current_game', sort: 'followers', offset: 0, limit: 100 }));
  expect(onQueryChange).toHaveBeenCalledOnce();
  expect(api.create).not.toHaveBeenCalled();
});

it('rejects a late empty membership and ignores its apply after the source saved list changes', async () => {
  const api = apiMock();
  let change: SavedSetQueryChange | undefined;
  let finishMembership!: (value: Result<CandidatePage>) => void;
  const membershipPending = new Promise<Result<CandidatePage>>(resolve => { finishMembership = resolve; });
  vi.mocked(api.results).mockImplementation(input => {
    if (input.id === SET_ID && input.evidence === 'none' && input.sort === 'added') return membershipPending;
    return Promise.resolve(ok({
      items: [candidateFixture(input.id === SET_ID ? 1 : 2)],
      total: 1,
      offset: input.offset ?? 0,
      limit: input.limit ?? 100,
    }));
  });
  const onQueryChange = vi.fn((next: SavedSetQueryChange) => { change = next; });
  const props = { ...baseProps(api), onQueryChange };
  const view = render(<SavedSetResults {...props} />);
  const user = userEvent.setup();

  await screen.findByRole('heading', { name: 'Creator 1' });
  await user.selectOptions(screen.getByLabelText('Evidence'), 'none');
  const staleRead = change!.read();
  view.rerender(<SavedSetResults {...props} id={SECOND_SET_ID} />);
  expect(await screen.findByRole('heading', { name: 'Second list' })).toBeVisible();
  expect(await screen.findByRole('heading', { name: 'Creator 2' })).toBeVisible();
  finishMembership(ok({ items: [], total: 0, offset: 0, limit: 100 }));
  await expect(staleRead).rejects.toMatchObject({ code: 'membership_changed' });

  act(() => change!.apply());
  expect(screen.getByLabelText('Evidence')).toHaveValue('all');
  expect(api.results).not.toHaveBeenCalledWith(expect.objectContaining({ id: SECOND_SET_ID, evidence: 'none' }));
  expect(api.create).not.toHaveBeenCalled();
});
