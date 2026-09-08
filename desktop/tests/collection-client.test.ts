import { describe, expect, it, vi } from 'vitest';
import { SettingsClient } from '../src/main/settings-client';
import { collectionSettingsFixture } from './collection-fixtures';

describe('collection settings client', () => {
  it('uses the exact GET and PUT contracts and preserves false', async () => {
    const response = collectionSettingsFixture();
    const request = vi.fn().mockResolvedValue(response);
    const client = new SettingsClient(request);

    expect(await client.collection()).toEqual(response);
    expect(request).toHaveBeenLastCalledWith({ method: 'GET', path: '/api/v1/settings/collection' });
    expect(await client.setCollection({ platform: 'youtube', enabled: false })).toEqual(response);
    expect(request).toHaveBeenLastCalledWith({ method: 'PUT', path: '/api/v1/settings/collection/youtube', body: { enabled: false } });
  });

  it('rejects arbitrary platforms, non-booleans and surplus input before requesting', async () => {
    const request = vi.fn();
    const client = new SettingsClient(request);
    for (const input of [
      { platform: '../youtube', enabled: true },
      { platform: 'steam', enabled: true },
      { platform: 'youtube', enabled: 1 },
      { platform: 'youtube', enabled: 'false' },
      { platform: 'youtube', enabled: false, secret: 'PRIVATE' },
    ]) await expect(client.setCollection(input as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });

  it('projects exact public fields while retaining each independent availability value', async () => {
    const raw = collectionSettingsFixture();
    raw.items = [
      { ...raw.items[0], enabled: false, credentials_configured: true, availability: 'disabled', secret: 'PRIVATE' } as never,
      { ...raw.items[1], enabled: true, credentials_configured: false, availability: 'missing_connection', token: 'PRIVATE' } as never,
      { ...raw.items[2], enabled: true, availability: 'not_implemented', ciphertext: 'PRIVATE' } as never,
      { ...raw.items[3], enabled: true, implemented: true, credentials_configured: true, availability: 'configured_unverified', access_verified: true } as never,
    ];
    const result = await new SettingsClient(async () => ({ ...raw, password: 'PRIVATE' })).collection();

    expect(result).toEqual({ items: [
      { platform: 'youtube', enabled: false, implemented: true, credentials_configured: true, availability: 'disabled' },
      { platform: 'x', enabled: true, implemented: true, credentials_configured: false, availability: 'missing_connection' },
      { platform: 'twitch', enabled: true, implemented: false, credentials_configured: false, availability: 'not_implemented' },
      { platform: 'instagram', enabled: true, implemented: true, credentials_configured: true, availability: 'configured_unverified' },
    ] });
  });

  it('rejects malformed, duplicate, missing and non-strict response fields', async () => {
    const valid = collectionSettingsFixture();
    const malformed: unknown[] = [
      null,
      {},
      { items: {} },
      { items: valid.items.slice(0, 3) },
      { items: [...valid.items.slice(0, 3), { ...valid.items[0] }] },
      { items: valid.items.map((item, index) => index ? item : { ...item, enabled: 1 }) },
      { items: valid.items.map((item, index) => index ? item : { ...item, implemented: 'true' }) },
      { items: valid.items.map((item, index) => index ? item : { ...item, credentials_configured: null }) },
      { items: valid.items.map((item, index) => index ? item : { ...item, availability: 'available' }) },
      { items: valid.items.map((item, index) => index ? item : { ...item, platform: 'steam' }) },
    ];
    for (const value of malformed) {
      await expect(new SettingsClient(async () => value).collection()).rejects.toMatchObject({ code: 'invalid_response', retryable: false });
    }
  });
});
