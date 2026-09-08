import { describe, expect, it, vi } from 'vitest';
import { authenticatedGet, PublicFailure } from '../src/main/transport';

describe('main authenticated network', () => {
  it('uses only a fixed read-only route and excludes cookies and redirects', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [], next_cursor: null })));
    await authenticatedGet(fetcher, { serviceUrl: 'https://workspace.test', key: 'test-key' }, '/api/v1/profiles/games', { query: 'a & b', limit: '50' });
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://workspace.test/api/v1/profiles/games?query=a+%26+b&limit=50');
    expect(init.method).toBe('GET');
    expect(init.redirect).toBe('error');
    expect(init.credentials).toBe('omit');
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer test-key');
  });
  it('cannot turn an IPC argument into an arbitrary privileged URL', async () => {
    const fetcher = vi.fn();
    for (const route of ['https://evil.test', '//evil.test', '/api/v1/jobs', '/api/v1/profiles/games/../../settings', '/api/v1/profiles/games?x=y']) {
      await expect(authenticatedGet(fetcher, { serviceUrl: 'https://workspace.test', key: 'test-key' }, route)).rejects.toBeInstanceOf(PublicFailure);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('keeps bad authentication distinct without exposing echoed credentials', async () => {
    const fetcher = vi.fn(async () => new Response('test-key in server error', { status: 401 }));
    const error = await authenticatedGet(fetcher, { serviceUrl: 'https://workspace.test', key: 'test-key' }, '/api/v1/session').catch(e => e);
    expect(error).toBeInstanceOf(PublicFailure);
    expect((error as PublicFailure).code).toBe('workspace_key_invalid');
    expect((error as PublicFailure).message).not.toContain('test-key');
  });
  it('reports bad JSON and oversized payloads as failures rather than empty libraries', async () => {
    for (const response of [new Response('<html>proxy login</html>'), new Response('{}', { headers: { 'content-length': '99999999' } })]) {
      await expect(authenticatedGet(async () => response, { serviceUrl: 'https://workspace.test', key: 'k' }, '/api/v1/session')).rejects.toBeInstanceOf(PublicFailure);
    }
  });
  it('sanitizes transport errors, including URLs and key material', async () => {
    const error = await authenticatedGet(async () => { throw Error('request header test-key'); }, { serviceUrl: 'https://workspace.test', key: 'test-key' }, '/api/v1/session').catch(e => e);
    expect(error).toBeInstanceOf(PublicFailure);
    expect((error as PublicFailure).message).not.toContain('test-key');
    expect((error as PublicFailure).retryable).toBe(true);
  });
});
