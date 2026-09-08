import { describe, expect, it, vi } from 'vitest';
import { LibraryClient, LibraryClientError } from '../src/main/library-client';

const gameId = '21d62c9c-b1a6-4f41-8da9-739c00204c31';
const creatorId = '6553c78b-2f12-43cd-94f9-cd91dfbba0fd';
const timestamp = '2026-09-08T01:02:03.123456+00:00';

function game(overrides: Record<string, unknown> = {}) {
  return {
    type: 'game', id: gameId, name: 'Forest Signals', steam_app_id: '123456',
    canonical_url: 'https://store.steampowered.com/app/123456/', favorite: false,
    current_facts: { short_description: 'A tactical expedition.', genres: ['Strategy'],
      header_image_url: 'https://images.example/game.jpg' },
    brief: { positioning_premise: { value: 'Thoughtful strategy.' } }, source_status: {},
    last_analyzed_at: timestamp, next_analysis_at: null, ...overrides,
  };
}

function contact(overrides: Record<string, unknown> = {}) {
  return { email: 'press@example.com', source: 'youtube',
    source_url: 'https://www.youtube.com/@creator/about', validation_state: 'unverified',
    purpose: 'Review requests', ...overrides };
}

function creator(overrides: Record<string, unknown> = {}) {
  return {
    type: 'creator', id: creatorId, name: 'Cedar Plays', youtube_channel_id: 'UC_example',
    canonical_url: 'https://www.youtube.com/channel/UC_example', favorite: true,
    current_facts: { subscriber_count: 42000, avatar_url: 'https://images.example/avatar.png' },
    brief: { performance_context: { value: 'Regular long-form reviews.', source: 'AI' },
      content_focus: { values: ['Strategy', 'Indie', 'Strategy', '  '] } },
    source_status: { youtube: 'current' }, last_analyzed_at: null, next_analysis_at: null,
    contact: contact(), contacts: [contact()], ...overrides,
  };
}

function detail(base: Record<string, unknown>): Record<string, unknown> {
  return { ...base, analysis: {}, model_metadata: {}, prompt_metadata: {},
    ...(base.type === 'creator' ? { manual_notes: null } : {}) };
}

