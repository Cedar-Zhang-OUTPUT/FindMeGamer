import { describe, expect, it, vi } from 'vitest';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';
const connection = { serviceUrl: 'https://service.example', key: 'PRIVATE' };
describe('settings transport', () => {
  it('authenticates only exact settings routes with no redirects, cookies or cache and a timeout', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}'));
    await authenticatedSettingsRequest(fetcher, connection, { method: 'GET', path: '/api/v1/settings/reanalysis' });
    expect(fetcher).toHaveBeenCalledWith('https://service.example/api/v1/settings/reanalysis', expect.objectContaining({ method: 'GET', redirect: 'error', credentials: 'omit', cache: 'no-store', signal: expect.any(AbortSignal), headers: expect.objectContaining({ Authorization: 'Bearer PRIVATE' }) }));
  });
  it('blocks malicious paths, methods, queries and non-whitelisted bodies before HTTP', async () => {
    const fetcher = vi.fn();
    for (const input of [{ method: 'GET', path: '//evil.example' }, { method: 'GET', path: '/api/v1/settings/connections/../steam' }, { method: 'GET', path: '/api/v1/settings/connections/steam?x=1' }, { method: 'DELETE', path: '/api/v1/outreach/smtp' }, { method: 'GET', path: '/api/v1/outreach/smtp', query: {} }, { method: 'PUT', path: '/api/v1/settings/connections/steam', body: { secret: 'x', extra: 'PRIVATE' } }, { method: 'POST', path: '/api/v1/outreach/smtp/test-connection', body: {} }, { method: 'PATCH', path: '/api/v1/settings/reanalysis', body: { game_interval_days: Infinity, creator_interval_days: 1 } }]) await expect(authenticatedSettingsRequest(fetcher, connection, input as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('redacts HTTP and network errors; unknown send delivery is non-retryable', async () => {
    for (const status of [401, 403, 409, 422, 429, 500]) {
      const fetcher = vi.fn().mockResolvedValue(new Response('{"error":{"message":"PRIVATE","code":"PRIVATE"}}', { status }));
      const error = await authenticatedSettingsRequest(fetcher, connection, { method: 'GET', path: '/api/v1/outreach/smtp' }).catch(e => e);
      expect((error as Error).message).not.toContain('PRIVATE');
    }
    for (const fetcher of [vi.fn().mockRejectedValue(new Error('PRIVATE')), vi.fn().mockResolvedValue(new Response('PRIVATE', { status: 500 })), vi.fn().mockResolvedValue(new Response('PRIVATE'))]) {
      const error = await authenticatedSettingsRequest(fetcher, connection, { method: 'POST', path: '/api/v1/outreach/smtp/test-email', body: { recipient: 'a@example.com' } }).catch(e => e);
      expect(error).toMatchObject({ code: 'delivery_outcome_unknown', retryable: false }); expect((error as Error).message).not.toContain('PRIVATE');
    }
  });
  it('bounds response streams and declared lengths', async () => {
    for (const response of [new Response('x'.repeat(65537)), new Response('{}', { headers: { 'content-length': '65537' } })]) await expect(authenticatedSettingsRequest(async () => response, connection, { method: 'GET', path: '/api/v1/outreach/smtp' })).rejects.toMatchObject({ code: 'response_too_large' });
  });
  it('preserves the backend password-required code without echoing its message', async () => {
    await expect(authenticatedSettingsRequest(async () => new Response(JSON.stringify({ error: { code: 'smtp_password_required', message: 'PRIVATE' } }), { status: 409 }), connection, { method: 'PUT', path: '/api/v1/outreach/smtp', body: { host: 'smtp.example.com', port: 587, encryption: 'starttls', username: 'a@example.com', from_name: 'A', reply_to: 'a@example.com', emails_per_minute: 60 } })).rejects.toMatchObject({ code: 'smtp_password_required', retryable: false });
  });
  it('marks non-authentication send server failures as unknown delivery', async () => {
    await expect(authenticatedSettingsRequest(async () => new Response('PRIVATE', { status: 429 }), connection, { method: 'POST', path: '/api/v1/outreach/smtp/test-email', body: { recipient: 'a@example.com' } })).rejects.toMatchObject({ code: 'delivery_outcome_unknown', retryable: false });
  });
});
