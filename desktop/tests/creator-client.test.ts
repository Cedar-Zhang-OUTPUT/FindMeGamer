import { describe, expect, it, vi } from 'vitest';
import { CreatorClient } from '../src/main/creator-client';
import { creatorFixture, contactFixture, workFixture, CREATOR_ID, CONTACT_ID, WORK_ID } from './creator-fixtures';
const path = `/api/v2/library/creators/${CREATOR_ID}`;
const key = 'creator-save-123';

describe('Creator client contract', () => {
  it('projects a partial contact PATCH exactly and returns the full Creator', async () => {
    const result = { ...creatorFixture(), revision: 4 };
    const request = vi.fn().mockResolvedValue(result);
    expect(await new CreatorClient(request).updateContact({ creatorId: CREATOR_ID, contactId: CONTACT_ID, data: { expected_revision: 3, is_active: false } })).toEqual(result);
    expect(request).toHaveBeenCalledExactlyOnceWith({ method: 'PATCH', path: `${path}/contacts/${CONTACT_ID}`, body: { expected_revision: 3, is_active: false } });
  });
  it('uses the complete list filters and default v2 pagination', async () => {
    const request = vi.fn().mockResolvedValue({ items: [creatorFixture()], total: 1, offset: 0, limit: 50 });
    await new CreatorClient(request).list({ platform: 'twitch', language: 'zh', query: 'Test', onlyCollection: true });
    expect(request).toHaveBeenCalledWith({ method: 'GET', path: '/api/v2/library/creators', query: { query: 'Test', platform: 'twitch', language: 'zh', only_collection: 'true', offset: '0', limit: '50' } });
  });
  it('preserves frozen POST payload values and omitted fields', async () => {
    const request = vi.fn().mockResolvedValue(creatorFixture());
    const data = Object.freeze({ platform: 'youtube' as const, profile_url: 'https://example.com', name: '  A name  ' });
    await new CreatorClient(request).create({ data, idempotencyKey: key });
    expect(request.mock.calls[0][0]).toEqual({ method: 'POST', path: '/api/v2/library/creators', body: data, idempotencyKey: key });
  });
  it('routes identity and work operations with protected revisions', async () => {
    const request = vi.fn().mockResolvedValueOnce(creatorFixture()).mockResolvedValue(workFixture());
    const client = new CreatorClient(request);
    const identity = { platform: 'x' as const, account_id: '123', expected_revision: 3, confirmed: true as const };
    await client.rebind({ id: CREATOR_ID, data: identity });
    expect(request).toHaveBeenLastCalledWith({ method: 'PUT', path: `${path}/identity`, body: identity });
    await client.createWork({ creatorId: CREATOR_ID, data: { expected_identity_revision: 1, work_name: 'Work' }, idempotencyKey: key });
    expect(request).toHaveBeenLastCalledWith({ method: 'POST', path: `${path}/works`, body: { expected_identity_revision: 1, work_name: 'Work' }, idempotencyKey: key });
    await client.updateWork({ creatorId: CREATOR_ID, workId: WORK_ID, data: { expected_revision: 1, metrics: [{ name: 'views', value: 0 }] } });
    expect(request).toHaveBeenLastCalledWith({ method: 'PATCH', path: `${path}/works/${WORK_ID}`, body: { expected_revision: 1, metrics: [{ name: 'views', value: 0 }] } });
  });
  it.each([
    { expected_revision: 3, account_id: 'UCprotected' }, { expected_revision: 3, revision: 4 },
    { expected_revision: 3, name: 'x', reset_fields: ['name'] }, { expected_revision: 3, reset_fields: ['favorite'] },
    { expected_revision: -1 }, { expected_revision: 1.5 }, { expected_revision: 3, follower_count: Number.MAX_SAFE_INTEGER + 1 },
    { expected_revision: 3, follower_count_collected_at: '2026-09-08T00:00:00' },
    { expected_revision: 3, profile_url: 'https://secret:token@example.com/' },
    { expected_revision: 3, name: 'x'.repeat(256) }, { expected_revision: 3, country_code: 'usa' },
  ])('rejects invalid Creator input before dispatch: %j', async data => {
    const request = vi.fn();
    await expect(new CreatorClient(request).update({ id: CREATOR_ID, data: data as never })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it('rejects null contact email and preserves explicit reset intent for backend validation', async () => {
    const request = vi.fn().mockResolvedValue(creatorFixture()); const client = new CreatorClient(request);
    await expect(client.updateContact({ creatorId: CREATOR_ID, contactId: CONTACT_ID, data: { expected_revision: 3, email: null } as never })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
    await client.updateContact({ creatorId: CREATOR_ID, contactId: CONTACT_ID, data: { expected_revision: 3, reset_fields: ['email'] } });
    expect(request).toHaveBeenCalledExactlyOnceWith({ method: 'PATCH', path: `${path}/contacts/${CONTACT_ID}`, body: { expected_revision: 3, reset_fields: ['email'] } });
  });
  it.each(['a..b@example.com', '.a@example.com', 'a.@example.com', 'a@-example.com', 'a@example-.com', 'a@example..com', 'a@exam_ple.com'])('rejects malformed contact email before either write dispatch: %s', async email => {
    const request = vi.fn().mockResolvedValue(creatorFixture()); const client = new CreatorClient(request);
    await expect(client.createContact({ creatorId: CREATOR_ID, data: { expected_revision: 3, email }, idempotencyKey: key })).rejects.toMatchObject({ code: 'request_invalid' });
    await expect(client.updateContact({ creatorId: CREATOR_ID, contactId: CONTACT_ID, data: { expected_revision: 3, email } })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it.each(['a..b@example.com', 'a@-example.com', 'a@example..com'])('rejects malformed effective and source/manual response email: %s', async email => {
    for (const layer of ['effective', 'source_fields', 'manual_overrides'] as const) {
      const result = creatorFixture();
      if (layer === 'effective') result.contacts[0].email = email; else result.contacts[0][layer] = { email };
      const client = new CreatorClient(vi.fn().mockResolvedValue(result));
      await expect(client.detail(CREATOR_ID)).rejects.toMatchObject({ code: 'invalid_response' });
      await expect(client.updateContact({ creatorId: CREATOR_ID, contactId: CONTACT_ID, data: { expected_revision: 3, is_active: false } })).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    }
  });
  it.each(['Alice+Tag@Example.COM', "o'connor@example.com", '用户@例子.公司', 'δοκιμή@παράδειγμα.δοκιμή', 'Alice@BÜCHER.de'])('retains valid ASCII and international email spelling: %s', async email => {
    const result = creatorFixture(); result.contacts[0].email = email;
    const request = vi.fn().mockResolvedValue(result); const client = new CreatorClient(request);
    const data = Object.freeze({ expected_revision: 3, email });
    expect((await client.createContact({ creatorId: CREATOR_ID, data, idempotencyKey: key })).contacts[0].email).toBe(email);
    expect(request).toHaveBeenCalledExactlyOnceWith({ method: 'POST', path: `${path}/contacts`, body: data, idempotencyKey: key });
  });
  it.each(['secret', 'source_fields', 'manual_overrides'])('rejects unknown secret-bearing response fields at %s', async field => {
    const result = creatorFixture() as unknown as Record<string, unknown>;
    if (field === 'secret') result.secret = 'RAW_SECRET'; else result[field] = { ...(result[field] as object), secret: 'RAW_SECRET' };
    const client = new CreatorClient(vi.fn().mockResolvedValue(result));
    await expect(client.detail(CREATOR_ID)).rejects.toMatchObject({ code: 'invalid_response' });
    await expect(client.update({ id: CREATOR_ID, data: { expected_revision: 3, name: 'New' } })).rejects.toMatchObject({ code: 'save_outcome_unknown' });
  });
  it('rejects duplicate contacts and inconsistent history flags', async () => {
    const result = creatorFixture(); result.contacts.push(contactFixture());
    const request = vi.fn().mockResolvedValue(result); const client = new CreatorClient(request);
    await expect(client.detail(CREATOR_ID)).rejects.toMatchObject({ code: 'invalid_response' });
    result.contacts.pop(); result.contacts[0].identity_revision = 0;
    await expect(client.detail(CREATOR_ID)).rejects.toMatchObject({ code: 'invalid_response' });
    result.contacts[0].is_current_identity = false;
    expect((await client.detail(CREATOR_ID)).contacts[0].is_current_identity).toBe(false);
  });
  it('checks work ownership, duplicates, finite metrics and previous-identity filtering', async () => {
    const work = workFixture(); const page = { items: [work], total: 1, offset: 0, limit: 50 };
    const request = vi.fn().mockResolvedValue(page); const client = new CreatorClient(request);
    expect((await client.works({ creatorId: CREATOR_ID })).items).toEqual([work]);
    work.is_current_identity = false;
    await expect(client.works({ creatorId: CREATOR_ID })).rejects.toMatchObject({ code: 'invalid_response' });
    expect((await client.works({ creatorId: CREATOR_ID, includePreviousIdentity: true })).items[0].is_current_identity).toBe(false);
    page.items.push(work);
    await expect(client.works({ creatorId: CREATOR_ID, includePreviousIdentity: true })).rejects.toMatchObject({ code: 'invalid_response' });
    page.items.pop(); work.metrics = [{ name: 'views', value: Infinity }];
    await expect(client.works({ creatorId: CREATOR_ID, includePreviousIdentity: true })).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('preserves unknown counts, languages, validation and distinct source evidence', async () => {
    const result = creatorFixture();
    result.profile_url = 'https://example.com/edited'; result.source_fields.profile_url = result.source_identity.canonical_url;
    result.contacts[0].validation_state = 'unknown'; result.contacts[0].source_fields = { email: 'old@example.com', validation_state: 'unverified' };
    const decoded = await new CreatorClient(vi.fn().mockResolvedValue(result)).detail(CREATOR_ID);
    expect(decoded).toEqual(result); expect(decoded.follower_count).toBeNull(); expect(decoded.languages).toEqual([]);
    expect(decoded.profile_url).not.toBe(decoded.source_identity.canonical_url);
    decoded.source_fields.languages.push('zh'); expect(result.source_fields.languages).toEqual([]);
  });
  it.each([
    { expected_identity_revision: 1 }, { expected_identity_revision: 1, work_name: 'work', timestamp_seconds: -1 },
    { expected_identity_revision: 1, work_name: 'work', metrics: [{ name: 'views', value: NaN }] },
    { expected_identity_revision: 1, work_name: 'work', game_id: 'not-a-uuid' },
    { expected_identity_revision: 1, work_name: 'work', published_at: '2026-02-30T00:00:00Z' },
    { expected_identity_revision: 1, work_name: 'work', source_platform: 'youtube' },
  ])('rejects invalid work creation before dispatch: %j', async data => {
    const request = vi.fn();
    await expect(new CreatorClient(request).createWork({ creatorId: CREATOR_ID, data: data as never, idempotencyKey: key })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it('validates createContact, identity confirmation, ownership and complete DTO fields', async () => {
    const request = vi.fn().mockResolvedValue(creatorFixture()); const client = new CreatorClient(request);
    const data = { expected_revision: 3, email: 'new@example.com', purpose: null };
    await client.createContact({ creatorId: CREATOR_ID, data, idempotencyKey: key });
    expect(request).toHaveBeenLastCalledWith({ method: 'POST', path: `${path}/contacts`, body: data, idempotencyKey: key });
    request.mockClear();
    await expect(client.rebind({ id: CREATOR_ID, data: { expected_revision: 3, confirmed: false, platform: 'youtube', account_id: 'UCnew' } as never })).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
    request.mockResolvedValue(workFixture());
    await expect(client.updateWork({ creatorId: CONTACT_ID, workId: WORK_ID, data: { expected_revision: 1 } })).rejects.toMatchObject({ code: 'save_outcome_unknown' });
    const missing = creatorFixture() as unknown as Record<string, unknown>; delete missing.languages;
    request.mockResolvedValue(missing);
    await expect(client.detail(CREATOR_ID)).rejects.toMatchObject({ code: 'invalid_response' });
  });
});
