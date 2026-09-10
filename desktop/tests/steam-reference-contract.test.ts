import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { decodeDetail, GameClient } from '../src/main/game-client';
import { decodeDraft } from '../src/main/drafts-validation';
import { gameFixture } from './game-fixtures';
import { draftFixture } from './drafts-fixtures';
import { draftFrom, patchData } from '../src/renderer/components/gameDraft';
const sourceURL = 'https://store.steampowered.com/recommended/morelike/app/12345/';
function game() { return { ...gameFixture(), reference_works: [{ id: '11111111-1111-4111-8111-111111111111', name: 'Steam peer', url: 'https://store.steampowered.com/app/67890/', similarities: [], reason: null, source: 'steam_more_like_this' as const, source_url: sourceURL }], steam_recommendations: { status: 'partial' as const, source_url: sourceURL, fetched_at: '2026-09-10T00:00:00Z' } }; }
describe('Steam recommendation provenance', () => {
  it('accepts old Game responses without inventing recommendation metadata', () => expect(decodeDetail(gameFixture())).toEqual(gameFixture()));
  it('preserves recommendation provenance and partial state', () => expect(decodeDetail(game())).toEqual(game()));
  it('accepts provenance in immutable draft Game snapshots too', () => { const draft = draftFixture(); draft.input.game = game() as any; expect(decodeDraft(draft)).toEqual(draft); });
  it.each([{ status: 'invented' }, { source_url: 'javascript:alert(1)' }, { fetched_at: 'yesterday' }, { unknown: true }])('rejects invalid status metadata %j', patch => expect(() => decodeDetail({ ...game(), steam_recommendations: { ...game().steam_recommendations, ...patch } })).toThrow());
  it('rejects invalid reference provenance', () => expect(() => decodeDetail({ ...game(), reference_works: [{ ...game().reference_works[0], source: 'AI_verified' }] })).toThrow());
  it('keeps provenance server-owned when editing and deleting recommendations', async () => {
    const base = decodeDetail(game()), draft = draftFrom(base); draft.references[0].name = 'Edited peer'; draft.referencesTouched = true;
    const patch = patchData(base, draft); expect(patch.reference_works?.[0]).not.toHaveProperty('source'); expect(patch.reference_works?.[0]).not.toHaveProperty('source_url');
    draft.references = []; expect(patchData(base, draft).reference_works).toEqual([]);
    const request = vi.fn(); await expect(new GameClient(request).update({ id: base.id, data: { expected_revision: base.revision, reference_works: game().reference_works } })).rejects.toMatchObject({ code: 'request_invalid' }); expect(request).not.toHaveBeenCalled();
  });
});

it.skipIf(!process.env.FMG_STEAM_GAME_DTO)('decodes an actual backend Steam Game DTO unchanged', () => {
  const raw = JSON.parse(readFileSync(process.env.FMG_STEAM_GAME_DTO!, 'utf8'));
  expect(decodeDetail(raw)).toEqual(raw);
});
