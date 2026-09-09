import { expect, it, vi } from 'vitest';
import { AnalysisClient } from '../src/main/analyze-client';
import { gameFixture } from './game-fixtures';
import { creatorFixture } from './creator-fixtures';
export const jobId = '11111111-1111-4111-8111-111111111111';
export const job = () => ({ outcome: 'job', id: jobId, target_type: 'creator', canonical_target_id: 'x:123', canonical_url: 'https://x.com/i/user/123', mode: 'reanalyze', status: 'queued', stage: null, completed_units: 0, total_units: 0, retryable: false, error: null, correlation_id: null, profile_id: null, created_at: '2026-09-09T00:00:00Z', updated_at: '2026-09-09T00:00:00Z', started_at: null, completed_at: null, waiting_reason: null, resume_available: false });
it('uses keyed create and same-job resume, while retry may return a new job', async () => {
  const request = vi.fn().mockResolvedValue(job()), client = new AnalysisClient(request);
  await client.create({ target_type: 'creator', url: 'https://x.com/i/user/123', mode: 'reanalyze', idempotencyKey: 'original-key' });
  await client.resume({ jobId, idempotencyKey: 'resume-key' }); await client.retry({ jobId, idempotencyKey: 'retry-key' });
  expect(request.mock.calls.map(c => c[0])).toEqual([
    { method: 'POST', path: '/api/v1/jobs/analysis', body: { target_type: 'creator', url: 'https://x.com/i/user/123', mode: 'reanalyze' }, idempotencyKey: 'original-key' },
    { method: 'POST', path: `/api/v1/jobs/analysis/${jobId}/resume`, idempotencyKey: 'resume-key' },
    { method: 'POST', path: `/api/v1/jobs/analysis/${jobId}/retry`, body: {}, idempotencyKey: 'retry-key' },
  ]);
});
it('rejects impossible job states and mismatched identity; mutation malformed receipt is unknown', async () => {
  const request = vi.fn(), client = new AnalysisClient(request);
  for (const patch of [{ canonical_target_id: jobId }, { status: 'succeeded' }, { completed_units: 1 }, { waiting_reason: 'explicit_resume_required', resume_available: false }, { status: 'failed', error: { code: 'x_unavailable', message: 'secret' } }]) {
    request.mockResolvedValue({ ...job(), ...patch });
    await expect(client.detail({ jobId })).rejects.toMatchObject({ code: 'invalid_response' });
    await expect(client.retry({ jobId, idempotencyKey: 'retry-key' })).rejects.toMatchObject({ code: 'analysis_write_unknown' });
  }
});
it('validates requests before invoking transport', async () => {
  const request = vi.fn(), client = new AnalysisClient(request);
  await expect(client.steamImport({ url: 'https://store.steampowered.com/app/1', gameId: jobId, idempotencyKey: 'original-key' })).rejects.toMatchObject({ code: 'request_invalid' });
  await expect(client.create({ target_type: 'creator', url: 'https://x.com/handle', mode: 'reanalyze', idempotencyKey: 'original-key' })).rejects.toMatchObject({ code: 'request_invalid' });
  expect(request).not.toHaveBeenCalled();
});
it('imports source-only Game and explicitly binds the same Creator with exact revision', async () => {
  const game = { ...gameFixture(), revision: 1, source_identity: { steam_app_id: '123', canonical_url: 'https://store.steampowered.com/app/123' } }, creator = creatorFixture(), request = vi.fn().mockResolvedValue(game), client = new AnalysisClient(request);
  expect((await client.steamImport({ url: 'https://store.steampowered.com/app/123/title', idempotencyKey: 'import-key' })).last_analyzed_at).toBeNull();
  request.mockResolvedValue(creator); expect((await client.bindYouTube({ creatorId: creator.id, url: 'https://www.youtube.com/@fixture', expectedRevision: 2, idempotencyKey: 'binding-key' })).id).toBe(creator.id);
  expect(request.mock.calls[1][0]).toMatchObject({ path: `/api/v2/library/creators/${creator.id}/youtube-binding`, body: { url: 'https://www.youtube.com/@fixture', expected_revision: 2 } });
  await expect(client.bindYouTube({ creatorId: creator.id, url: 'https://www.youtube.com/@fixture', expectedRevision: 3, idempotencyKey: 'binding-key' })).rejects.toMatchObject({ code: 'analysis_write_unknown' });
});
it('accepts existing-profile outcome and mixed change pages without treating Match as Analyze', async () => {
  const existing = { outcome: 'existing_profile', existing_profile_id: jobId, target_type: 'creator', canonical_target_id: 'x:123', canonical_url: 'https://x.com/i/user/123' }, request = vi.fn().mockResolvedValue(existing), client = new AnalysisClient(request);
  expect(await client.create({ target_type: 'creator', url: existing.canonical_url, mode: 'create', idempotencyKey: 'existing-key' })).toEqual(existing);
  const match = { kind: 'match', resource_id: jobId, status: 'queued', stage: 'screening', completed_units: 0, total_units: 0, result_count: 0, retryable: false, error: null, correlation_id: null, game_id: jobId, supersedes_id: null, created_at: job().created_at, updated_at: job().updated_at, started_at: null, completed_at: null };
  request.mockResolvedValue({ items: [{ ...job(), kind: 'analysis', resource_id: jobId }, match], cursor: 'opaque.cursor', has_more: false, affected_profile_ids: [] });
  expect((await client.changed({ cursor: 'previous.cursor', limit: 10 })).items.map(r => r.kind)).toEqual(['analysis','match']);
  expect(request.mock.calls.at(-1)?.[0]).toEqual({ method: 'GET', path: '/api/v1/jobs', query: { limit: '10', changed_after: 'previous.cursor' } });
  request.mockResolvedValue({ items: [{ ...match, status: 'failed', error: { code: 'match_queue_unavailable', message: 'Match could not be queued. Please retry.' }, retryable: true, completed_at: job().created_at }], cursor: 'next.cursor', has_more: false, affected_profile_ids: [] });
  expect((await client.changed({ cursor: 'opaque.cursor' })).cursor).toBe('next.cursor');
});
it('accepts truthful failed, paused and complete states without fabricating progress', async () => {
  const request = vi.fn(), client = new AnalysisClient(request);
  for (const patch of [{ waiting_reason: 'collection_disabled' }, { waiting_reason: 'explicit_resume_required', resume_available: true }, { status: 'failed', retryable: true, error: { code: 'x_unavailable', message: 'Analysis is temporarily unavailable. Please retry.' }, completed_at: job().created_at }, { status: 'succeeded', stage: 'finalizing', completed_units: 1, total_units: 1, profile_id: jobId, started_at: job().created_at, completed_at: job().created_at }]) { request.mockResolvedValue({ ...job(), ...patch }); expect(await client.detail({ jobId })).toMatchObject(patch); }
});
it('allows active-job reuse across create/reanalyze modes but never resolves a YouTube handle to X', async () => {
  const request = vi.fn().mockResolvedValue(job()), client = new AnalysisClient(request);
  expect((await client.create({ target_type: 'creator', url: 'https://x.com/i/user/123', mode: 'create', idempotencyKey: 'reuse-key' })).outcome).toBe('job');
  await expect(client.create({ target_type: 'creator', url: 'https://www.youtube.com/@fixture', mode: 'create', idempotencyKey: 'handle-key' })).rejects.toMatchObject({ code: 'analysis_write_unknown' });
});
