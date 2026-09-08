// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { Result } from '../src/shared/bridge';
import type { CandidatePage } from '../src/shared/match';
import type { SavedSetPage, SavedSetsAPI, SavedSetView } from '../src/shared/savedSets';
import { SavedSetPicker, SavedSetResults } from '../src/renderer/components/match/SavedSetBrowser';
import { candidateFixture } from './match-api-mock';
import { ACTIVITY_ID } from './match-fixtures';
import { savedSetFixture, SET_ID } from './saved-set-fixtures';

const ok = <T,>(data: T): Result<T> => ({ ok: true, data });
const error = (message: string): Result<never> => ({ ok: false, error: { code: 'network_error', message, retryable: true } });
const SECOND_SET_ID = '789abcde-789a-489a-889a-789abcdef012';
const THIRD_SET_ID = '89abcdef-89ab-49ab-89ab-89abcdef0123';
const secondSet = (): SavedSetView => ({ ...savedSetFixture(), id: SECOND_SET_ID, name: 'Second list' });
function apiMock(): SavedSetsAPI {
  return {
    list: vi.fn(async () => ok({ items: [savedSetFixture()], total: 1, offset: 0, limit: 50 })),
    detail: vi.fn(async () => ok(savedSetFixture())),
    results: vi.fn(async () => ok({ items: [candidateFixture(1)], total: 1, offset: 0, limit: 100 })),
    create: vi.fn(async () => ok(savedSetFixture())),
  };
}
afterEach(cleanup);

it('loads the compact picker only while expanded and active, retaining the prior page for exact retry', async () => {
  const api = apiMock();
  vi.mocked(api.list).mockImplementation(async input => input.offset === 50
    ? error('Saved lists interrupted')
    : ok({ items: [savedSetFixture()], total: 51, offset: 0, limit: 50 }));
  const onOpen = vi.fn();
  const view = render(<SavedSetPicker api={api} activityId={ACTIVITY_ID} active={false} selectedId={SET_ID} onOpen={onOpen} />);
  const user = userEvent.setup();

  await user.click(screen.getByText('Saved lists'));
  expect(api.list).not.toHaveBeenCalled();
  view.rerender(<SavedSetPicker api={api} activityId={ACTIVITY_ID} active selectedId={SET_ID} onOpen={onOpen} />);
  await screen.findByRole('button', { name: 'Open Launch shortlist' });
  expect(api.list).toHaveBeenLastCalledWith({ activityId: ACTIVITY_ID, offset: 0, limit: 50 });
  expect(screen.getByRole('button', { name: 'Open Launch shortlist' })).toHaveAttribute('aria-current', 'true');
  expect(screen.getByText('1–1 of 51 saved lists')).toBeVisible();

  await user.click(screen.getByRole('button', { name: 'Next saved lists' }));
  await screen.findByText('Saved lists interrupted');
  expect(screen.getByRole('button', { name: 'Open Launch shortlist' })).toBeVisible();
  expect(screen.getByText('1–1 of 51 saved lists')).toBeVisible();
  vi.mocked(api.list).mockResolvedValueOnce(ok({ items: [secondSet()], total: 51, offset: 50, limit: 50 }));
  await user.click(screen.getByRole('button', { name: 'Try again' }));
  await user.click(await screen.findByRole('button', { name: 'Open Second list' }));
  expect(api.list).toHaveBeenLastCalledWith({ activityId: ACTIVITY_ID, offset: 50, limit: 50 });
  expect(onOpen).toHaveBeenCalledExactlyOnceWith(SECOND_SET_ID);
  expect(api.create).not.toHaveBeenCalled();
});

it('reads validated metadata and 100-row result prefixes with saved-set-specific counts and controls', async () => {
  const api = apiMock();
  const members = Array.from({ length: 101 }, (_, index) => candidateFixture(index + 1));
  const metadata = { ...savedSetFixture(), candidate_ids: members.map(item => item.id), count: 101 };
  vi.mocked(api.detail).mockResolvedValue(ok(metadata));
  vi.mocked(api.results).mockImplementation(async input => input.offset === 0
    ? ok({ items: members.slice(0, 100), total: 101, offset: 0, limit: 100 })
    : ok({ items: members.slice(100), total: 101, offset: 100, limit: 100 }));
  const onMetadata = vi.fn(), onOriginal = vi.fn(), onOpenCreator = vi.fn();
  const view = render(<SavedSetResults api={api} id={SET_ID} activityId={ACTIVITY_ID} active onMetadata={onMetadata} onOriginal={onOriginal} onOpenCreator={onOpenCreator} />);
  const user = userEvent.setup();

  expect(await screen.findByRole('heading', { name: 'Launch shortlist' })).toBeVisible();
  expect(screen.getByText('101 saved')).toBeVisible();
  expect(screen.getByText('101 matching')).toBeVisible();
  expect(api.detail).toHaveBeenCalledExactlyOnceWith(SET_ID);
  expect(api.results).toHaveBeenLastCalledWith({ id: SET_ID, evidence: 'all', sort: 'relevance', offset: 0, limit: 100 });
  expect(onMetadata).toHaveBeenCalledExactlyOnceWith(metadata);

  await user.selectOptions(screen.getByLabelText('Order'), 'followers');
  await waitFor(() => expect(api.results).toHaveBeenLastCalledWith({ id: SET_ID, evidence: 'all', sort: 'followers', offset: 0, limit: 100 }));
  await user.click(screen.getByRole('button', { name: 'Load more candidates' }));
  await screen.findByRole('heading', { name: 'Creator 101' });
  expect(api.results).toHaveBeenLastCalledWith({ id: SET_ID, evidence: 'all', sort: 'followers', offset: 100, limit: 100 });
  await user.click(screen.getAllByRole('button', { name: 'View creator' })[0]);
  expect(onOpenCreator).toHaveBeenCalledWith(members[0].creator_id, 'overview');
  await user.click(screen.getByRole('button', { name: 'Original search' }));
  expect(onOriginal).toHaveBeenCalledOnce();

  const callsBeforeHide = vi.mocked(api.results).mock.calls.length;
  view.rerender(<SavedSetResults api={api} id={SET_ID} activityId={ACTIVITY_ID} active={false} onMetadata={() => { throw new Error('stale callback'); }} onOriginal={onOriginal} onOpenCreator={onOpenCreator} />);
  expect(screen.getByLabelText('Order')).toHaveValue('followers');
  view.rerender(<SavedSetResults api={api} id={SET_ID} activityId={ACTIVITY_ID} active onMetadata={onMetadata} onOriginal={onOriginal} onOpenCreator={onOpenCreator} />);
  await waitFor(() => expect(api.results).toHaveBeenCalledTimes(callsBeforeHide + 2));
  expect(api.results).toHaveBeenLastCalledWith({ id: SET_ID, evidence: 'all', sort: 'followers', offset: 100, limit: 100 });
  expect(screen.getByRole('heading', { name: 'Creator 101' })).toBeVisible();
  expect(api.create).not.toHaveBeenCalled();
});

