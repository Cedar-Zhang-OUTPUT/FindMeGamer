import { domainToASCII } from 'node:url';
import { CONTACT_FIELDS, CREATOR_FIELDS, CREATOR_PLATFORMS, WORK_FIELDS } from '../shared/creators';
import type { ContactDetail, CreatorDetail, CreatorFields, CreatorSort, RecentWorkSummary, WorkDetail } from '../shared/creators';
import { PublicFailure } from './transport';
import type { JsonObject, JsonValue } from '../shared/library';

export type Mode = 'input' | 'response';
export const UUID_SOURCE = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
export const UUID_PATTERN = new RegExp(`^${UUID_SOURCE}$`);
export function fail(mode: Mode): never {
  throw new PublicFailure(mode === 'input' ? 'request_invalid' : 'invalid_response', mode === 'input'
    ? 'Check the Creator fields, required values, and source URLs before saving.'
    : 'The service returned an unsupported Creator response. Reload or check the service version.', false);
}
export function object(value: unknown, mode: Mode): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail(mode);
  return value as Record<string, unknown>;
}
export function keys(raw: Record<string, unknown>, allowed: readonly string[], mode: Mode) {
  if (Object.keys(raw).some(key => !allowed.includes(key))) fail(mode);
}
export function integer(value: unknown, mode: Mode, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) fail(mode);
  return value;
}
export function bool(value: unknown, mode: Mode): boolean { if (typeof value !== 'boolean') fail(mode); return value; }
export function identifier(value: unknown, mode: Mode): string { if (typeof value !== 'string' || !UUID_PATTERN.test(value)) fail(mode); return value; }
export function text(value: unknown, mode: Mode, max: number, min = 0): string {
  if (typeof value !== 'string' || [...value].length > max || [...value].length < min) fail(mode);
  return value;
}
function optionalText(value: unknown, mode: Mode, max: number): string | null { return value === null ? null : text(value, mode, max); }
function enumValue<T extends string>(value: unknown, allowed: readonly T[], mode: Mode): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) fail(mode); return value as T;
}
export function platform(value: unknown, mode: Mode) { return enumValue(value, CREATOR_PLATFORMS, mode); }
export function creatorSort(value: unknown, mode: Mode): CreatorSort {
  return enumValue(value, ['name', 'relevance', 'followers', 'recent_publish', 'recent_added'] as const, mode);
}
export function platformList(value: unknown, mode: Mode) {
  return array(value, mode, 4, item => platform(item, mode));
}
export function languageList(value: unknown, mode: Mode) {
  return array(value, mode, 30, item => text(item, mode, 255, 1));
}
export function timestamp(value: unknown, mode: Mode): string | null {
  if (value === null) return null;
  const result = text(value, mode, 100);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(result) || !Number.isFinite(Date.parse(result))) fail(mode);
  const [year, month, day, hour, minute, second] = result.slice(0, 19).split(/[-T:]/i).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > days[month - 1] || hour > 23 || minute > 59 || second > 59) fail(mode);
  return result;
}
function webURL(value: unknown, mode: Mode): string | null {
  if (value === null) return null;
  const result = text(value, mode, 2048);
  if (!result.trim()) return result; // The backend accepts blank-to-null; preserve frozen write values.
  try {
    const url = new URL(result);
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password || result.trim().match(/^https?:\/\/([^/?#]*)/i)?.[1].includes('@')) fail(mode);
  } catch { fail(mode); }
  return result;
}
function finite(value: unknown, mode: Mode): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) fail(mode); return value;
}
function array<T>(value: unknown, mode: Mode, max: number, decode: (item: unknown) => T): T[] {
  if (!Array.isArray(value) || value.length > max) fail(mode); return Array.from(value, decode);
}
function email(value: unknown, mode: Mode): string {
  const result = text(value, mode, 254, 3);
  const parts = result.split('@');
  if (parts.length !== 2 || /[\p{C}\p{Z}]/u.test(result)) fail(mode);
  const [local, domain] = parts;
  // Unquoted dot-atom syntax includes international local parts. Keep original
  // spelling: normalization here is validation-only, never a POST transformation.
  if (!local || local.startsWith('.') || local.endsWith('.') || local.includes('..')
    || !/^[A-Za-z0-9!#$%&'*+\-/=?^_`{|}~.\u0080-\u{10FFFF}]+$/u.test(local)) fail(mode);
  // Check only domain syntax; DNS/deliverability remain backend concerns. IDN
  // conversion lets Unicode labels use the same DNS-label checks as ASCII.
  if (!/^[A-Za-z0-9.\-\u0080-\u{10FFFF}]+$/u.test(domain)) fail(mode);
  const asciiDomain = domainToASCII(domain);
  const labels = asciiDomain.split('.');
  if (asciiDomain.length > 253 || labels.length < 2 || labels.some(label =>
    !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label))) fail(mode);
  return result;
}
type Kind = 'creator' | 'contact' | 'work';
const names = { creator: CREATOR_FIELDS, contact: CONTACT_FIELDS, work: WORK_FIELDS };
function field(value: unknown, name: string, mode: Mode): unknown {
  if (['public_name_confirmed', 'is_active', 'favorite'].includes(name)) return bool(value, mode);
  if (name === 'platform') return value === null ? null : platform(value, mode);
  if (name === 'email') return email(value, mode);
  if (name === 'follower_count') return value === null ? null : integer(value, mode);
  if (name === 'timestamp_seconds') return value === null ? null : finite(value, mode);
  if (name === 'game_id') return value === null ? null : identifier(value, mode);
  if (name.endsWith('_at')) return timestamp(value, mode);
  if (name.endsWith('_url') || name === 'url') return webURL(value, mode);
  if (name === 'country_code') {
    if (value === null) return null; const result = text(value, mode, 2, 2); if (!/^[A-Z]{2}$/.test(result)) fail(mode); return result;
  }
  if (name === 'languages') return array(value, mode, 100, item => text(item, mode, 255, 1));
  if (name === 'other_contacts') return array(value, mode, 100, item => {
    const raw = object(item, mode); keys(raw, ['label', 'value', 'url'], mode);
    // Nested optional defaults are omitted in frozen input, but required in a full response DTO.
    return { ...(Object.hasOwn(raw, 'label') || mode === 'response' ? { label: optionalText(raw.label, mode, 255) } : {}),
      value: text(raw.value, mode, 1024, 1), ...(Object.hasOwn(raw, 'url') || mode === 'response' ? { url: webURL(raw.url, mode) } : {}) };
  });
  if (name === 'metrics') return array(value, mode, 30, item => {
    const raw = object(item, mode); keys(raw, ['name', 'value'], mode);
    return { name: text(raw.name, mode, 128, 1), value: finite(raw.value, mode) };
  });
  if (name === 'content_type') return enumValue(value, ['unverified', 'gameplay', 'livestream', 'review', 'commentary', 'trailer', 'news', 'other'], mode);
  return optionalText(value, mode, ['description', 'source_notes', 'internal_notes', 'interest_notes', 'verification_notes', 'evidence_excerpt'].includes(name) ? 20_000 : name === 'purpose' ? 512 : 255);
}
function fields(raw: Record<string, unknown>, kind: Kind, mode: Mode, complete: boolean): Record<string, unknown> {
  return Object.fromEntries(names[kind].filter(name => complete || Object.hasOwn(raw, name)).map(name => [name, field(raw[name], name, mode)]));
}
function source(value: unknown, kind: Kind, complete = false): Record<string, unknown> {
  const raw = object(value, 'response');
  keys(raw, [...names[kind], ...(kind === 'contact' ? ['validation_state'] : [])], 'response');
  const result = fields(raw, kind, 'response', complete);
  if (Object.hasOwn(raw, 'validation_state')) result.validation_state = text(raw.validation_state, 'response', 255, 1);
  return result;
}
function workSource(value: unknown): Record<string, unknown> {
  const raw = object(value, 'response');
  const { text: recordedText, ...editableFields } = raw;
  const result = source(editableFields, 'work');
  // Imported PublicJSONObject retains source evidence, not an editable WorkField.
  if (Object.hasOwn(raw, 'text')) result.text = text(recordedText, 'response', 20_000);
  return result;
}
export type BodyKind = 'creatorCreate' | 'creatorPatch' | 'identity' | 'contactCreate' | 'contactPatch' | 'workCreate' | 'workPatch';
export function body(value: unknown, operation: BodyKind): Record<string, unknown> {
  const raw = object(value, 'input');
  if (operation === 'identity') {
    keys(raw, ['platform', 'account_id', 'profile_url', 'confirmed', 'expected_revision'], 'input');
    if (raw.confirmed !== true) fail('input');
    const result: Record<string, unknown> = { platform: platform(raw.platform, 'input'), confirmed: true, expected_revision: integer(raw.expected_revision, 'input') };
    if (Object.hasOwn(raw, 'profile_url')) result.profile_url = webURL(raw.profile_url, 'input');
    if (Object.hasOwn(raw, 'account_id')) result.account_id = account(raw.account_id);
    if (!meaningful(result.account_id) && !meaningful(result.profile_url)) fail('input'); return result;
  }
  const kind: Kind = operation.startsWith('creator') ? 'creator' : operation.startsWith('contact') ? 'contact' : 'work';
  const patch = operation.endsWith('Patch');
  const revision = operation === 'workCreate' ? 'expected_identity_revision' : 'expected_revision';
  const extras = kind === 'creator' ? ['favorite', ...(patch ? [] : ['platform', 'account_id'])] : [];
  keys(raw, [...names[kind], ...extras, ...(patch ? [revision, 'reset_fields'] : kind === 'creator' ? [] : [revision])], 'input');
  const result = fields(raw, kind, 'input', false);
  if (kind === 'creator') {
    if (Object.hasOwn(raw, 'favorite')) result.favorite = bool(raw.favorite, 'input');
    if (!patch) {
      if (Object.hasOwn(raw, 'platform')) result.platform = platform(raw.platform, 'input');
      if (Object.hasOwn(raw, 'account_id')) result.account_id = account(raw.account_id);
      if (!meaningful(result.account_id) && !meaningful(result.profile_url)) fail('input');
    }
  }
  if (!patch && kind === 'contact') result.email = email(raw.email, 'input');
  if (!patch && kind === 'work' && !['work_name', 'content_title', 'source_url'].some(key => meaningful(result[key]))) fail('input');
  if (patch || kind !== 'creator') result[revision] = integer(raw[revision], 'input');
  if (patch && Object.hasOwn(raw, 'reset_fields')) {
    result.reset_fields = array(raw.reset_fields, 'input', names[kind].length, item => {
      const name = enumValue(item, names[kind], 'input'); if (Object.hasOwn(raw, name)) fail('input'); return name;
    });
    if (new Set(result.reset_fields as string[]).size !== (result.reset_fields as string[]).length) fail('input');
  }
  return result;
}
function meaningful(value: unknown): boolean { return typeof value === 'string' && value.trim().length > 0; }
function account(value: unknown): string | null { return value === null ? null : text(value, 'input', 128, 1); }
function uniqueIDs<T extends { id: string }>(items: T[]): T[] {
  if (new Set(items.map(item => item.id.toLowerCase())).size !== items.length) fail('response'); return items;
}
/** PublicJSONObject read projection, kept separate from editable Creator/source fields. */
function analysisMetadata(value: unknown): JsonObject {
  let nodes = 0, keyCount = 0; const active = new WeakSet<object>();
  function visit(item: unknown, depth: number): JsonValue {
    if (++nodes > 10_000 || depth > 32) fail('response');
    if (item === null || typeof item === 'boolean') return item;
    if (typeof item === 'string') return text(item, 'response', 1_000_000);
    if (typeof item === 'number') { if (!Number.isFinite(item)) fail('response'); return item; }
    if (!item || typeof item !== 'object' || active.has(item)) fail('response');
    active.add(item);
    try {
      if (Array.isArray(item)) return item.map(child => visit(child, depth + 1));
      const raw = object(item, 'response'), result: JsonObject = {};
      for (const [key, child] of Object.entries(raw)) {
        if (++keyCount > 2000 || ['__proto__', 'constructor', 'prototype'].includes(key)) fail('response');
        text(key, 'response', 512); result[key] = visit(child, depth + 1);
      }
      return result;
    } finally { active.delete(item); }
  }
  object(value, 'response'); return visit(value, 0) as JsonObject;
}
function contact(value: unknown, identityRevision: number): ContactDetail {
  const raw = object(value, 'response');
  keys(raw, [...CONTACT_FIELDS, 'id', 'origin', 'source_type', 'validation_state', 'source_fields', 'manual_overrides', 'identity_revision', 'is_current_identity', 'updated_at'], 'response');
  const revision = integer(raw.identity_revision, 'response'); const current = bool(raw.is_current_identity, 'response');
  if (revision > identityRevision || current !== (revision === identityRevision)) fail('response');
  const updated = timestamp(raw.updated_at, 'response'); if (updated === null) fail('response');
  return { ...fields(raw, 'contact', 'response', true), id: identifier(raw.id, 'response'), origin: enumValue(raw.origin, ['source', 'manual'], 'response'),
    source_type: text(raw.source_type, 'response', 255, 1), validation_state: text(raw.validation_state, 'response', 255, 1),
    source_fields: source(raw.source_fields, 'contact'), manual_overrides: source(raw.manual_overrides, 'contact'), identity_revision: revision,
    is_current_identity: current, updated_at: updated } as ContactDetail;
}
export function decodeCreator(value: unknown, expectedId?: string): CreatorDetail {
  const raw = object(value, 'response');
  const summaries = ['created_at', 'updated_at', 'latest_published_at', 'recent_works', 'active_email_count', 'contact_status'] as const;
  keys(raw, [...CREATOR_FIELDS, 'id', 'platform', 'revision', 'favorite', 'source_identity', 'source_fields', 'manual_overrides', 'overridden_fields', 'contacts', 'work_count', 'last_analyzed_at', 'next_analysis_at', 'analysis_available', 'analysis', 'brief', 'source_status', ...summaries], 'response');
  const id = identifier(raw.id, 'response'); if (expectedId && id.toLowerCase() !== expectedId.toLowerCase()) fail('response');
  const identity = object(raw.source_identity, 'response'); keys(identity, ['platform', 'account_id', 'canonical_url', 'revision'], 'response');
  const identityRevision = integer(identity.revision, 'response'); const servicePlatform = platform(raw.platform, 'response');
  if (platform(identity.platform, 'response') !== servicePlatform) fail('response');
  const overridden = array(raw.overridden_fields, 'response', CREATOR_FIELDS.length, name => enumValue(name, CREATOR_FIELDS, 'response'));
  if (new Set(overridden).size !== overridden.length) fail('response');
  const optionalSummaries: Partial<Pick<CreatorDetail, typeof summaries[number]>> = {};
  if (Object.hasOwn(raw, 'created_at')) optionalSummaries.created_at = timestamp(raw.created_at, 'response');
  if (Object.hasOwn(raw, 'updated_at')) optionalSummaries.updated_at = timestamp(raw.updated_at, 'response');
  if (Object.hasOwn(raw, 'latest_published_at')) optionalSummaries.latest_published_at = timestamp(raw.latest_published_at, 'response');
  if (Object.hasOwn(raw, 'active_email_count')) optionalSummaries.active_email_count = integer(raw.active_email_count, 'response');
  if (Object.hasOwn(raw, 'contact_status')) optionalSummaries.contact_status = enumValue(raw.contact_status, ['available', 'missing'] as const, 'response');
  if (Object.hasOwn(raw, 'recent_works')) optionalSummaries.recent_works = uniqueIDs(array(raw.recent_works, 'response', 3, item => {
    const work = object(item, 'response');
    keys(work, ['id', 'work_name', 'content_title', 'source_url', 'published_at', 'content_type'], 'response');
    return { id: identifier(work.id, 'response'), work_name: optionalText(work.work_name, 'response', Number.MAX_SAFE_INTEGER),
      content_title: optionalText(work.content_title, 'response', Number.MAX_SAFE_INTEGER), source_url: optionalText(work.source_url, 'response', Number.MAX_SAFE_INTEGER),
      published_at: timestamp(work.published_at, 'response'), content_type: text(work.content_type, 'response', Number.MAX_SAFE_INTEGER) } satisfies RecentWorkSummary;
  }));
  return { ...fields(raw, 'creator', 'response', true), id, platform: servicePlatform,
    revision: integer(raw.revision, 'response'), favorite: bool(raw.favorite, 'response'),
    source_identity: { platform: servicePlatform, account_id: optionalText(identity.account_id, 'response', 128), canonical_url: webURL(identity.canonical_url, 'response'), revision: identityRevision },
    source_fields: source(raw.source_fields, 'creator', true) as unknown as CreatorFields,
    manual_overrides: source(raw.manual_overrides, 'creator'), overridden_fields: overridden,
    contacts: uniqueIDs(array(raw.contacts, 'response', Number.MAX_SAFE_INTEGER, item => contact(item, identityRevision))),
    work_count: integer(raw.work_count, 'response'), last_analyzed_at: timestamp(raw.last_analyzed_at, 'response'),
    next_analysis_at: timestamp(raw.next_analysis_at, 'response'), analysis_available: bool(raw.analysis_available, 'response'), ...optionalSummaries,
    ...Object.fromEntries(['analysis', 'brief', 'source_status'].filter(key => Object.hasOwn(raw, key)).map(key => [key, analysisMetadata(raw[key])])) } as CreatorDetail;
}
export function decodeWork(value: unknown, creatorId: string, expectedId?: string): WorkDetail {
  const raw = object(value, 'response');
  keys(raw, [...WORK_FIELDS, 'id', 'creator_id', 'source_platform', 'origin', 'revision', 'identity_revision', 'is_current_identity', 'source_content_id', 'source_collected_at', 'source_fields', 'manual_overrides'], 'response');
  const id = identifier(raw.id, 'response');
  if ((expectedId && id.toLowerCase() !== expectedId.toLowerCase()) || identifier(raw.creator_id, 'response').toLowerCase() !== creatorId.toLowerCase()) fail('response');
  return { ...fields(raw, 'work', 'response', true), id, creator_id: raw.creator_id, platform: platform(raw.platform, 'response'),
    source_platform: platform(raw.source_platform, 'response'), origin: enumValue(raw.origin, ['source', 'manual'], 'response'),
    revision: integer(raw.revision, 'response'), identity_revision: integer(raw.identity_revision, 'response'), is_current_identity: bool(raw.is_current_identity, 'response'),
    source_content_id: optionalText(raw.source_content_id, 'response', 255), source_collected_at: timestamp(raw.source_collected_at, 'response'),
    source_fields: workSource(raw.source_fields), manual_overrides: source(raw.manual_overrides, 'work') } as WorkDetail;
}
export function decodePage<T extends { id: string }>(value: unknown, decode: (item: unknown) => T): { items: T[]; total: number; limit: number; offset: number } {
  const raw = object(value, 'response'); keys(raw, ['items', 'total', 'limit', 'offset'], 'response');
  const total = integer(raw.total, 'response'), limit = integer(raw.limit, 'response', 1, 100), offset = integer(raw.offset, 'response');
  const items = uniqueIDs(array(raw.items, 'response', limit, decode));
  if (items.length > total) fail('response'); return { items, total, limit, offset };
}
