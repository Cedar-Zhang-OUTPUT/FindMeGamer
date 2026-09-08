import { describe, expect, it, vi } from 'vitest';
import { SettingsClient } from '../src/main/settings-client';
const status = { configured: true, last_test_status: null, last_tested_at: null };
const smtp = { ...status, host: 'smtp.example.com', port: 465, encryption: 'tls', username: 'a@example.com', from_name: 'A', reply_to: 'a@example.com', emails_per_minute: 10 };
const input = { host: 'smtp.example.com', port: 465, encryption: 'tls' as const, username: 'a@example.com', fromName: 'A', replyTo: 'a@example.com', emailsPerMinute: 10 };
describe('SettingsClient', () => {
  it('maps service reads, replacement and stored probes without exposing surplus credentials', async () => {
    const request = vi.fn().mockResolvedValue({ ...status, secret: 'PRIVATE', ciphertext: 'PRIVATE' });
    const client = new SettingsClient(request);
    for (const service of ['steam', 'youtube', 'deepseek', 'google_ai', 'x'] as const) {
      expect(await client.connection(service)).toEqual({ configured: true, lastTestStatus: null, lastTestedAt: null });
      await client.replaceConnection({ service, secret: ' PRIVATE ' });
      expect(request).toHaveBeenLastCalledWith({ method: 'PUT', path: `/api/v1/settings/connections/${service}`, body: { secret: ' PRIVATE ' } });
      await client.testConnection(service);
      expect(request).toHaveBeenLastCalledWith({ method: 'POST', path: `/api/v1/settings/connections/${service}` });
    }
  });
  it('maps reanalysis and SMTP, omitting an unchanged password', async () => {
    const request = vi.fn().mockResolvedValue({ game_interval_days: 90, creator_interval_days: 30 });
    const client = new SettingsClient(request);
    expect(await client.saveReanalysis({ gameIntervalDays: 90, creatorIntervalDays: 30 })).toEqual({ gameIntervalDays: 90, creatorIntervalDays: 30 });
    expect(request).toHaveBeenLastCalledWith({ method: 'PATCH', path: '/api/v1/settings/reanalysis', body: { game_interval_days: 90, creator_interval_days: 30 } });
    request.mockResolvedValue({ ...smtp, password: 'PRIVATE' });
    expect(await client.saveSMTP(input)).toEqual({ configured: true, host: 'smtp.example.com', port: 465, encryption: 'tls', username: 'a@example.com', fromName: 'A', replyTo: 'a@example.com', emailsPerMinute: 10, lastTestStatus: null, lastTestedAt: null });
    expect(request).toHaveBeenLastCalledWith({ method: 'PUT', path: '/api/v1/outreach/smtp', body: { host: 'smtp.example.com', port: 465, encryption: 'tls', username: 'a@example.com', from_name: 'A', reply_to: 'a@example.com', emails_per_minute: 10 } });
  });
  it('validates finite integer ranges, service names, email and surplus input before requesting', async () => {
    const request = vi.fn(); const client = new SettingsClient(request);
    for (const value of [0, 91, NaN, Infinity, 1.5]) await expect(client.saveReanalysis({ gameIntervalDays: value, creatorIntervalDays: 1 })).rejects.toMatchObject({ code: 'request_invalid' });
    for (const value of [0, 31, NaN]) await expect(client.saveReanalysis({ gameIntervalDays: 1, creatorIntervalDays: value })).rejects.toMatchObject({ code: 'request_invalid' });
    for (const patch of [{ port: 65536 }, { port: 0 }, { emailsPerMinute: 61 }, { encryption: 'ssl' }, { password: '' }, { host: 'https://bad' }, { username: 'bad' }, { fromName: 'bad\r\n' }, { secret: 'PRIVATE' }]) await expect(client.saveSMTP({ ...input, ...patch } as never)).rejects.toMatchObject({ code: 'request_invalid' });
    await expect(client.connection('../steam' as never)).rejects.toMatchObject({ code: 'request_invalid' });
    await expect(client.sendTestEmail({ recipient: 'bad' })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it('rejects malformed responses and treats uncertain sends as non-retryable unknown delivery', async () => {
    const request = vi.fn().mockResolvedValue({ ...status, configured: 'PRIVATE' }); const client = new SettingsClient(request);
    await expect(client.connection('steam')).rejects.toMatchObject({ code: 'invalid_response' });
    await expect(client.sendTestEmail({ recipient: 'a@example.com' })).rejects.toMatchObject({ code: 'delivery_outcome_unknown', retryable: false });
    request.mockRejectedValue(new Error('PRIVATE'));
    await expect(client.sendTestEmail({ recipient: 'a@example.com' })).rejects.toMatchObject({ code: 'delivery_outcome_unknown', retryable: false });
  });
  it('maps probe and send results including failure without promising non-delivery', async () => {
    const request = vi.fn().mockResolvedValue({ succeeded: false, last_test_status: 'failure', last_tested_at: '2026-09-08T00:00:00Z', password: 'PRIVATE' }); const client = new SettingsClient(request);
    expect(await client.testSMTP()).toEqual({ succeeded: false, lastTestStatus: 'failure', lastTestedAt: '2026-09-08T00:00:00Z' });
    expect(request).toHaveBeenLastCalledWith({ method: 'POST', path: '/api/v1/outreach/smtp/test-connection' });
    await client.sendTestEmail({ recipient: ' a@example.com ' });
    expect(request).toHaveBeenLastCalledWith({ method: 'POST', path: '/api/v1/outreach/smtp/test-email', body: { recipient: 'a@example.com' } });
  });
  it('supports globally routable IPv6 SMTP hosts accepted by the backend', async () => {
    const request = vi.fn().mockResolvedValue(smtp); const client = new SettingsClient(request);
    await client.saveSMTP({ ...input, host: '2606:4700:4700::1111', password: ' PRIVATE ' });
    expect(request).toHaveBeenLastCalledWith(expect.objectContaining({ body: expect.objectContaining({ host: '2606:4700:4700::1111', password: 'PRIVATE' }) }));
  });
  it('maps generation changes to unknown delivery and validates response timestamps/ranges', async () => {
    const request = vi.fn().mockRejectedValue(new Error('configuration_changed')); const client = new SettingsClient(request);
    await expect(client.sendTestEmail({ recipient: 'a@example.com' })).rejects.toMatchObject({ code: 'delivery_outcome_unknown', retryable: false });
    request.mockResolvedValue({ ...status, last_tested_at: 'PRIVATE' });
    await expect(client.connection('steam')).rejects.toMatchObject({ code: 'invalid_response' });
    request.mockResolvedValue({ game_interval_days: 1, creator_interval_days: Infinity });
    await expect(client.reanalysis()).rejects.toMatchObject({ code: 'invalid_response' });
    request.mockResolvedValue({ ...smtp, port: 0 });
    await expect(client.smtp()).rejects.toMatchObject({ code: 'invalid_response' });
  });
});