it('keeps prior results honest while a new filter fails, disables further paging, and retries that filter', async () => {
  const api = apiMock();
  let finish!: (value: Result<CandidatePage>) => void;
  vi.mocked(api.results).mockImplementation(input => input.evidence === 'none'
    ? new Promise(resolve => { finish = resolve; })
    : Promise.resolve(ok({ items: [candidateFixture(1)], total: 2, offset: 0, limit: 100 })));
  render(<SavedSetResults api={api} id={SET_ID} activityId={ACTIVITY_ID} active onMetadata={() => {}} onOriginal={() => {}} onOpenCreator={() => {}} />);
  const user = userEvent.setup();
  await screen.findByRole('heading', { name: 'Creator 1' });
  await user.selectOptions(screen.getByLabelText('Evidence'), 'none');
  expect(screen.getByRole('heading', { name: 'Creator 1' })).toBeVisible();
  expect(screen.getByText('Refreshing · 1 previous saved result')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Load more candidates' })).not.toBeInTheDocument();
  finish(error('Filtered saved results interrupted'));
  await screen.findByText('Filtered saved results interrupted');
  expect(screen.getByText('Results unavailable · 1 previous saved result')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Load more candidates' })).not.toBeInTheDocument();

  vi.mocked(api.results).mockResolvedValueOnce(ok({ items: [], total: 0, offset: 0, limit: 100 }));
  await user.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByRole('heading', { name: 'No candidates found' });
  expect(api.results).toHaveBeenLastCalledWith({ id: SET_ID, evidence: 'none', sort: 'relevance', offset: 0, limit: 100 });
  expect(screen.getByText('0 matching')).toBeVisible();
  expect(api.create).not.toHaveBeenCalled();
});

it('fences late result errors after an ID switch and rejects out-of-activity metadata before callbacks or results', async () => {
  const api = apiMock();
  let finishOld!: (value: Result<CandidatePage>) => void;
  const oldPending = new Promise<Result<CandidatePage>>(resolve => { finishOld = resolve; });
  const metadataA = savedSetFixture();
  const metadataB = { ...secondSet(), activity_id: ACTIVITY_ID };
  const metadataC = { ...savedSetFixture(), id: THIRD_SET_ID, name: 'Wrong activity', activity_id: '99999999-9999-4999-8999-999999999999' };
  vi.mocked(api.detail).mockImplementation(async id => ok(id === SET_ID ? metadataA : id === SECOND_SET_ID ? metadataB : metadataC));
  vi.mocked(api.results).mockImplementation(input => input.id === SET_ID && input.evidence === 'none'
    ? oldPending
    : Promise.resolve(ok({ items: [candidateFixture(input.id === SECOND_SET_ID ? 2 : 1)], total: 1, offset: 0, limit: 100 })));
  const onMetadata = vi.fn();
  const props = { api, activityId: ACTIVITY_ID, active: true, onMetadata, onOriginal: vi.fn(), onOpenCreator: vi.fn() };
  const view = render(<SavedSetResults {...props} id={SET_ID} />);
  const user = userEvent.setup();
  await screen.findByRole('heading', { name: 'Creator 1' });
  await user.selectOptions(screen.getByLabelText('Evidence'), 'none');
  view.rerender(<SavedSetResults {...props} id={SECOND_SET_ID} />);
  expect(await screen.findByRole('heading', { name: 'Second list' })).toBeVisible();
  expect(await screen.findByRole('heading', { name: 'Creator 2' })).toBeVisible();
  finishOld(error('Late old-set failure'));
  await waitFor(() => expect(screen.queryByText('Late old-set failure')).not.toBeInTheDocument());
  expect(screen.getByRole('heading', { name: 'Second list' })).toBeVisible();

  view.rerender(<SavedSetResults {...props} id={THIRD_SET_ID} />);
  await screen.findByText('This saved list does not belong to the current activity.');
  expect(onMetadata).not.toHaveBeenCalledWith(metadataC);
  expect(api.results).not.toHaveBeenCalledWith(expect.objectContaining({ id: THIRD_SET_ID }));
  expect(api.create).not.toHaveBeenCalled();
});
