// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CandidateView, EvaluationResult } from '../src/shared/match';
import { creatorFixture } from './creator-fixtures';
import { CandidateResults, EvaluationResults } from '../src/renderer/components/match/MatchResults';

const candidate = (overrides: Partial<CandidateView> = {}): CandidateView => ({
  id: '21111111-1111-4111-8111-111111111111',
  creator_id: '11111111-1111-4111-8111-111111111111',
  platform: 'youtube',
  account_id: 'UC-frozen',
  account: {
    platform: 'youtube', account_id: 'UC-frozen', profile_url: 'https://youtube.com/channel/UC-frozen',
    display_name: 'Frozen Harbor', handle: '@frozenharbor', description: 'Discovery snapshot description.',
    follower_count: 12500, country: 'CA', location_text: 'Toronto', avatar_url: 'javascript:alert(1)',
    collected_at: '2026-09-08T08:30:00Z', metadata_complete: true,
  },
  creator: { ...creatorFixture('Current Library Harbor'), country_code: 'US', country_name: 'United States', follower_count: 999999 },
  filter_notes: {
    unknown_fields: ['language'], failed_filters: [], pending_country_labels: ['Ontario'],
    evidence_status: 'unverified', contact_available: true,
  },
  identity_revision: 1,
  identity_changed: false,
  selected: false,
  added_at: '2026-09-08T08:31:00Z',
  ...overrides,
});

const evaluation = (overrides: Partial<EvaluationResult> = {}): EvaluationResult => ({
  candidate_id: '21111111-1111-4111-8111-111111111111',
  creator_id: '11111111-1111-4111-8111-111111111111',
  platform: 'youtube',
  account_id: 'UC-frozen',
  name: 'Frozen Harbor',
  status: 'completed',
  fit_group: 'potential_fit',
  match_brief: {
    candidate_id: '21111111-1111-4111-8111-111111111111',
    summary: '<b>Thoughtful strategy coverage with a compatible audience.</b>',
    content_fit: 'Regularly publishes considered strategy-game reviews.',
    audience_fit: 'Audience interests overlap with calm tactical games.',
    limitations: ['No direct current-game record.', 'Audience geography is incomplete.'],
    cited_work_ids: ['41111111-1111-4111-8111-111111111111'],
    confidence: 'supported',
  },
  evidence_status: 'recorded_evidence',
  evidence: [{
    work_id: '41111111-1111-4111-8111-111111111111', source_url: 'https://youtube.com/watch?v=known',
    content_title: 'A recorded strategy review', timestamp_seconds: 93, relation: 'reference_game', status: 'recorded_evidence',
  }],
  needs_enrichment: false,
  stale: false,
  identity_changed: false,
  selected: false,
  sender_watched: false,
  ...overrides,
});

afterEach(cleanup);