describe('LibraryClient read-only contract', () => {
  it('validates the authenticated session route and retains unknown service names', async () => {
    const request = vi.fn().mockResolvedValue({ workspace_name: 'My workspace', api_version: 'v1',
      service_connections: { youtube: false, gemini: true, future_service: false } });
    expect(await new LibraryClient(request).session()).toEqual({ workspaceName: 'My workspace',
      apiVersion: 'v1', serviceConnections: { youtube: false, gemini: true, future_service: false } });
    expect(request).toHaveBeenCalledWith('/api/v1/session');
  });

  it.each([{}, { workspace_name: 'Workspace', api_version: 'v1', service_connections: { youtube: 'yes' } }])(
    'rejects an invalid session instead of reporting authentication success: %j', async response => {
      await expect(new LibraryClient(vi.fn().mockResolvedValue(response)).session())
        .rejects.toMatchObject({ code: 'invalid_response' });
    },
  );

  it('maps the real games route, exact query names, nullable cursor and known field paths', async () => {
    const request = vi.fn().mockResolvedValue({ items: [game()], next_cursor: 'opaque+/=' });
    const result = await new LibraryClient(request).list({ kind: 'games', query: 'forest',
      onlyCollection: true, cursor: 'previous+/=', limit: 24 });
    expect(request).toHaveBeenCalledWith('/api/v1/profiles/games', {
      query: 'forest', only_collection: 'true', cursor: 'previous+/=', limit: '24',
    });
    expect(result.nextCursor).toBe('opaque+/=');
    expect(result.items[0]).toEqual({ id: gameId, kind: 'games', name: 'Forest Signals',
      sourceId: '123456', canonicalUrl: 'https://store.steampowered.com/app/123456/',
      summary: 'A tactical expedition.', artworkUrl: 'https://images.example/game.jpg',
      favorite: false, updatedAt: timestamp, subscribers: null, tags: ['Strategy'] });
  });

  it('omits a first-page cursor and respects an empty successful final page', async () => {
    const request = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
    expect(await new LibraryClient(request).list({ kind: 'creators' })).toEqual({ items: [], nextCursor: null });
    expect(request).toHaveBeenCalledWith('/api/v1/profiles/creators', {
      query: '', only_collection: 'false', limit: '50',
    });
  });

  it('unwraps actual brief evidence fields without fabricating counts or images', async () => {
    const request = vi.fn().mockResolvedValue({ items: [creator()], next_cursor: null });
    const { items } = await new LibraryClient(request).list({ kind: 'creators' });
    expect(items[0]).toMatchObject({ sourceId: 'UC_example', subscribers: 42000,
      summary: 'Regular long-form reviews.', artworkUrl: 'https://images.example/avatar.png',
      tags: ['Strategy', 'Indie'], updatedAt: null });
    request.mockResolvedValue({ items: [creator({ current_facts: { subscriber_count: '42000',
      avatar_url: 'file:///private/avatar.png' }, brief: {} })], next_cursor: null });
    expect((await new LibraryClient(request).list({ kind: 'creators' })).items[0]).toMatchObject({
      subscribers: null, artworkUrl: null, summary: null, tags: [],
    });
  });

  it('retains all public detail data, evidence, email purposes and unknown nested fields', async () => {
    const raw = detail(creator({ current_facts: { description: 'The complete channel description.',
      future_metric: { unit: 'minutes', values: [1, null, true] } },
      source_status: { youtube: { state: 'stale', reason: 'Source changed' } },
      contacts: [contact(), contact({ email: 'business@example.com', purpose: 'Sponsorships' })] }));
    raw.analysis = { audience: { value: 'Strategy fans', confidence: 'inferred',
      sources: ['https://www.youtube.com/channel/UC_example'] } };
    const request = vi.fn().mockResolvedValue(raw);
    const result = await new LibraryClient(request).detail({ kind: 'creators', id: creatorId });
    expect(request).toHaveBeenCalledWith(`/api/v1/profiles/creators/${creatorId}`);
    expect(result.raw).toEqual(raw);
    expect(result.groups.find(group => group.id === 'facts')?.data).toEqual(raw.current_facts);
    expect(result.groups.find(group => group.id === 'analysis')?.data).toEqual(raw.analysis);
    expect(result.groups.find(group => group.id === 'sources')?.data).toEqual(raw.source_status);
    expect(result.contacts.map(item => item.purpose)).toEqual(['Review requests', 'Sponsorships']);
    expect(result.contacts[0]).toMatchObject({ validationState: 'unverified', source: 'youtube',
      sourceUrl: 'https://www.youtube.com/@creator/about' });
    expect(result.manualNotes).toBeNull();
  });

  it('uses legacy contact only when contacts is absent, never when explicitly empty', async () => {
    const legacy = detail(creator());
    delete (legacy as Record<string, unknown>).contacts;
    const request = vi.fn().mockResolvedValue(legacy);
    const client = new LibraryClient(request);
    expect((await client.detail({ kind: 'creators', id: creatorId })).contacts).toHaveLength(1);
    request.mockResolvedValue(detail(creator({ contacts: [] })));
    expect((await client.detail({ kind: 'creators', id: creatorId })).contacts).toEqual([]);
  });

  it('uses the requested kind when optional wire type is absent and rejects a contradictory type', async () => {
    const row: Record<string, unknown> = game(); delete row.type;
    const request = vi.fn().mockResolvedValue({ items: [row], next_cursor: null });
    expect((await new LibraryClient(request).list({ kind: 'games' })).items[0].kind).toBe('games');
    request.mockResolvedValue({ items: [creator()], next_cursor: null });
    await expect(new LibraryClient(request).list({ kind: 'games' })).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('preserves business unknown fields but excludes credential-shaped data from renderer DTOs', async () => {
    const request = vi.fn().mockResolvedValue(detail(game({ current_facts: { secretary: 'Public role',
      game_key: 'A business field', future_value: { note: 'Keep this' }, api_key: 'DO-NOT-LEAK',
      nested: { authorization: 'DO-NOT-LEAK', workspaceAccessKey: 'DO-NOT-LEAK' } },
      unknown_business_field: { value: 'Still public' }, password: 'DO-NOT-LEAK' })));
    const result = await new LibraryClient(request).detail({ kind: 'games', id: gameId });
    expect(JSON.stringify(result)).not.toContain('DO-NOT-LEAK');
    expect(result.raw.unknown_business_field).toEqual({ value: 'Still public' });
    expect(result.raw.current_facts).toMatchObject({ secretary: 'Public role', game_key: 'A business field',
      future_value: { note: 'Keep this' } });
  });

  it.each([
    { kind: 'people' }, { kind: '../games' }, { kind: 'games', query: 'a'.repeat(256) },
    { kind: 'games', query: 42 }, { kind: 'games', query: null },
    { kind: 'games', onlyCollection: 'true' }, { kind: 'games', onlyCollection: null },
    { kind: 'games', limit: 0 }, { kind: 'games', limit: 101 }, { kind: 'games', limit: 1.5 },
    { kind: 'games', limit: null },
    { kind: 'games', cursor: '' }, { kind: 'games', cursor: 'x'.repeat(2049) },
  ])('rejects invalid list input without a request: %j', async input => {
    const request = vi.fn();
    await expect(new LibraryClient(request).list(input as never)).rejects.toMatchObject({ code: 'invalid_input' });
    expect(request).not.toHaveBeenCalled();
  });

  it('counts Unicode code points for the documented query limit', async () => {
    const request = vi.fn().mockResolvedValue({ items: [], next_cursor: null });
    await new LibraryClient(request).list({ kind: 'games', query: '🎮'.repeat(255) });
    expect(request).toHaveBeenCalledOnce();
  });

  it.each(['../session', '', 'not-a-uuid'])('rejects invalid detail IDs before transport: %s', async id => {
    const request = vi.fn();
    await expect(new LibraryClient(request).detail({ kind: 'games', id })).rejects.toMatchObject({ code: 'invalid_input' });
    expect(request).not.toHaveBeenCalled();
  });

  it.each([{}, { items: [] }, { items: null, next_cursor: null }, { items: [], next_cursor: 5 },
    { items: [game({ favorite: 'false' })], next_cursor: null },
    { items: [game({ current_facts: [] })], next_cursor: null },
    { items: [game({ last_analyzed_at: 'yesterday' })], next_cursor: null },
  ])('does not turn a malformed response into an empty success: %j', async response => {
    const request = vi.fn().mockResolvedValue(response);
    await expect(new LibraryClient(request).list({ kind: 'games' })).rejects.toBeInstanceOf(LibraryClientError);
  });

  it('propagates real API envelopes and thrown transport failures without retrying', async () => {
    const request = vi.fn().mockResolvedValue({ error: { code: 'workspace_key_invalid',
      message: 'A valid Workspace Access Key is required.', retryable: false, correlation_id: gameId } });
    await expect(new LibraryClient(request).session()).rejects.toMatchObject({ code: 'workspace_key_invalid',
      retryable: false, correlationId: gameId });
    expect(request).toHaveBeenCalledOnce();
    const offline = new Error('offline'); request.mockRejectedValue(offline);
    await expect(new LibraryClient(request).list({ kind: 'games' })).rejects.toBe(offline);
  });

  it('rejects incomplete details and mismatched returned identity', async () => {
    const request = vi.fn().mockResolvedValue(game());
    const client = new LibraryClient(request);
    await expect(client.detail({ kind: 'games', id: gameId })).rejects.toMatchObject({ code: 'invalid_response' });
    request.mockResolvedValue(detail(game({ id: creatorId })));
    await expect(client.detail({ kind: 'games', id: gameId })).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('rejects malformed contacts and does not silently label them unavailable', async () => {
    const request = vi.fn().mockResolvedValue(detail(creator({ contacts: null })));
    await expect(new LibraryClient(request).detail({ kind: 'creators', id: creatorId }))
      .rejects.toMatchObject({ code: 'invalid_response' });
    request.mockResolvedValue(detail(creator({ contacts: [contact({ validation_state: false })] })));
    await expect(new LibraryClient(request).detail({ kind: 'creators', id: creatorId }))
      .rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('rejects non-JSON response content instead of leaking it into IPC', async () => {
    const cyclic: Record<string, unknown> = {}; cyclic.loop = cyclic;
    const request = vi.fn().mockResolvedValue({ ...detail(game()), analysis: cyclic });
    await expect(new LibraryClient(request).detail({ kind: 'games', id: gameId })).rejects.toMatchObject({ code: 'invalid_response' });
  });
});
