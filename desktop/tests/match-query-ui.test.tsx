// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { DesktopBridge } from '../src/shared/bridge';
import type { CandidateView } from '../src/shared/match';
import { CandidateQueryControls } from '../src/renderer/components/match/CandidateQueryControls';
import { CandidateResults } from '../src/renderer/components/match/MatchResults';
import { MatchActivity } from '../src/renderer/components/match/MatchActivity';
import { activityFixture, candidateFixture, matchAPIMock, queryFixture } from './match-api-mock';
import { settingsBridgeMock } from './settings-fixtures';

afterEach(cleanup);

it('offers every evidence category and the four user-facing sort choices with an honest count', async () => {
  const onChange = vi.fn(); const user = userEvent.setup();
  render(<CandidateQueryControls value={{ evidence: 'all', sort: 'relevance' }} filteredTotal={3} queryTotal={20} current loading={false} onChange={onChange}/>);
  expect(screen.getByText('3 matching of 20 discovered')).toBeVisible();
  expect(within(screen.getByLabelText('Evidence')).getAllByRole('option').map(option => option.textContent)).toEqual([
    'All evidence', 'Current game', 'Reference games', 'Other recorded content', 'Evidence unknown',
  ]);
  expect(within(screen.getByLabelText('Order')).getAllByRole('option').map(option => option.textContent)).toEqual([
    'Relevance', 'Followers', 'Recently published', 'Recently added',
  ]);
  await user.selectOptions(screen.getByLabelText('Evidence'), 'related_content');
  expect(onChange).toHaveBeenCalledWith({ evidence: 'related_content', sort: 'relevance' });
});

it('shows factual evidence groups without treating other recorded content as game relevance', () => {
  const candidate: CandidateView = {
    ...candidateFixture(1), evidence_groups: ['current_game', 'reference_game', 'related_content'], relevance_status: 'not_evaluated',
  };
  const view = render(<CandidateResults candidates={[candidate]} total={1} loading={false} sort="recent_added" onLoadMore={() => {}} onOpenCreator={() => {}}/>);
  const card = screen.getByRole('article', { name: 'Creator 1' });
  expect(within(card).getByText('Current game evidence')).toBeVisible();
  expect(within(card).getByText('Reference game evidence')).toBeVisible();
  expect(within(card).getByText('Other recorded content')).toBeVisible();
  expect(within(card).queryByText(/not evaluated|never evaluated/i)).not.toBeInTheDocument();
  expect(within(card).queryByText(/verified|played|watched/i)).not.toBeInTheDocument();
  view.rerender(<CandidateResults candidates={[{ ...candidate, evidence_groups: [], relevance_status: 'stale' }]} total={1} loading={false} sort="relevance" onLoadMore={() => {}} onOpenCreator={() => {}}/>);
  expect(within(card).getByText('Evidence unknown')).toBeVisible();
  expect(within(card).getByText('Relevance outdated')).toBeVisible();
});

it('applies candidate controls in Match and disables evaluation while old membership is shown', async () => {
  const match = matchAPIMock();
  let finish!: (value: Awaited<ReturnType<typeof match.candidates>>) => void;
  vi.mocked(match.candidates).mockImplementation(input => input.evidence === 'none'
    ? new Promise(resolve => { finish = resolve; })
    : Promise.resolve({ ok: true, data: { items: [candidateFixture(1)], total: 1, limit: 100, offset: 0 } }));
  const api = { match, settings: settingsBridgeMock().settings } as DesktopBridge;
  const user = userEvent.setup();
  render(<MatchActivity api={api} activityId={activityFixture().id} active onBack={() => {}} onOpenCreator={() => {}}/>);
  const evaluate = await screen.findByRole('button', { name: 'Evaluate 1 loaded' });
  expect(screen.getByText('1 matching of 2 discovered')).toBeVisible();
  await user.selectOptions(screen.getByLabelText('Evidence'), 'none');
  await waitFor(() => expect(match.candidates).toHaveBeenLastCalledWith({ queryId: queryFixture().id, offset: 0, limit: 100, evidence: 'none', sort: 'relevance' }));
  expect(screen.getAllByText(/previous candidate result/i)).toHaveLength(2);
  expect(evaluate).toBeDisabled();
  expect(screen.getByRole('heading', { name: 'Creator 1' })).toBeVisible();
  finish({ ok: true, data: { items: [], total: 0, limit: 100, offset: 0 } });
  await waitFor(() => expect(screen.getByRole('heading', { name: 'No candidates found' })).toBeVisible());
  expect(match.evaluate).not.toHaveBeenCalled();
});