describe('CandidateResults', () => {
  it('shows frozen candidate facts at a glance and separates current Library details', async () => {
    const onOpenCreator = vi.fn();
    const user = userEvent.setup();
    render(<CandidateResults candidates={[candidate()]} total={1} loading={false} onLoadMore={() => {}} onOpenCreator={onOpenCreator}/>);
    const card = screen.getByRole('article', { name: 'Frozen Harbor' });
    expect(within(card).getByRole('heading', { name: 'Frozen Harbor' })).toBeVisible();
    expect(within(card).getByText('YouTube')).toBeVisible();
    expect(within(card).getByText('CA')).toBeVisible();
    expect(within(card).getByText('12,500 followers')).toBeVisible();
    expect(within(card).queryByText('999,999 followers')).not.toBeInTheDocument();
    expect(within(card).queryByRole('img')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /select|send/i })).not.toBeInTheDocument();
    const primaryAction = within(card).getByRole('button', { name: 'View creator' });
    expect(primaryAction).toBeVisible();
    await user.click(primaryAction);
    expect(onOpenCreator).toHaveBeenCalledWith(candidate().creator_id, 'overview');
    const details = within(card).getByText('Discovery details', { selector: 'summary' });
    expect(within(card).getByText('Current Library Harbor')).not.toBeVisible();
    await user.click(details);
    expect(within(card).getByText('Current Library Harbor')).toBeVisible();
    const identityRevision = within(card).getByText('Identity revision');
    expect(identityRevision.nextElementSibling).toHaveTextContent('1');
    expect(within(card).getByText('Language')).toBeVisible();
    expect(within(card).getByText('Ontario')).toBeVisible();
    expect(within(card).getByText('Contact available')).toBeVisible();
    expect(within(card).queryByText('Discovery snapshot')).not.toBeInTheDocument();
  });

  it('makes a rebound prominent without presenting the replacement as the candidate', () => {
    const replacement = { ...creatorFixture('Replacement account'), handle: '@replacement', follower_count: 88000 };
    render(<CandidateResults candidates={[candidate({
      account: { platform: 'youtube', account_id: 'UC-old', profile_url: 'https://youtube.com/channel/UC-old', collected_at: '2026-09-08T08:30:00Z', metadata_complete: false },
      account_id: 'UC-old', creator: replacement, identity_changed: true,
    })]} total={1} loading={false} onLoadMore={() => {}} onOpenCreator={() => {}}/>);
    const card = screen.getByRole('article', { name: 'UC-old' });
    expect(within(card).getByText('Account changed')).toBeVisible();
    expect(within(card).getByText('Country unknown')).toBeVisible();
    expect(within(card).getByText('Followers unknown')).toBeVisible();
    expect(within(card).getByText(/result belongs to the discovered account/i)).toBeVisible();
    expect(within(card).getByRole('button', { name: 'View current creator' })).toBeVisible();
    expect(within(card).queryByRole('heading', { name: 'Replacement account' })).not.toBeInTheDocument();
  });

  it('does not invent a replacement when the current Library record is unavailable', async () => {
    const user = userEvent.setup();
    render(<CandidateResults candidates={[candidate({ creator: null, identity_changed: true })]} total={1} loading={false} onLoadMore={() => {}} onOpenCreator={() => {}}/>);
    const card = screen.getByRole('article', { name: 'Frozen Harbor' });
    expect(within(card).queryByText(/replacement/i)).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /View.*creator/ })).not.toBeInTheDocument();
    await user.click(within(card).getByText('Discovery details', { selector: 'summary' }));
    expect(within(card).getByText('Current creator record unavailable.')).toBeVisible();
  });

  it('retains appended candidates while loading and uses the server total for load more', async () => {
    const onLoadMore = vi.fn(); const user = userEvent.setup();
    const view = render(<CandidateResults candidates={[candidate()]} total={3} loading={true} onLoadMore={onLoadMore} onOpenCreator={() => {}}/>);
    expect(screen.getByRole('heading', { name: 'Frozen Harbor' })).toBeVisible();
    expect(screen.getByText('1 of 3 candidates')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Loading more candidates…' })).toBeDisabled();
    view.rerender(<CandidateResults candidates={[candidate()]} total={3} loading={false} onLoadMore={onLoadMore} onOpenCreator={() => {}}/>);
    await user.click(screen.getByRole('button', { name: 'Load more candidates' }));
    expect(onLoadMore).toHaveBeenCalledOnce();
    view.rerender(<CandidateResults candidates={[]} total={0} loading={false} onLoadMore={onLoadMore} onOpenCreator={() => {}}/>);
    expect(screen.getByRole('heading', { name: 'No candidates found' })).toBeVisible();
  });
});

