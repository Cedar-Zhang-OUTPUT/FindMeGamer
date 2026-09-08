import { describe, expect, it } from 'vitest';
import { changedKeys, draftFrom, makePayload, updateDraftField, validateDraft, type EditContext } from '../src/renderer/components/creators/creatorDraft';
import { creatorFormFixture, contactFormFixture, workFormFixture } from './creator-form-fixtures';

describe('creator drafts', () => {
  it('includes explicit confirmation with the exact renamed public name even when the base was confirmed', () => {
    const context: EditContext = { kind: 'creator', base: creatorFormFixture() };
    let draft = updateDraftField(draftFrom(context), 'public_name', 'New name');
    draft = updateDraftField(draft, 'public_name_confirmed', true);
    expect(changedKeys(context, draft)).toEqual(['public_name', 'public_name_confirmed']);
    expect(makePayload(context, draft)).toEqual({ expected_revision: 7, public_name: 'New name', public_name_confirmed: true });
    draft = updateDraftField(draft, 'public_name', 'Different name');
    expect(makePayload(context, draft)).toEqual({ expected_revision: 7, public_name: 'Different name', public_name_confirmed: false });
  });
  it('creates only explicit meaningful fields and preserves unknown followers', () => {
    const context: EditContext = { kind: 'creator', base: null };
    const draft = draftFrom(context);
    expect(draft.values).toMatchObject({ platform: 'youtube', account_id: null, favorite: false, follower_count: null, languages: [], other_contacts: [] });
    expect(changedKeys(context, draft)).toEqual([]);
    draft.values.account_id = 'harbor';
    expect(makePayload(context, draft)).toEqual({ platform: 'youtube', account_id: 'harbor', favorite: false });
    draft.values.follower_count = 0;
    expect(makePayload(context, draft)).toEqual({ platform: 'youtube', account_id: 'harbor', favorite: false, follower_count: 0 });
  });
  it('patches only supported changes and preserves null and array clears', () => {
    const context: EditContext = { kind: 'creator', base: creatorFormFixture() };
    const draft = draftFrom(context); draft.values.description = null; draft.values.languages = []; draft.values.account_id = 'other'; draft.values.revision = 99;
    expect(makePayload(context, draft)).toEqual({ expected_revision: 7, description: null, languages: [] });
    expect(changedKeys(context, draft)).toEqual(['description', 'languages']);
    expect(context.base).toMatchObject({ source_identity: { account_id: 'harbor', revision: 3 } });
  });
  it('resets never overlap explicit fields and reject unsupported reset keys', () => {
    const context: EditContext = { kind: 'creator', base: creatorFormFixture() };
    const draft = draftFrom(context); draft.values.name = 'Source Harbor'; draft.resets = ['name', 'name', 'revision', 'favorite'];
    expect(makePayload(context, draft)).toEqual({ expected_revision: 7, reset_fields: ['name'] });
  });
  it('uses creator revision for contacts and blocks null email and sourceless email reset', () => {
    const context: EditContext = { kind: 'contact', base: contactFormFixture(), creator: creatorFormFixture() };
    const draft = draftFrom(context); draft.values.email = null;
    expect(validateDraft(context, draft)).toHaveProperty('email');
    draft.values.email = 'new@example.com';
    expect(makePayload(context, draft)).toEqual({ expected_revision: 7, email: 'new@example.com' });
    draft.resets = ['email'];
    expect(validateDraft(context, draft)).toHaveProperty('email');
  });
  it('requires a name, title or URL for work create and uses identity revision', () => {
    const context: EditContext = { kind: 'work', base: null, creator: creatorFormFixture() };
    const draft = draftFrom(context); expect(validateDraft(context, draft)).toHaveProperty('work_name');
    draft.values.content_title = 'Review';
    expect(makePayload(context, draft)).toEqual({ expected_identity_revision: 3, content_title: 'Review' });
    expect(validateDraft(context, draft)).toEqual({});
  });
  it('uses work revision, validates finite nonnegative metrics/time and permits explicit empty metrics', () => {
    const context: EditContext = { kind: 'work', base: workFormFixture(), creator: creatorFormFixture() };
    const draft = draftFrom(context); draft.values.metrics = []; draft.values.timestamp_seconds = 0;
    expect(makePayload(context, draft)).toEqual({ expected_revision: 11, metrics: [], timestamp_seconds: 0 });
    draft.values.metrics = [{ name: 'views', value: Infinity }]; draft.values.timestamp_seconds = -1;
    expect(validateDraft(context, draft)).toMatchObject({ 'metrics-0-value': expect.any(String), timestamp_seconds: expect.any(String) });
  });
  it('validates timezones, integer followers, URLs and repeatable contact rows', () => {
    const context: EditContext = { kind: 'creator', base: creatorFormFixture() }; const draft = draftFrom(context);
    draft.values.follower_count = 0.5; draft.values.follower_count_collected_at = '2026-09-08T12:00'; draft.values.profile_url = 'javascript:alert(1)'; draft.values.other_contacts = [{ label: null, value: '', url: null }];
    expect(validateDraft(context, draft)).toMatchObject({ follower_count: expect.any(String), follower_count_collected_at: expect.any(String), profile_url: expect.any(String), 'other_contacts-0-value': expect.any(String) });
  });
  it('rejects nonfinite numbers instead of treating them as unchanged unknown values', () => {
    const context: EditContext = { kind: 'work', base: workFormFixture(), creator: creatorFormFixture() };
    for (const value of [Infinity, -Infinity, NaN]) {
      const draft = draftFrom(context); draft.values.timestamp_seconds = value;
      expect(validateDraft(context, draft)).toHaveProperty('timestamp_seconds');
    }
  });
});
