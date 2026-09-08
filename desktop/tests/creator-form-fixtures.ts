import type { CreatorDetail, ContactDetail, WorkDetail } from '../src/shared/creators';
import { creatorFixture, contactFixture, workFixture } from './creator-fixtures';

export function creatorFormFixture(overrides: Partial<CreatorDetail> = {}): CreatorDetail {
  const fields = { name: 'Harbor', public_name: 'Harbor', public_name_confirmed: true, handle: null, profile_url: 'https://example.com/harbor', avatar_url: null, description: 'A creator', follower_count: null, follower_count_collected_at: null, languages: ['English'], country_code: null, country_name: null, other_contacts: [], source_notes: null, internal_notes: null, interest_notes: null };
  return { ...creatorFixture(), ...fields, revision: 7, source_identity: { platform: 'youtube', account_id: 'harbor', canonical_url: 'https://youtube.com/@harbor', revision: 3 }, source_fields: { ...fields, name: 'Source Harbor' }, manual_overrides: { name: 'Harbor' }, contacts: [], ...overrides };
}
export function contactFormFixture(overrides: Partial<ContactDetail> = {}): ContactDetail {
  return { ...contactFixture(), email: 'hello@example.com', purpose: 'Business', validation_state: 'unknown', manual_overrides: { email: 'hello@example.com' }, identity_revision: 3, ...overrides };
}
export function workFormFixture(overrides: Partial<WorkDetail> = {}): WorkDetail {
  return { ...workFixture(), work_name: 'Harbor review', metrics: [{ name: 'views', value: 20 }], revision: 11, identity_revision: 3, manual_overrides: {}, ...overrides };
}
