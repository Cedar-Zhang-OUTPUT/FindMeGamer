import { describe, expect, it, vi } from 'vitest';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest, exactCandidateQueryOptions, validateMatchRequest } from '../src/main/match-transport';
import { candidateFixture, matchPage, QUERY_ID as Q, EVALUATION_ID as E } from './match-fixtures';

const connection = { serviceUrl: 'https://example.com', key: 'SYNTHETIC_SECRET' };
const path = `/api/v2/discovery/queries/${Q}/results`;

describe('candidate query options boundary', () => {
  it('preserves legacy omission and sends explicit evidence and order only on candidate reads', async () => {
    const request = vi.fn().mockResolvedValue(matchPage(candidateFixture()));
    const client = new MatchClient(request);
    await client.candidates({ queryId: Q });
    await client.candidates({ queryId: Q, offset: 25, limit: 25, evidence: 'reference_game', sort: 'recent_publish' });
    expect(request.mock.calls[0][0]).toEqual({ method: 'GET', path, query: { offset: '0', limit: '50' } });
    expect(request.mock.calls[1][0]).toEqual({ method: 'GET', path, query: { offset: '25', limit: '25', evidence: 'reference_game', sort: 'recent_publish' } });

    expect(exactCandidateQueryOptions({ offset: '0', limit: '100', evidence: 'none', sort: 'followers' }))
      .toEqual({ offset: '0', limit: '100', evidence: 'none', sort: 'followers' });
    expect(() => validateMatchRequest({ method: 'GET', path: `/api/v2/discovery/evaluations/${E}/results`, query: { evidence: 'all' } }))
      .toThrow(expect.objectContaining({ code: 'request_invalid' }));
  });

  it.each([
    { evidence: 'played_game' }, { sort: 'rank' }, { evidence: '' }, { sort: 1 }, { extra: 'all' },
  ])('rejects unsupported candidate query option before the request: %j', async option => {
    const request = vi.fn().mockResolvedValue(matchPage(candidateFixture()));
    await expect(new MatchClient(request).candidates({ queryId: Q, ...option } as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });

  it('serializes the exact validated candidate URL through the authenticated transport', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(matchPage(candidateFixture(), 100)));
    await authenticatedMatchRequest(fetcher, connection, {
      method: 'GET', path, query: { offset: '0', limit: '100', evidence: 'current_game', sort: 'relevance' },
    });
    expect(fetcher.mock.calls[0][0]).toBe(`https://example.com${path}?offset=0&limit=100&evidence=current_game&sort=relevance`);
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store' });
  });

  it('accepts optional evidence metadata without inventing it for older responses', async () => {
    const enriched = { ...candidateFixture(), evidence_groups: ['current_game', 'related_content'], relevance_status: 'stale' };
    const request = vi.fn().mockResolvedValueOnce(matchPage(enriched)).mockResolvedValueOnce(matchPage(candidateFixture()));
    const client = new MatchClient(request);
    const first = await client.candidates({ queryId: Q, evidence: 'all', sort: 'relevance' });
    const second = await client.candidates({ queryId: Q });
    expect(first.items[0]).toMatchObject({ evidence_groups: ['current_game', 'related_content'], relevance_status: 'stale' });
    expect(second.items[0]).not.toHaveProperty('evidence_groups');
    expect(second.items[0]).not.toHaveProperty('relevance_status');
  });

  it.each([
    (item: any) => { item.evidence_groups = ['verified_gameplay']; },
    (item: any) => { item.relevance_status = 'ranked'; },
    (item: any) => { item.evidence_groups = 'current_game'; },
    (item: any) => { item.rank = 1; },
  ])('rejects malformed or invented candidate evidence metadata', async mutate => {
    const item = candidateFixture(); mutate(item);
    await expect(new MatchClient(vi.fn().mockResolvedValue(matchPage(item))).candidates({ queryId: Q }))
      .rejects.toMatchObject({ code: 'invalid_response' });
  });
});
