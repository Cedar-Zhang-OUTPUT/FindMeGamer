import { describe, expect, it, vi } from 'vitest';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';

const connection = { serviceUrl: 'https://service.example', key: 'PRIVATE' };

describe('collection settings transport', () => {
  it('sends exact GET and PUT requests without credentials, cookies, redirects or idempotency', async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response('{"items":[]}'));
    await authenticatedSettingsRequest(fetcher, connection, { method: 'GET', path: '/api/v1/settings/collection' });
    expect(fetcher).toHaveBeenLastCalledWith('https://service.example/api/v1/settings/collection', expect.objectContaining({
      method: 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store',
      headers: expect.not.objectContaining({ Cookie: expect.anything(), 'Idempotency-Key': expect.anything() }),
    }));

    await authenticatedSettingsRequest(fetcher, connection, { method: 'PUT', path: '/api/v1/settings/collection/x', body: { enabled: false } });
    const options = fetcher.mock.calls.at(-1)?.[1];
    expect(fetcher).toHaveBeenLastCalledWith('https://service.example/api/v1/settings/collection/x', expect.objectContaining({ method: 'PUT', body: '{"enabled":false}' }));
    expect(options.headers).not.toHaveProperty('Idempotency-Key');
    expect(options).not.toHaveProperty('credentials', 'include');
  });

  it('rejects arbitrary platforms, paths, fields, methods and non-boolean values before HTTP', async () => {
    const fetcher = vi.fn();
    const invalid = [
      { method: 'GET', path: '/api/v1/settings/collection/youtube' },
      { method: 'GET', path: '/api/v1/settings/collection?platform=youtube' },
      { method: 'POST', path: '/api/v1/settings/collection/youtube', body: { enabled: true } },
      { method: 'DELETE', path: '/api/v1/settings/collection/youtube' },
      { method: 'PUT', path: '/api/v1/settings/collection/steam', body: { enabled: true } },
      { method: 'PUT', path: '/api/v1/settings/collection/../youtube', body: { enabled: true } },
      { method: 'PUT', path: '/api/v1/settings/collection/youtube', body: { enabled: 1 } },
      { method: 'PUT', path: '/api/v1/settings/collection/youtube', body: { enabled: false, secret: 'PRIVATE' } },
      { method: 'PUT', path: '/api/v1/settings/collection/youtube', body: { enabled: false }, idempotencyKey: 'not-allowed' },
    ];
    for (const request of invalid) await expect(authenticatedSettingsRequest(fetcher, connection, request as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('sanitizes read and write failures and never automatically repeats a request', async () => {
    for (const request of [
      { method: 'GET', path: '/api/v1/settings/collection' } as const,
      { method: 'PUT', path: '/api/v1/settings/collection/youtube', body: { enabled: false } } as const,
    ]) {
      const http = vi.fn().mockResolvedValue(new Response('{"error":{"code":"PRIVATE","message":"PRIVATE secret"}}', { status: 500 }));
      const httpError = await authenticatedSettingsRequest(http, connection, request).catch(error => error);
      expect(http).toHaveBeenCalledTimes(1);
      expect(httpError).toMatchObject({ code: 'service_error' });
      expect((httpError as Error).message).not.toContain('PRIVATE');

      const network = vi.fn().mockRejectedValue(new Error('PRIVATE secret'));
      const networkError = await authenticatedSettingsRequest(network, connection, request).catch(error => error);
      expect(network).toHaveBeenCalledTimes(1);
      expect(networkError).toMatchObject({ code: 'network_error' });
      expect((networkError as Error).message).not.toContain('PRIVATE');
    }
  });
});
