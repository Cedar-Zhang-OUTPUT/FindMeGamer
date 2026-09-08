import type { GameDetail } from '../src/shared/games';

export function gameFixture(name = 'A game', id = '33333333-3333-4333-8333-333333333333'): GameDetail {
  const fields = { name: null, website_url: null, steam_app_id: null, developer: null, description: null, tags: [], languages: [], release_date: null, cover_url: null };
  return { ...fields, id, name, revision: 0, favorite: false, reference_works: [], source_fields: { ...fields }, manual_overrides: { name }, overridden_fields: ['name'], source_identity: {steam_app_id:null,canonical_url:null}, last_analyzed_at: null, next_analysis_at:null };
}
