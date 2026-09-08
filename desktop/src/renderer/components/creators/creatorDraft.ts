import { CREATOR_FIELDS, CONTACT_FIELDS, WORK_FIELDS, CREATOR_PLATFORMS, type CreatorDetail, type ContactDetail, type WorkDetail, type CreatorCreate, type CreatorPatch, type ContactCreate, type ContactPatch, type WorkCreate, type WorkPatch } from '../../../shared/creators';
import type { JsonValue } from '../../../shared/library';
export type EntityKind = 'creator' | 'contact' | 'work';
export interface EditContext { kind: EntityKind; base: CreatorDetail | ContactDetail | WorkDetail | null; creator?: CreatorDetail }
export interface EntityDraft { values: Record<string, JsonValue>; resets: string[] }
export const entityFields: Record<EntityKind, readonly string[]> = { creator: CREATOR_FIELDS, contact: CONTACT_FIELDS, work: WORK_FIELDS };
const defaults: Record<string, JsonValue> = { public_name_confirmed: false, favorite: false, is_active: true, languages: [], other_contacts: [], metrics: [], content_type: 'unverified' };
const labels: Record<string, string> = { name: 'Name', public_name: 'Public name', public_name_confirmed: 'Public name confirmed', handle: 'Handle', profile_url: 'Homepage URL', avatar_url: 'Avatar URL', description: 'Description', follower_count: 'Followers', follower_count_collected_at: 'Follower count collected at', languages: 'Languages', country_code: 'Country code', country_name: 'Country', other_contacts: 'Other contacts', source_notes: 'Source notes', internal_notes: 'Internal notes', interest_notes: 'Interest notes', favorite: 'Saved', platform: 'Platform', account_id: 'Account ID', email: 'Email', purpose: 'Purpose', source_url: 'Source URL', is_active: 'Active', verification_notes: 'Verification notes', work_name: 'Work name', content_title: 'Content title', content_type: 'Content type', content_id: 'Content ID', published_at: 'Published at', collected_at: 'Collected at', metrics: 'Metrics', game_id: 'Linked game', evidence_excerpt: 'Evidence excerpt', timestamp_seconds: 'Timestamp (seconds)' };
export function fieldLabel(key: string): string { return labels[key] ?? key.replaceAll('_', ' '); }
const copy = <T,>(value: T): T => structuredClone(value);
function keys(context: EditContext): string[] { return [...entityFields[context.kind], ...(context.kind === 'creator' ? context.base ? ['favorite'] : ['platform', 'account_id', 'favorite'] : [])]; }
function normalize(value: JsonValue): JsonValue {
  if (typeof value === 'string') return value.trim() || null;
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalize(item)]));
  return value;
}
function same(left: JsonValue, right: JsonValue): boolean {
  if (Object.is(left, right)) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) !== Array.isArray(right)) return false;
  const leftEntries = Object.entries(left); const rightEntries = Object.entries(right);
  return leftEntries.length === rightEntries.length && leftEntries.every(([key, value]) => Object.hasOwn(right, key) && same(value, (right as Record<string, JsonValue>)[key]));
}
const equal = (left: JsonValue, right: JsonValue) => same(normalize(left), normalize(right));
export function draftFrom(context: EditContext): EntityDraft {
  const base = context.base as unknown as Record<string, JsonValue> | null;
  return { values: Object.fromEntries(keys(context).map(key => [key, copy(base?.[key] ?? (key === 'platform' && context.kind === 'creator' ? 'youtube' : defaults[key] ?? null))])), resets: [] };
}
export function sourceValue(context: EditContext, key: string): JsonValue {
  const source = context.base?.source_fields as unknown as Record<string, JsonValue> | undefined;
  return copy(source?.[key] ?? defaults[key] ?? null);
}
export function updateDraftField(draft: EntityDraft, key: string, value: JsonValue): EntityDraft {
  const nameChanged = key === 'public_name' && !equal(draft.values.public_name, value);
  return { values: { ...draft.values, [key]: value, ...(nameChanged ? { public_name_confirmed: false } : {}) }, resets: draft.resets.filter(field => field !== key && !(nameChanged && field === 'public_name_confirmed')) };
}
export function changedKeys(context: EditContext, draft: EntityDraft): string[] {
  const initial = draftFrom(context).values;
  const publicNameChanged = context.kind === 'creator' && context.base && (draft.resets.includes('public_name') || (Object.hasOwn(draft.values, 'public_name') && !equal(draft.values.public_name, initial.public_name)));
  // Confirmation belongs to this name. The backend requires both in the same
  // PATCH even when an explicit reconfirmation equals the old boolean value.
  return keys(context).filter(key => (key === 'public_name_confirmed' && publicNameChanged) || (context.base && entityFields[context.kind].includes(key) && draft.resets.includes(key)) || (Object.hasOwn(draft.values, key) && !equal(draft.values[key], initial[key])));
}
export function makePayload(context: EditContext, draft: EntityDraft): CreatorCreate | CreatorPatch | ContactCreate | ContactPatch | WorkCreate | WorkPatch {
  const resets = context.base ? [...new Set(draft.resets)].filter(key => entityFields[context.kind].includes(key)) : [];
  const changes = changedKeys(context, draft).filter(key => !resets.includes(key));
  const entries = changes.map(key => [key, normalize(draft.values[key])] as const).filter(([, value]) => context.base || (value !== null && (!Array.isArray(value) || value.length > 0)));
  const payload: Record<string, unknown> = Object.fromEntries(entries);
  if (context.kind === 'creator' && !context.base) {
    payload.platform = draft.values.platform; payload.favorite = draft.values.favorite;
    if (normalize(draft.values.account_id) !== null) payload.account_id = normalize(draft.values.account_id);
  }
  if (context.kind === 'creator' && context.base) payload.expected_revision = (context.base as CreatorDetail).revision;
  if (context.kind === 'contact') payload.expected_revision = context.creator?.revision;
  if (context.kind === 'work') {
    if (context.base) payload.expected_revision = (context.base as WorkDetail).revision;
    else payload.expected_identity_revision = context.creator?.source_identity.revision;
  }
  if (resets.length) payload.reset_fields = resets;
  return payload as CreatorCreate | CreatorPatch | ContactCreate | ContactPatch | WorkCreate | WorkPatch;
}
export function validWebURL(value: string): boolean {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && Boolean(url.hostname) && !url.username && !url.password; } catch { return false; }
}
const text = (value: JsonValue | undefined): string => typeof value === 'string' ? value.trim() : '';
const validEmail = (value: JsonValue | undefined) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text(value));
export function canReset(context: EditContext, key: string): boolean { return key !== 'email' || validEmail(sourceValue(context, key)); }
export function validateDraft(context: EditContext, draft: EntityDraft): Record<string, string> {
  const errors: Record<string, string> = {};
  const values = draft.values;
  const submitted = context.base ? changedKeys(context, draft) : keys(context);
  if (!context.base && context.kind === 'creator' && !text(values.account_id) && !text(values.profile_url)) errors.account_id = 'Enter an account ID or homepage URL.';
  if (!context.base && context.kind === 'work' && !text(values.work_name) && !text(values.content_title) && !text(values.source_url)) errors.work_name = 'Enter a work name, content title or source URL.';
  if (context.kind !== 'creator' && !context.creator) errors[context.kind === 'contact' ? 'email' : 'work_name'] = 'Reload the creator before saving.';
  for (const key of submitted) {
    if (draft.resets.includes(key)) { if (!canReset(context, key)) errors[key] = 'No source email is available.'; continue; }
    const value = values[key]; const input = text(value);
    const max = ['description', 'source_notes', 'internal_notes', 'interest_notes', 'verification_notes', 'evidence_excerpt'].includes(key) ? 20000 : key.endsWith('_url') ? 2048 : key === 'purpose' ? 512 : key === 'account_id' ? 128 : 255;
    if (input.length > max) errors[key] = `Use at most ${max.toLocaleString()} characters.`;
    if (key.endsWith('_url') && input && !validWebURL(input)) errors[key] = 'Use an HTTP(S) URL without credentials.';
    if (key === 'email' && !validEmail(value)) errors[key] = 'Enter a valid email.';
    if (key === 'country_code' && input && !/^[A-Z]{2}$/.test(input)) errors[key] = 'Use a two-letter uppercase country code.';
    if (['follower_count', 'timestamp_seconds'].includes(key) && value !== null && (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || (key === 'follower_count' && !Number.isInteger(value)))) errors[key] = key === 'follower_count' ? 'Enter a whole number of zero or more, or leave unknown.' : 'Enter a finite number of zero or more.';
    if (['follower_count_collected_at', 'published_at', 'collected_at'].includes(key) && input && (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(input) || !Number.isFinite(Date.parse(input)))) errors[key] = 'Use a date and time with timezone, e.g. 2026-09-08T12:00:00+08:00.';
    if (key === 'platform' && value !== null && !CREATOR_PLATFORMS.includes(value as never)) errors[key] = 'Choose a platform.';
    if (key === 'content_type' && !['unverified', 'gameplay', 'livestream', 'review', 'commentary', 'trailer', 'news', 'other'].includes(String(value))) errors[key] = 'Choose a content type.';
    if (key === 'game_id' && input && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(input)) errors[key] = 'Choose a game from the Library.';
    if (['favorite', 'public_name_confirmed', 'is_active'].includes(key) && typeof value !== 'boolean') errors[key] = 'Choose yes or no.';
    if (key === 'languages' && (!Array.isArray(value) || value.length > 100 || value.some(item => typeof item !== 'string' || !item.trim() || item.length > 255))) errors[key] = 'Use up to 100 languages, each at most 255 characters.';
    if (key === 'other_contacts' || key === 'metrics') {
      if (!Array.isArray(value)) { errors[key] = 'Use the entry controls.'; continue; }
      if (value.length > (key === 'metrics' ? 30 : 100)) errors[key] = `Use up to ${key === 'metrics' ? 30 : 100} entries.`;
      value.forEach((entry, index) => {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) { errors[key] = 'Complete each entry.'; return; }
        const prefix = `${key}-${index}`;
        if (key === 'metrics') {
          if (!text(entry.name) || text(entry.name).length > 128) errors[`${prefix}-name`] = 'Enter a metric name, at most 128 characters.';
          if (typeof entry.value !== 'number' || !Number.isFinite(entry.value) || entry.value < 0) errors[`${prefix}-value`] = 'Enter a finite number of zero or more.';
        } else {
          if (!text(entry.value) || text(entry.value).length > 1024) errors[`${prefix}-value`] = 'Enter a contact value, at most 1,024 characters.';
          if (text(entry.label).length > 255) errors[`${prefix}-label`] = 'Use at most 255 characters.';
          if (text(entry.url) && (!validWebURL(text(entry.url)) || text(entry.url).length > 2048)) errors[`${prefix}-url`] = 'Use an HTTP(S) URL without credentials, at most 2,048 characters.';
        }
      });
    }
  }
  return errors;
}
