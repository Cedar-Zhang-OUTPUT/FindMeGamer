import type { ContactDetail, CreatorDetail, CreatorFields, WorkDetail } from '../src/shared/creators';

export const CREATOR_ID = '11111111-1111-4111-8111-111111111111';
export const CONTACT_ID = '22222222-2222-4222-8222-222222222222';
export const WORK_ID = '44444444-4444-4444-8444-444444444444';
export function contactFixture(): ContactDetail {
  return { id: CONTACT_ID, email: 'creator@example.com', purpose: null, source_url: null, is_active: true,
    verification_notes: null, origin: 'manual', source_type: 'manual', validation_state: 'unverified',
    source_fields: {}, manual_overrides: { email: 'creator@example.com' }, identity_revision: 1,
    is_current_identity: true, updated_at: '2026-09-08T00:00:00Z' };
}
export function creatorFixture(name = 'Creator fixture', id = CREATOR_ID): CreatorDetail {
  const fields = (): CreatorFields => ({ name: null, public_name: null, public_name_confirmed: false,
    handle: null, profile_url: null, avatar_url: null, description: null, follower_count: null,
    follower_count_collected_at: null, languages: [], country_code: null, country_name: null,
    other_contacts: [], source_notes: null, internal_notes: null, interest_notes: null });
  return { ...fields(), name, id, platform: 'youtube', revision: 3, favorite: false,
    source_identity: { platform: 'youtube', account_id: 'UCfixture', canonical_url: 'https://www.youtube.com/channel/UCfixture', revision: 1 },
    source_fields: fields(), manual_overrides: { name }, overridden_fields: ['name'], contacts: [contactFixture()],
    work_count: 1, last_analyzed_at: null, next_analysis_at: null, analysis_available: true };
}
export function workFixture(): WorkDetail {
  return { id: WORK_ID, creator_id: CREATOR_ID, platform: 'youtube', source_platform: 'youtube',
    work_name: 'A recorded work', content_title: null, content_type: 'unverified', source_url: null,
    content_id: null, published_at: null, collected_at: null, metrics: [], game_id: null,
    verification_notes: null, evidence_excerpt: null, timestamp_seconds: null, origin: 'manual', revision: 1,
    identity_revision: 1, is_current_identity: true, source_content_id: null, source_collected_at: null,
    source_fields: {}, manual_overrides: { work_name: 'A recorded work' } };
}