describe('EvaluationResults', () => {
  it('keeps backend order and uses fit groups without scores, ranks, or selection controls', () => {
    const first = evaluation({ candidate_id: 'candidate-potential', name: 'Potential first', fit_group: 'potential_fit' });
    const second = evaluation({ candidate_id: 'candidate-strong', name: 'Strong second', fit_group: 'strong_fit' });
    const { container } = render(<EvaluationResults results={[first, second]} total={2} loading={false} onLoadMore={() => {}} onOpenCreator={() => {}}/>);
    expect(screen.getAllByRole('heading', { level: 3 }).map(node => node.textContent)).toEqual(['Potential first', 'Strong second']);
    expect(screen.getByText('Potential fit')).toBeVisible();
    expect(screen.getByText('Strong fit')).toBeVisible();
    expect(screen.getAllByText('<b>Thoughtful strategy coverage with a compatible audience.</b>')).toHaveLength(2);
    expect(container.querySelector('b')).not.toBeInTheDocument();
    expect(screen.queryByText(/score|top|rank/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /select|send/i })).not.toBeInTheDocument();
  });

  it('keeps reasoning and evidence on demand with truthful evidence and safe citation actions', async () => {
    const onOpenExternal = vi.fn(); const onOpenCreator = vi.fn(); const user = userEvent.setup();
    const result = evaluation({
      stale: true, identity_changed: true, needs_enrichment: true,
      evidence: [
        ...evaluation().evidence,
        { work_id: '42222222-2222-4222-8222-222222222222', source_url: 'javascript:alert(1)', content_title: null, timestamp_seconds: null, relation: 'related_content', status: 'metadata_only' },
      ],
    });
    render(<EvaluationResults results={[result]} total={1} loading={false} onLoadMore={() => {}} onOpenCreator={onOpenCreator} onOpenExternal={onOpenExternal}/>);
    const card = screen.getByRole('article', { name: 'Frozen Harbor' });
    expect(within(card).getByText('Recorded evidence · sender viewing not confirmed')).toBeVisible();
    expect(within(card).getByText('Outdated')).toBeVisible();
    expect(within(card).getByText('Account changed')).toBeVisible();
    expect(within(card).getByText('Needs enrichment')).toBeVisible();
    expect(within(card).getByText(/evaluation describes the frozen account UC-frozen, not the current Library identity/i)).toBeVisible();
    expect(within(card).getByText('Regularly publishes considered strategy-game reviews.')).not.toBeVisible();
    await user.click(within(card).getByText('Fit and evidence', { selector: 'summary' }));
    expect(within(card).getByText('Regularly publishes considered strategy-game reviews.')).toBeVisible();
    expect(within(card).getByText('No direct current-game record.')).toBeVisible();
    expect(within(card).getByText('A recorded strategy review')).toBeVisible();
    expect(within(card).getByText(/Reference game · Recorded evidence · 1:33/)).toBeVisible();
    expect(within(card).getByText('Untitled work record')).toBeVisible();
    expect(within(card).queryByRole('button', { name: 'Open source for Untitled work record' })).not.toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'Open source for A recorded strategy review' }));
    expect(onOpenExternal).toHaveBeenCalledWith('https://youtube.com/watch?v=known');
    expect(within(card).queryByRole('button', { name: 'View known works' })).not.toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'View current creator works' }));
    expect(onOpenCreator).toHaveBeenCalledWith(result.creator_id, 'works');
  });

  it('retains completed rows during loading and renders unavailable and empty states honestly', async () => {
    const onLoadMore = vi.fn(); const user = userEvent.setup();
    const unavailable = evaluation({ match_brief: null, status: 'identity_changed', identity_changed: true, evidence_status: 'unknown', evidence: [] });
    const view = render(<EvaluationResults results={[unavailable]} total={2} loading={true} onLoadMore={onLoadMore} onOpenCreator={() => {}}/>);
    expect(screen.getByRole('heading', { name: 'Frozen Harbor' })).toBeVisible();
    expect(screen.getByText('Evaluation unavailable')).toBeVisible();
    expect(screen.getByText('No recorded evidence')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Loading more evaluations…' })).toBeDisabled();
    view.rerender(<EvaluationResults results={[unavailable]} total={2} loading={false} onLoadMore={onLoadMore} onOpenCreator={() => {}}/>);
    await user.click(screen.getByRole('button', { name: 'Load more evaluations' }));
    expect(onLoadMore).toHaveBeenCalledOnce();
    view.rerender(<EvaluationResults results={[]} total={0} loading={false} onLoadMore={onLoadMore} onOpenCreator={() => {}}/>);
    expect(screen.getByRole('heading', { name: 'No evaluations available' })).toBeVisible();
  });
});
