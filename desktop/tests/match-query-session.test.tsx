// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { CandidatePage } from '../src/shared/match';
import { useMatchSession } from '../src/renderer/components/match/useMatchSession';
import { activityFixture, candidateFixture, evaluationFixture, matchAPIMock, queryFixture } from './match-api-mock';

afterEach(cleanup);
const ok = <T,>(data: T) => ({ ok: true as const, data });

it('sends the explicit UI defaults on every candidate page and refresh', async () => {
  const api = matchAPIMock();
  vi.mocked(api.candidates).mockImplementation(async input => ok({
    items: Array.from({ length: input.offset ? 1 : 100 }, (_, index) => candidateFixture((input.offset ?? 0) + index + 1)),
    total: 101, limit: 100, offset: input.offset ?? 0,
  }));
  const { result } = renderHook(() => useMatchSession(api, activityFixture().id, true));
  await waitFor(() => expect(result.current.candidates).toHaveLength(100));
  expect(api.candidates).toHaveBeenLastCalledWith({ queryId: queryFixture().id, offset: 0, limit: 100, evidence: 'all', sort: 'relevance' });
  act(() => result.current.loadMoreCandidates());
  await waitFor(() => expect(result.current.candidates).toHaveLength(101));
  expect(vi.mocked(api.candidates).mock.calls.slice(-2).map(([input]) => input)).toEqual([
    { queryId: queryFixture().id, offset: 0, limit: 100, evidence: 'all', sort: 'relevance' },
    { queryId: queryFixture().id, offset: 100, limit: 100, evidence: 'all', sort: 'relevance' },
  ]);
  act(() => result.current.refresh());
  await waitFor(() => expect(vi.mocked(api.candidates).mock.calls.length).toBeGreaterThanOrEqual(5));
  expect(vi.mocked(api.candidates).mock.calls.at(-1)?.[0]).toMatchObject({ evidence: 'all', sort: 'relevance' });
});

it('resets the loaded prefix, fences older filters, and leaves frozen evaluations untouched', async () => {
  const api = matchAPIMock();
  vi.mocked(api.evaluations).mockResolvedValue(ok({ items: [evaluationFixture()], total: 1, limit: 50, offset: 0 }));
  let finishCurrent!: (value: ReturnType<typeof ok<CandidatePage>>) => void;
  let finishFollowers!: (value: ReturnType<typeof ok<CandidatePage>>) => void;
  vi.mocked(api.candidates)
    .mockResolvedValueOnce(ok({ items: [candidateFixture(1)], total: 201, limit: 100, offset: 0 }))
    .mockResolvedValueOnce(ok({ items: [candidateFixture(1)], total: 201, limit: 100, offset: 0 }))
    .mockResolvedValueOnce(ok({ items: [candidateFixture(1)], total: 201, limit: 100, offset: 0 }))
    .mockResolvedValueOnce(ok({ items: [candidateFixture(2)], total: 201, limit: 100, offset: 100 }))
    .mockImplementationOnce(() => new Promise(resolve => { finishCurrent = resolve; }))
    .mockImplementationOnce(() => new Promise(resolve => { finishFollowers = resolve; }));
  const { result } = renderHook(() => useMatchSession(api, activityFixture().id, true));
  await waitFor(() => expect(result.current.evaluation?.status).toBe('completed'));
  act(() => result.current.loadMoreCandidates());
  await waitFor(() => expect(result.current.candidates).toHaveLength(2));
  const evaluationReads = vi.mocked(api.evaluation).mock.calls.length;

  act(() => result.current.setCandidateOptions({ evidence: 'current_game', sort: 'relevance' }));
  await waitFor(() => expect(result.current.candidateMembershipCurrent).toBe(false));
  expect(result.current.candidates).toHaveLength(2);
  expect(result.current.candidateOptions).toEqual({ evidence: 'current_game', sort: 'relevance' });
  act(() => result.current.setCandidateOptions({ evidence: 'current_game', sort: 'followers' }));
  await act(async () => finishCurrent(ok({ items: [candidateFixture(3)], total: 1, limit: 100, offset: 0 })));
  expect(result.current.candidates.map(item => item.id)).toEqual([candidateFixture(1).id, candidateFixture(2).id]);
  expect(result.current.candidateMembershipCurrent).toBe(false);
  await act(async () => finishFollowers(ok({ items: [candidateFixture(4)], total: 1, limit: 100, offset: 0 })));
  expect(result.current.candidates.map(item => item.id)).toEqual([candidateFixture(4).id]);
  expect(result.current.candidateMembershipCurrent).toBe(true);
  expect(vi.mocked(api.candidates).mock.calls.at(-1)?.[0]).toEqual({ queryId: queryFixture().id, offset: 0, limit: 100, evidence: 'current_game', sort: 'followers' });
  expect(api.evaluation).toHaveBeenCalledTimes(evaluationReads);
  expect(api.evaluate).not.toHaveBeenCalled();
});

it('restores each query’s candidate options and loaded capacity when history is revisited', async () => {
  const api = matchAPIMock();
  const first = queryFixture();
  const second = { ...queryFixture(), id: '10000000-0000-4000-8000-000000000099' };
  vi.mocked(api.plans).mockResolvedValue(ok({ items: [], total: 0, offset: 0, limit: 50 }));
  vi.mocked(api.activity).mockResolvedValue(ok({ ...activityFixture(), queries: [first, second] }));
  vi.mocked(api.query).mockImplementation(async id => ok(id === first.id ? first : second));
  vi.mocked(api.candidates).mockImplementation(async input => ok({ items: [candidateFixture(input.offset ? 2 : 1)], total: 150, limit: 100, offset: input.offset ?? 0 }));
  const { result } = renderHook(() => useMatchSession(api, activityFixture().id, true));
  await waitFor(() => expect(result.current.query?.id).toBe(first.id));
  act(() => result.current.setCandidateOptions({ evidence: 'reference_game', sort: 'recent_added' }));
  await waitFor(() => expect(result.current.candidateMembershipCurrent).toBe(true));
  act(() => result.current.loadMoreCandidates());
  await waitFor(() => expect(vi.mocked(api.candidates).mock.calls.some(([input]) => input.queryId === first.id && input.offset === 100)).toBe(true));
  act(() => result.current.selectScope({ planId: null, queryId: second.id }));
  await waitFor(() => expect(result.current.query?.id).toBe(second.id));
  expect(result.current.candidateOptions).toEqual({ evidence: 'all', sort: 'relevance' });
  act(() => result.current.selectScope({ planId: null, queryId: first.id }));
  await waitFor(() => expect(result.current.query?.id).toBe(first.id));
  await waitFor(() => expect(vi.mocked(api.candidates).mock.calls.filter(([input]) => input.queryId === first.id).at(-1)?.[0])
    .toEqual({ queryId: first.id, offset: 100, limit: 100, evidence: 'reference_game', sort: 'recent_added' }));
  expect(result.current.candidateOptions).toEqual({ evidence: 'reference_game', sort: 'recent_added' });
});
