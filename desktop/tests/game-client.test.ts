import { describe, expect, it, vi } from 'vitest';
import { GameClient } from '../src/main/game-client';

const id = '21d62c9c-b1a6-4f41-8da9-739c00204c31';
const refId = '6553c78b-2f12-43cd-94f9-cd91dfbba0fd';
const fields = { name: 'Forest Signals', website_url: 'https://game.example/', steam_app_id: '12345',
  developer: 'Cedar Studio', description: 'Complete description.', tags: ['Strategy'], languages: ['English'],
  release_date: 'Coming soon', cover_url: 'https://images.example/cover.jpg' };
function game(overrides: Record<string, unknown> = {}) {
  return { ...fields, id, revision: 3, favorite: true,
    reference_works: [{ id: refId, name: 'Reference', url: 'https://reference.example/',
      similarities: ['Turn-based'], reason: 'Shared pacing.' }],
    source_fields: { ...fields, name: 'Source name' }, manual_overrides: { name: fields.name },
    overridden_fields: ['name'], source_identity: { steam_app_id: '67890',
      canonical_url: 'https://store.steampowered.com/app/67890' },
    last_analyzed_at: '2026-09-08T01:02:03.123456+00:00', next_analysis_at: null, ...overrides };
}

describe('GameClient v2 contract', () => {
  it('uses offset/total v2 pagination, never the v1 cursor contract', async () => {
    const request = vi.fn().mockResolvedValue({ items: [game()], total: 51, offset: 24, limit: 24 });
    const result = await new GameClient(request).list({ query: 'forest & leaves', onlyCollection: true, offset: 24, limit: 24 });
    expect(request).toHaveBeenCalledWith({ method: 'GET', path: '/api/v2/library/games',
      query: { query: 'forest & leaves', only_collection: 'true', offset: '24', limit: '24' } });
    expect(result).toEqual({ items: [game()], total: 51, offset: 24, limit: 24 });
  });
  it('sends default list filters and preserves a legitimate empty result', async () => {
    const request = vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    expect(await new GameClient(request).list({})).toEqual({ items: [], total: 0, offset: 0, limit: 50 });
    expect(request).toHaveBeenCalledWith({ method: 'GET', path: '/api/v2/library/games',
      query: { query: '', only_collection: 'false', offset: '0', limit: '50' } });
  });
  it('preserves distinct source/business identities, manual layers and reference UUIDs', async () => {
    const response = game({ manual_overrides: { name: fields.name, description: null,
      future_public_value: { label: 'Retain evidence', values: [null, 1, true] } } });
    const request = vi.fn().mockResolvedValue(response);
    expect(await new GameClient(request).detail(id)).toEqual(response);
    expect(request).toHaveBeenCalledWith({ method: 'GET', path: `/api/v2/library/games/${id}` });
  });
  it('normalizes only omitted optional GameFields to null/lists, including source fields', async () => {
    const minimal: Record<string, unknown> = { ...game(), source_fields: {} };
    for (const name of Object.keys(fields)) delete minimal[name];
    const result = await new GameClient(vi.fn().mockResolvedValue(minimal)).detail(id);
    expect(result.name).toBeNull(); expect(result.tags).toEqual([]);
    expect(result.source_fields).toEqual({ name: null, website_url: null, steam_app_id: null,
      developer: null, description: null, tags: [], languages: [], release_date: null, cover_url: null });
    expect(result.source_identity.steam_app_id).toBe('67890');
  });
  it('preserves a valid source response reference list beyond the write-input limit', async () => {
    const response = game({ reference_works: Array.from({ length: 101 }, (_, index) => ({
      id: null, name: `Reference ${index}`, url: null, similarities: [], reason: null,
    })) });
    expect((await new GameClient(vi.fn().mockResolvedValue(response)).detail(id)).reference_works).toEqual(response.reference_works);
  });
  it('creates with a caller-owned idempotency key and no implicit analysis or second request', async () => {
    const request = vi.fn().mockResolvedValue(game());
    expect(await new GameClient(request).create({ data: { name: '  Forest Signals  ',
      reference_works: [{ id: refId, url: 'https://reference.example', similarities: [], reason: 'Evidence' }] },
      idempotencyKey: 'game-create:1234' })).toEqual(game());
    expect(request).toHaveBeenCalledExactlyOnceWith({ method: 'POST', path: '/api/v2/library/games',
      idempotencyKey: 'game-create:1234', body: { name: 'Forest Signals',
        reference_works: [{ id: refId, url: 'https://reference.example', similarities: [], reason: 'Evidence' }] } });
  });
  it('allows a website-only game and an HTTP website without embedded credentials', async () => {
    const request = vi.fn().mockResolvedValue(game());
    await new GameClient(request).create({ data: { website_url: 'http://game.example/' }, idempotencyKey: 'new-game-123' });
    expect(request.mock.calls[0][0].body).toEqual({ website_url: 'http://game.example/' });
  });
  it('keeps PATCH omission, explicit null, empty lists, reset and expected revision distinct', async () => {
    const request = vi.fn().mockResolvedValue(game({ revision: 4 }));
    const data = { expected_revision: 3, developer: null, tags: [], reset_fields: ['name'] as ['name'],
      reference_works: [{ id: refId, name: 'Reference', similarities: [] }] };
    expect((await new GameClient(request).update({ id, data })).revision).toBe(4);
    expect(request).toHaveBeenCalledExactlyOnceWith({ method: 'PATCH', path: `/api/v2/library/games/${id}`, body: data });
    expect(request.mock.calls[0][0].body).not.toHaveProperty('favorite');
    expect(request.mock.calls[0][0].body).not.toHaveProperty('website_url');
  });
  it('does not infer clearing or resetting the other effective identity field from a partial PATCH', async () => {
    const request = vi.fn().mockResolvedValue(game({ name: null, revision: 4 }));
    await new GameClient(request).update({ id, data: { expected_revision: 3, name: null } });
    expect(request.mock.calls[0][0].body).toEqual({ expected_revision: 3, name: null });
  });
  it.each([
    { data: {}, idempotencyKey: 'new-game-123' },
    { data: { name: '  ', website_url: null }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', extra: 'ignored?' }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', source_identity: {} }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good' }, idempotencyKey: 'short' },
    { data: { name: 'Good' }, idempotencyKey: 'bad header\r\n' },
    { data: { name: 'Good' }, idempotencyKey: 'x'.repeat(129) },
    { data: { name: 1 }, idempotencyKey: 'new-game-123' },
    { data: { name: 'x'.repeat(256) }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', description: 'x'.repeat(20001) }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', steam_app_id: 12345 }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', steam_app_id: '0123' }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', steam_app_id: '1'.repeat(21) }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', tags: null }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', languages: [''] }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', tags: Array(101).fill('one') }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', favorite: 'false' }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', cover_url: 'file:///private/a' }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', website_url: 'https://u:pw@host.example/' }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', website_url: 'https://@host.example/' }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', reference_works: [{ similarities: [] }] }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', reference_works: [{ name: 'Ref', id: '../x', similarities: [] }] }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', reference_works: [{ name: 'Ref', url: 'https://u@host.test', similarities: [] }] }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good', reference_works: [{ name: 'Ref', unknown: true, similarities: [] }] }, idempotencyKey: 'new-game-123' },
    { data: { name: 'Good' }, idempotencyKey: 'new-game-123', route: '/api/v1/jobs' },
  ])('rejects invalid/unknown create fields before network: %#', async input => {
    const request = vi.fn();
    await expect(new GameClient(request).create(input as never)).rejects.toMatchObject({ code: 'request_invalid', retryable: false });
    expect(request).not.toHaveBeenCalled();
  });
  it.each([
    { id, data: {} }, { id: '../session', data: { expected_revision: 1 } },
    { id, data: { expected_revision: -1 } }, { id, data: { expected_revision: 1.5 } },
    { id, data: { expected_revision: '1' } },
    { id, data: { expected_revision: 1, name: null, reset_fields: ['name'] } },
    { id, data: { expected_revision: 1, reset_fields: ['source_identity'] } },
    { id, data: { expected_revision: 1, reset_fields: Array(10).fill('name') } },
    { id, data: { expected_revision: 1, website_url: null, name: null } },
    { id, data: { expected_revision: 1, revision: 20 } },
  ])('rejects invalid PATCH without auto-correcting revision/reset: %#', async input => {
    const request = vi.fn();
    await expect(new GameClient(request).update(input as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it.each([{ query: 'a'.repeat(256) }, { limit: 101 }, { limit: 0 }, { offset: -1 }, { offset: 1.5 },
    { onlyCollection: 'false' }, { cursor: 'v1-cursor' }, { kind: 'creators' }])('rejects invalid list input: %#', async input => {
    const request = vi.fn();
    await expect(new GameClient(request).list(input as never)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });
  it.each([
    {}, game({ revision: '3' }), game({ favorite: 'yes' }), game({ tags: null }), game({ id: 'bad' }),
    game({ source_fields: null }), game({ source_identity: null }), game({ manual_overrides: [] }),
    game({ overridden_fields: ['fake'] }), game({ reference_works: [{ name: 'Ref', id: 'bad', similarities: [] }] }),
    game({ next_analysis_at: 'yesterday' }), game({ arbitrary: 'extra' }), game({ website_url: 'javascript:alert(1)' }),
  ])('rejects damaged details rather than swallowing them: %#', async response => {
    await expect(new GameClient(vi.fn().mockResolvedValue(response)).detail(id)).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it.each([{}, { items: [], total: '0', limit: 50, offset: 0 }, { items: null, total: 0, limit: 50, offset: 0 },
    { items: [], total: 0, limit: 50, offset: -1 }])('rejects malformed pages: %#', async response => {
    await expect(new GameClient(vi.fn().mockResolvedValue(response)).list({})).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('does not retry transport/conflict failures and keeps the original save idempotency key owned by caller', async () => {
    const error = Object.assign(new Error('Check before saving again.'), { code: 'save_outcome_unknown', retryable: false });
    const request = vi.fn().mockRejectedValue(error);
    await expect(new GameClient(request).create({ data: { name: 'Good' }, idempotencyKey: 'new-game-123' })).rejects.toBe(error);
    expect(request).toHaveBeenCalledOnce();
  });
  it.each(['create', 'update'])('treats a successful HTTP response with a damaged DTO as an unknown save result: %s', async operation => {
    const request = vi.fn().mockResolvedValue({ id, revision: 4 });
    const client = new GameClient(request);
    const result = operation === 'create'
      ? client.create({ data: { name: 'Game' }, idempotencyKey: 'new-game-123' })
      : client.update({ id, data: { expected_revision: 3, name: 'Game' } });
    await expect(result).rejects.toMatchObject({ code: 'save_outcome_unknown', retryable: false });
    expect(request).toHaveBeenCalledOnce();
  });
});
