import { describe, expect, it, vi } from 'vitest';
import { authenticatedGet, authenticatedGameRequest, PublicFailure } from '../src/main/transport';

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

describe('bounded v2 Game transport', () => {
  const connection = { serviceUrl: 'https://workspace.test', key: 'DO-NOT-ECHO-KEY' };
  const id = '21d62c9c-b1a6-4f41-8da9-739c00204c31';
  it('allows only explicit Game GET/POST/PATCH and sends only the create idempotency header', async () => {
    const fetcher = vi.fn(async () => new Response('{}'));
    await authenticatedGameRequest(fetcher, connection, { method: 'GET', path: '/api/v2/library/games', query: { offset: '20', limit: '20' } });
    await authenticatedGameRequest(fetcher, connection, { method: 'POST', path: '/api/v2/library/games', body: { name: 'Game' }, idempotencyKey: 'game-create:123' });
    await authenticatedGameRequest(fetcher, connection, { method: 'PATCH', path: `/api/v2/library/games/${id}`, body: { expected_revision: 3, description: null } });
    const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([, init]) => init.method)).toEqual(['GET', 'POST', 'PATCH']);
    expect(new Headers(calls[1][1].headers).get('Idempotency-Key')).toBe('game-create:123');
    expect(new Headers(calls[2][1].headers).has('Idempotency-Key')).toBe(false);
    expect(JSON.parse(calls[2][1].body as string)).toEqual({ expected_revision: 3, description: null });
    for (const [, init] of calls) expect(init).toMatchObject({ redirect: 'error', credentials: 'omit', cache: 'no-store' });
  });
  it.each([
    { method: 'POST', path: '/api/v1/jobs', body: {}, idempotencyKey: 'new-game-123' },
    { method: 'PATCH', path: '/api/v2/library/games', body: {} },
    { method: 'POST', path: `/api/v2/library/games/${id}`, body: {}, idempotencyKey: 'new-game-123' },
    { method: 'DELETE', path: `/api/v2/library/games/${id}` },
    { method: 'GET', path: '/api/v2/library/creators' },
    { method: 'GET', path: 'https://evil.test' },
    { method: 'GET', path: '/api/v2/library/games', query: { cursor: 'wrong-contract' } },
    { method: 'POST', path: '/api/v2/library/games', body: {}, idempotencyKey: 'bad\r\nheader' },
    { method: 'PATCH', path: `/api/v2/library/games/${id}`, body: {}, headers: { Authorization: 'evil' } },
  ])('rejects a generalized privileged request: %#', async input => {
    const fetcher = vi.fn();
    await expect(authenticatedGameRequest(fetcher, connection, input as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(['game_revision_conflict', 'game_identity_conflict', 'idempotency_key_conflict'])(
    'preserves allowed 409 code %s but never upstream messages/key material', async code => {
      const fetcher = vi.fn(async () => new Response(JSON.stringify({ error: { code, message: 'DO-NOT-ECHO-KEY', retryable: true, correlation_id: id } }), { status: 409 }));
      const error = await authenticatedGameRequest(fetcher, connection, { method: 'POST', path: '/api/v2/library/games', body: { name: 'Game' }, idempotencyKey: 'new-game-123' }).catch(e => e);
      expect(error).toMatchObject({ code, retryable: false, correlationId: id });
      expect((error as PublicFailure).message).not.toContain('DO-NOT-ECHO');
      expect(fetcher).toHaveBeenCalledOnce();
    },
  );
  it('maps unknown 409 codes to a fixed conflict and 422 to actionable validation without raw body', async () => {
    const write = { method: 'PATCH' as const, path: `/api/v2/library/games/${id}`, body: { expected_revision: 1 } };
    const conflict = await authenticatedGameRequest(async () => new Response('{"error":{"code":"DO-NOT-ECHO-KEY","message":"unsafe"}}', { status: 409 }), connection, write).catch(e => e);
    expect(conflict).toMatchObject({ code: 'save_conflict', retryable: false });
    expect((conflict as PublicFailure).message).not.toContain('DO-NOT-ECHO');
    await expect(authenticatedGameRequest(async () => new Response('DO-NOT-ECHO-KEY', { status: 422 }), connection, write)).rejects.toMatchObject({ code: 'request_invalid', retryable: false });
  });
  it.each(['reject', 'bad-json', 'server-error'])('never marks an unknown save result automatically retryable: %s', async mode => {
    const fetcher = vi.fn(async () => {
      if (mode === 'reject') throw Error('DO-NOT-ECHO-KEY');
      return new Response(mode === 'bad-json' ? '<bad>' : '{}', { status: mode === 'server-error' ? 500 : 200 });
    });
    const error = await authenticatedGameRequest(fetcher, connection, { method: 'POST', path: '/api/v2/library/games', body: { name: 'Game' }, idempotencyKey: 'new-game-123' }).catch(e => e);
    expect(error).toMatchObject({ code: 'save_outcome_unknown', retryable: false });
    expect((error as PublicFailure).message).not.toContain('DO-NOT-ECHO');
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it('keeps v1 Creator validation wording independent from the Game editor', async () => {
    const error = await authenticatedGet(async () => new Response('{}', { status: 422 }), connection,
      '/api/v1/profiles/creators').catch(error => error);
    expect(error).toMatchObject({ code: 'request_invalid', retryable: false });
    expect((error as PublicFailure).message).not.toMatch(/game|save/i);
  });
});
