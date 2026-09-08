import { describe, expect, it, vi } from 'vitest';
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import type { CreatorListInput } from '../src/shared/creators';
import { creatorFixture, CREATOR_ID } from './creator-fixtures';

const connection = { serviceUrl: 'http://127.0.0.1:18090', key: 'RAW_SECRET' };
const page = (creator = creatorFixture()) => ({ items: [creator], total: 1, offset: 0, limit: 50 });

describe('Creator Library query options', () => {
  it('sends plural OR filters as repeated keys through the authenticated transport', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(page()));
    const client = new CreatorClient(input => authenticatedCreatorRequest(fetcher, connection, input));

    await client.list({
      query: 'cozy', platform: 'x', language: 'English', platforms: ['youtube', 'twitch'],
      languages: ['en', '日本語'], sort: 'followers', onlyCollection: true, offset: 0, limit: 50,
    } as unknown as CreatorListInput);

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0][0]).toBe(
      'http://127.0.0.1:18090/api/v2/library/creators?query=cozy&language=English&only_collection=true&platform=x&platforms=youtube&platforms=twitch&languages=en&languages=%E6%97%A5%E6%9C%AC%E8%AA%9E&sort=followers&offset=0&limit=50',
    );
  });

  it.each([
    { platforms: ['youtube', 'x', 'twitch', 'instagram', 'youtube'] },
    { platforms: ['youtube', 'threads'] },
    { platforms: 'youtube' },
    { languages: Array.from({ length: 31 }, (_, index) => `language-${index}`) },
    { languages: [''] },
    { languages: ['x'.repeat(256)] },
    { languages: 'English' },
    { sort: 'game_fit' },
    { mystery: true },
  ])('rejects invalid list input before authenticated fetch: %j', async invalid => {
    const fetcher = vi.fn();
    const client = new CreatorClient(input => authenticatedCreatorRequest(fetcher, connection, input));
    await expect(client.list(invalid as unknown as CreatorListInput)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    { platforms: ['youtube', 'threads'] },
    { platforms: ['youtube', 'x', 'twitch', 'instagram', 'youtube'] },
    { languages: [''] },
    { languages: ['x'.repeat(256)] },
    { sort: 'game_fit' },
  ])('rejects invalid raw plural query values before fetch: %j', async query => {
    const fetcher = vi.fn();
    await expect(authenticatedCreatorRequest(fetcher, connection, {
      method: 'GET', path: '/api/v2/library/creators', query,
    } as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('Creator Library public summaries', () => {
  it('accepts strict current-identity summaries and leaves compatible absent fields absent', async () => {
    const enriched = {
      ...creatorFixture(),
      created_at: '2026-09-01T10:00:00Z',
      updated_at: null,
      latest_published_at: '2026-09-07T11:00:00+08:00',
      recent_works: [{
        id: '55555555-5555-4555-8555-555555555555', work_name: 'Recorded title', content_title: null,
        source_url: 'https://example.com/watch/1', published_at: null, content_type: 'video',
      }],
      active_email_count: 2,
      contact_status: 'available' as const,
    };
    const request = vi.fn().mockResolvedValueOnce(page(enriched)).mockResolvedValueOnce(creatorFixture());
    const client = new CreatorClient(request);

    expect((await client.list({})).items[0]).toEqual(enriched);
    const compatible = await client.detail(CREATOR_ID);
    expect(Object.hasOwn(compatible, 'created_at')).toBe(false);
    expect(Object.hasOwn(compatible, 'recent_works')).toBe(false);
    expect(Object.hasOwn(compatible, 'active_email_count')).toBe(false);
    expect(Object.hasOwn(compatible, 'contact_status')).toBe(false);
  });

  it.each([
    (value: Record<string, unknown>) => { value.raw_secret = 'RAW_SECRET'; },
    (value: Record<string, unknown>) => { value.created_at = '2026-02-30T00:00:00Z'; },
    (value: Record<string, unknown>) => { value.active_email_count = -1; },
    (value: Record<string, unknown>) => { value.contact_status = 'qualified'; },
    (value: Record<string, unknown>) => { value.recent_works = Array.from({ length: 4 }, () => ({ id: CREATOR_ID, work_name: null, content_title: null, source_url: null, published_at: null, content_type: 'video' })); },
    (value: Record<string, unknown>) => { value.recent_works = [{ id: 'not-an-id', work_name: null, content_title: null, source_url: null, published_at: null, content_type: 'video' }]; },
    (value: Record<string, unknown>) => { value.recent_works = [{ id: CREATOR_ID, work_name: null, content_title: null, source_url: null, published_at: 'yesterday', content_type: 'video' }]; },
    (value: Record<string, unknown>) => { value.recent_works = [{ id: CREATOR_ID, work_name: null, content_title: null, source_url: null, published_at: null, content_type: 'video', raw_secret: 'RAW_SECRET' }]; },
  ])('rejects malformed or unknown summary fields without exposing the response', async mutate => {
    const value = creatorFixture() as unknown as Record<string, unknown>;
    mutate(value);
    try {
      await new CreatorClient(vi.fn().mockResolvedValue(value)).detail(CREATOR_ID);
      throw new Error('expected rejection');
    } catch (error) {
      expect(error).toMatchObject({ code: 'invalid_response' });
      expect(String(error)).not.toContain('RAW_SECRET');
    }
  });
});
