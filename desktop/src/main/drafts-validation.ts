import { createHash } from 'node:crypto';
import type * as DTO from '../shared/drafts';
import type { JsonObject } from '../shared/library';
import { GAME_FIELDS } from '../shared/games';
import { decodeSteamRecommendations, validateReferenceSource } from './game-provenance-validation';
import { PublicFailure } from './transport';
export { identifier, integer, object, keys } from './outreach-validation';
import { identifier, integer, object, keys } from './outreach-validation';
type Mode = 'input' | 'response';
export const SLOT_KEYS = ['firstName', 'channelName', 'reference', 'observation'] as const;
export const CANONICAL_FIXED_HASH = '0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93';
const RAW_HASH = '6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd';
export function fail(mode: Mode): never { throw new PublicFailure(mode === 'input' ? 'request_invalid' : 'invalid_response', mode === 'input' ? 'Check the template, draft values, and recorded revisions.' : 'The service returned unsupported draft data.', false); }
export function exact(value: unknown, names: readonly string[], mode: Mode) { const raw = object(value, mode); keys(raw, names, mode); if (names.some(k => !Object.hasOwn(raw, k))) fail(mode); return raw; }
export function text(value: unknown, mode: Mode, max = 100_000, min = 0): string { if (typeof value !== 'string' || [...value].length > max || [...value].length < min) fail(mode); return value; }
export function token(value: unknown, mode: Mode): string { const v = text(value, mode, 64, 64); if (!/^[a-f0-9]{64}$/.test(v)) fail(mode); return v; }
const bool = (v: unknown, m: Mode): boolean => typeof v === 'boolean' ? v : fail(m);
const nullable = (v: unknown, m: Mode, max = 100_000) => v === null ? null : text(v, m, max);
export function same(a: string, b: string) { return a.toLowerCase() === b.toLowerCase(); }
export function unique(ids: string[], m: Mode) { if (new Set(ids.map(v => v.toLowerCase())).size !== ids.length) fail(m); }
function list<T>(v: unknown, m: Mode, max: number, decode: (v: unknown) => T, min = 0): T[] { if (!Array.isArray(v) || v.length < min || v.length > max) fail(m); return v.map(decode); }
export function stamp(v: unknown): string { const s = text(v, 'response', 100, 1); if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(s) || !Number.isFinite(Date.parse(s))) fail('response'); return s; }
export function slots(v: unknown, m: Mode): DTO.SlotValues {
  const values = draftSlots(v, m);
  if (SLOT_KEYS.some(key => !values[key]) || !values.observation.endsWith('.')) fail(m);
  return values;
}
export function draftSlots(v: unknown, m: Mode): DTO.SlotValues {
  const raw = exact(v, SLOT_KEYS, m);
  for (const key of SLOT_KEYS) { const s = text(raw[key], m, 600); if (s !== s.trim() || /[\x00-\x1f\x7f<>{}]/.test(s) || /\[(?:first name|channel name|reference game\s*\/\s*video|unfilled[^\]]*|specific observation[^\]]*)\]/i.test(s)) fail(m); }
  // Persistence and preview accept unfinished text. Qualification owns completeness.
  return raw as unknown as DTO.SlotValues;
}
/** Parse the small immutable HTML grammar without a browser or HTML repair. Slots must occur in text. */
export function fixed(subject: unknown, fragments: unknown, m: Mode): string {
  const s = text(subject, m, 998, 1); if (!s.trim() || /[\x00-\x1f\x7f]/.test(s)) fail(m);
  const parts = list(fragments, m, 5, v => text(v, m), 5); const body = parts.join('<slot/>');
  if ([...body].length > 100_000 || /\{\{|\}\}/.test(body)) fail(m);
  const stack: string[] = []; let count = 0, cursor = 0;
  const tag = /<[^>]*>/g; let match: RegExpExecArray | null;
  while ((match = tag.exec(body))) {
    if (body.slice(cursor, match.index).includes('<')) fail(m); cursor = tag.lastIndex;
    if (match[0] === '<slot/>') { count++; continue; }
    const parsed = /^<(\/)?(p|b|strong|em|i|a|br)(\s[^<>]*)?(\/?)>$/i.exec(match[0]); if (!parsed) fail(m);
    const [, closing, nameRaw, attrs = '', self] = parsed, name = nameRaw.toLowerCase();
    if (closing) { if (attrs || self || stack.pop() !== name) fail(m); continue; }
    if (attrs.trim()) {
      if (name !== 'a') fail(m); let remainder = attrs; const seen = new Set<string>();
      while (remainder.trim()) { const attr = /^\s+(href|title)\s*=\s*(?:"([^"<>]*)"|'([^'<>]*)')/i.exec(remainder); if (!attr || seen.has(attr[1].toLowerCase())) fail(m); seen.add(attr[1].toLowerCase());
        if (attr[1].toLowerCase() === 'href' && !/^https?:\/\//i.test(attr[2] ?? attr[3])) fail(m); remainder = remainder.slice(attr[0].length); }
    }
    if (name !== 'br' && !self) stack.push(name);
  }
  if (body.slice(cursor).includes('<') || stack.length || count !== 4) fail(m);
  return createHash('sha256').update(s + '\n' + body).digest('hex');
}
export type BodyKind = 'canonical' | 'template' | 'composition' | 'edit' | 'revision' | 'facts';
export function draftsBody(v: unknown, kind: BodyKind): Record<string, unknown> {
  const m = 'input';
  if (kind === 'canonical') { const r = exact(v, ['game_id'], m); identifier(r.game_id, m); return r; }
  if (kind === 'template') { const r = exact(v, ['game_id', 'request_id', 'name', 'subject', 'fixed_fragments'], m); identifier(r.game_id, m); identifier(r.request_id, m); if (!text(r.name, m, 255, 1).trim()) fail(m); fixed(r.subject, r.fixed_fragments, m); return r; }
  if (kind === 'composition') { const r = exact(v, ['request_id', 'recipient_batch_id', 'template_version_id'], m); Object.values(r).forEach(id => identifier(id, m)); return r; }
  if (kind === 'facts') { const r = exact(v, ['members', 'following', 'enjoyed', 'liked'], m); const members = list(r.members, m, 600, v => { const member = exact(v, ['draft_id', 'expected_revision', 'context_token'], m); identifier(member.draft_id, m); integer(member.expected_revision, m); token(member.context_token, m); return member; }, 1); unique(members.map(v => v.draft_id as string), m); for (const k of ['following', 'enjoyed', 'liked']) bool(r[k], m); return r; }
  const r = exact(v, ['expected_revision', 'context_token', ...(kind === 'edit' ? ['values'] : [])], m); integer(r.expected_revision, m); token(r.context_token, m); if (kind === 'edit') draftSlots(r.values, m); return r;
}
function content(v: unknown, extra: string[]): Record<string, unknown> {
  const m = 'response', r = exact(v, ['name', 'subject', 'fixed_fragments', 'fixed_hash', 'source_metadata', ...extra], m);
  text(r.name, m, 255, 1); if (fixed(r.subject, r.fixed_fragments, m) !== token(r.fixed_hash, m)) fail(m);
  const source = object(r.source_metadata,m),base=['kind','document_id','revision','steam_app_id','raw_hash'],bound=['game_id','game_revision','game_fingerprint','sender_name'];
  keys(source,[...base,...bound],m);if(base.some(key=>!Object.hasOwn(source,key)))fail(m);
  if(source.kind==='game_bound'){
    if(bound.some(key=>!Object.hasOwn(source,key))||source.revision!==1||source.document_id!==null||source.raw_hash!==null)fail(m);
    identifier(source.game_id,m);integer(source.game_revision,m);token(source.game_fingerprint,m);nullable(source.steam_app_id,m,255);nullable(source.sender_name,m,1024);
  }else{
    if(bound.some(key=>Object.hasOwn(source,key)&&source[key]!==null))fail(m);
    if (source.kind === 'canonical') { if (source.document_id !== 'Ieqid5pULoUSqMxOtKTc156xnLe' || source.revision !== 69 || source.steam_app_id !== '4952700' || source.raw_hash !== RAW_HASH || r.fixed_hash !== CANONICAL_FIXED_HASH) fail(m); }
    else if (source.kind !== 'user_saved' || ['document_id', 'revision', 'steam_app_id', 'raw_hash'].some(k => source[k] !== null)) fail(m);
  }
  return r;
}
export function decodeTemplate(v: unknown, id?: string, gameId?: string): DTO.TemplateVersion { const r = content(v, ['id', 'game_id', 'created_at']); const actual = identifier(r.id, 'response'), game = identifier(r.game_id, 'response'); if ((id && !same(id, actual)) || (gameId && !same(gameId, game))) fail('response'); if((r.source_metadata as DTO.TemplateSource).kind==='game_bound'&&!same((r.source_metadata as DTO.TemplateSource).game_id!,game))fail('response'); stamp(r.created_at); return r as unknown as DTO.TemplateVersion; }
export function decodeCatalog(v: unknown, gameId: string): DTO.TemplateCatalog { const r = exact(v, ['items', 'builtin'], 'response'); const items = list(r.items, 'response', 10_000, v => decodeTemplate(v, undefined, gameId)); unique(items.map(v => v.id), 'response'); const builtin = content(r.builtin, ['key', 'requires_explicit_registration']); const source=builtin.source_metadata as DTO.TemplateSource; if(builtin.requires_explicit_registration!==true)fail('response');if(source.kind==='game_bound'){if(builtin.key!=='game-outreach-v1'||!same(source.game_id!,gameId))fail('response');}else if(builtin.key!=='liminal-revision-69'||source.kind!=='canonical')fail('response'); return { items, builtin: builtin as unknown as DTO.BuiltinTemplate }; }
export function jsonObject(v: unknown): JsonObject { let nodes = 0; const seen = new WeakSet<object>(); function check(v: unknown, depth: number): void { if (++nodes > 20_000 || depth > 20) fail('response'); if (v === null || typeof v === 'boolean') return; if (typeof v === 'string') { text(v, 'response', 1_000_000); return; } if (typeof v === 'number') { if (!Number.isFinite(v)) fail('response'); return; } if (typeof v !== 'object' || seen.has(v)) fail('response'); seen.add(v); if (Array.isArray(v)) { if (v.length > 10_000) fail('response'); v.forEach(i => check(i, depth + 1)); } else for (const [k, item] of Object.entries(object(v, 'response'))) { if (['__proto__', 'constructor', 'prototype'].includes(k)) fail('response'); text(k, 'response', 512); check(item, depth + 1); } seen.delete(v); } object(v, 'response'); check(v, 0); return v as JsonObject; }
function work(v: unknown) {
  const base = ['id', 'source_url', 'content_title', 'work_name', 'evidence_excerpt', 'verification_notes', 'timestamp_seconds'];
  const metadata = ['game_id', 'relation', 'evidence_status', 'evidence_tier'];
  const raw = object(v, 'response');
  // Immutable historical snapshots have seven fields; new snapshots carry all metadata.
  const extended = metadata.some(key => Object.hasOwn(raw, key));
  const evidenceKeys = Object.hasOwn(raw, 'evidence_kind') ? ['evidence_kind'] : [];
  const r = exact(raw, [...base, ...(extended ? metadata : []), ...evidenceKeys], 'response');
  if (evidenceKeys.length && !['manual_note', 'metadata', 'unavailable'].includes(r.evidence_kind as string)) fail('response');
  if (r.id !== null) identifier(r.id, 'response');
  for (const k of ['source_url', 'content_title', 'work_name', 'evidence_excerpt', 'verification_notes']) nullable(r[k], 'response');
  if (r.timestamp_seconds !== null && (typeof r.timestamp_seconds !== 'number' || !Number.isFinite(r.timestamp_seconds) || r.timestamp_seconds < 0)) fail('response');
  if (extended) {
    if (r.game_id !== null) identifier(r.game_id, 'response');
    if (r.relation !== null && !['current_game', 'reference_game', 'related_content'].includes(r.relation as string)) fail('response');
    if (r.evidence_status !== null && !['recorded_evidence', 'metadata_only'].includes(r.evidence_status as string)) fail('response');
    if (!['current_game', 'reference_game', 'related_content', 'unverified'].includes(r.evidence_tier as string)) fail('response');
  }
  return r;
}
export function sources(v: unknown) { const r = exact(v, SLOT_KEYS, 'response'), first = exact(r.firstName, ['source_url', 'confirmed'], 'response'), channel = exact(r.channelName, ['source_url'], 'response'); nullable(first.source_url, 'response', 2048); bool(first.confirmed, 'response'); nullable(channel.source_url, 'response', 2048); work(r.reference); work(r.observation); return r; }
function recordedGame(v: unknown) {
  const r = object(v, 'response'); keys(r, [...GAME_FIELDS, 'id', 'revision', 'favorite', 'reference_works', 'source_fields', 'manual_overrides', 'overridden_fields', 'source_identity', 'last_analyzed_at', 'next_analysis_at', 'created_at', 'updated_at', 'steam_recommendations'], 'response');
  if (Object.hasOwn(r, 'steam_recommendations')) decodeSteamRecommendations(r.steam_recommendations);
  identifier(r.id, 'response'); integer(r.revision, 'response'); bool(r.favorite, 'response');
  function fields(v: unknown) { const f = object(v, 'response'); keys(f, GAME_FIELDS, 'response'); for (const k of GAME_FIELDS) if (Object.hasOwn(f, k)) { if (k === 'tags' || k === 'languages') list(f[k], 'response', 100, v => text(v, 'response', 255, 1)); else nullable(f[k], 'response'); } }
  fields(Object.fromEntries(GAME_FIELDS.filter(k => Object.hasOwn(r, k)).map(k => [k, r[k]]))); fields(r.source_fields); jsonObject(r.manual_overrides);
  list(r.overridden_fields, 'response', 9, v => { if (!GAME_FIELDS.includes(v as typeof GAME_FIELDS[number])) fail('response'); return v; });
  const identity = exact(r.source_identity, ['steam_app_id', 'canonical_url'], 'response'); Object.values(identity).forEach(v => nullable(v, 'response', 2048));
  list(r.reference_works, 'response', 10_000, v => { const ref = object(v, 'response'); keys(ref, ['id', 'name', 'url', 'similarities', 'reason', 'source', 'source_url'], 'response'); validateReferenceSource(ref); if (ref.id != null) identifier(ref.id, 'response'); for (const k of ['name', 'url', 'reason']) if (Object.hasOwn(ref, k)) nullable(ref[k], 'response'); list(ref.similarities, 'response', 100, v => text(v, 'response', 255)); return ref; });
  for (const k of ['last_analyzed_at', 'next_analysis_at', 'created_at', 'updated_at']) if (r[k] != null) stamp(r[k]);
}
function recordedContact(v: unknown) { const r = exact(v, ['id', 'email', 'purpose', 'source_url', 'source_type', 'source_fields', 'manual_overrides', 'validation_state', 'identity_revision', 'updated_at', 'status'], 'response'); identifier(r.id, 'response'); text(r.email, 'response', 254, 3); nullable(r.purpose, 'response', 512); nullable(r.source_url, 'response', 2048); text(r.source_type, 'response', 255, 1); text(r.validation_state, 'response', 255, 1); jsonObject(r.source_fields); jsonObject(r.manual_overrides); integer(r.identity_revision, 'response'); stamp(r.updated_at); if (!['eligible', 'inactive', 'invalid', 'historical'].includes(r.status as string)) fail('response'); }
function draftInput(v: unknown, selectionId: string): JsonObject { const raw = object(v, 'response'); const extra = Object.hasOwn(raw, 'prefill_values') ? ['prefill_values'] : []; const r = exact(raw, [...extra, 'selection_id', 'identity', 'active', 'identity_changed', 'public_name', 'public_name_confirmed', 'channel_name', 'profile_url', 'reference', 'work', 'game', 'selected_contact', 'contact_status', 'template_version_id', 'fixed_hash', 'sender', 'missing_fields', 'slot_sources'], 'response'); jsonObject(r); if (extra.length) draftSlots(r.prefill_values, 'response'); if (!same(identifier(r.selection_id, 'response'), selectionId)) fail('response'); identifier(r.template_version_id, 'response'); token(r.fixed_hash, 'response'); const identity = exact(r.identity, ['platform', 'account_id', 'revision'], 'response'); if (!['youtube', 'x', 'twitch', 'instagram'].includes(identity.platform as string)) fail('response'); text(identity.account_id, 'response', 512, 1); integer(identity.revision, 'response'); for (const k of ['active', 'identity_changed', 'public_name_confirmed']) bool(r[k], 'response'); for (const k of ['public_name', 'channel_name', 'profile_url', 'reference']) nullable(r[k], 'response'); work(r.work); const game = object(r.game, 'response'); identifier(game.id, 'response'); integer(game.revision, 'response'); if (r.selected_contact !== null) { const c = object(r.selected_contact, 'response'); identifier(c.id, 'response'); text(c.email, 'response', 254, 3); integer(c.identity_revision, 'response'); } if (!['not_selected', 'eligible', 'changed', 'inactive', 'invalid', 'historical', 'missing'].includes(r.contact_status as string)) fail('response'); const sender = exact(r.sender, ['username', 'from_name', 'reply_to'], 'response'); Object.values(sender).forEach(v => nullable(v, 'response', 1024)); list(r.missing_fields, 'response', 100, v => text(v, 'response', 255)); sources(r.slot_sources); return r as JsonObject; }
export function decodeDraft(v: unknown, id?: string, compositionId?: string): DTO.DraftView {
  const m = 'response', r = exact(v, ['id', 'composition_id', 'recipient_snapshot_id', 'selection_id', 'input_order', 'revision', 'context_token', 'source_changed', 'status', 'error_code', 'input', 'values', 'missing_fields', 'slot_sources', 'rendered', 'sender_facts_valid', 'sender_facts', 'send_ready'], m);
  const actual = identifier(r.id, m), composition = identifier(r.composition_id, m), selection = identifier(r.selection_id, m); identifier(r.recipient_snapshot_id, m); if ((id && !same(id, actual)) || (compositionId && !same(compositionId, composition))) fail(m);
  integer(r.input_order, m, 0, 599); integer(r.revision, m); token(r.context_token, m); bool(r.source_changed, m); bool(r.sender_facts_valid, m); if (r.send_ready !== false || !['pending', 'running', 'succeeded', 'failed', 'needs_repair'].includes(r.status as string)) fail(m); nullable(r.error_code, m, 255);
  const input = draftInput(r.input, selection); recordedGame(input.game); if (input.selected_contact !== null) recordedContact(input.selected_contact); sources(r.slot_sources); if (JSON.stringify(r.slot_sources) !== JSON.stringify(input.slot_sources)) fail(m);
  list(r.missing_fields, m, 100, v => text(v, m, 255)); const facts = jsonObject(r.sender_facts); if (Object.keys(facts).length) { exact(facts, ['following', 'enjoyed', 'liked', 'at', 'fingerprint'], m); for (const k of ['following', 'enjoyed', 'liked']) bool(facts[k], m); stamp(facts.at); token(facts.fingerprint, m); }
  if (r.values !== null) {
    if (r.status === 'succeeded') slots(r.values, m);
    else draftSlots(r.values, m);
  }
  if ((r.values === null) !== (r.rendered === null) || (r.status === 'succeeded' && r.values === null)) fail(m);
  if (r.rendered !== null) { const rendered = exact(r.rendered, ['subject', 'html', 'text', 'fixed_hash'], m); text(rendered.subject, m, 998, 1); text(rendered.html, m, 120_000); text(rendered.text, m, 120_000); if (token(rendered.fixed_hash, m) !== input.fixed_hash) fail(m);
    const html = rendered.html as string, marked = /<span background-color="rgba\(255,246,122,0\.8\)">(.*?)<\/span>/gs; const matches = [...html.matchAll(marked)]; const values = r.values as DTO.SlotValues;
    const escape = (s: string) => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#x27;');
    if (matches.length !== 4 || matches.some((v, i) => v[1] !== escape(values[SLOT_KEYS[i]])) || fixed(rendered.subject, html.split(marked).filter((_, i) => i % 2 === 0), m) !== input.fixed_hash) fail(m);
  }
  if (r.sender_facts_valid && (r.source_changed || r.status !== 'succeeded' || !['following', 'enjoyed', 'liked'].every(k => facts[k] === true))) fail(m);
  return r as unknown as DTO.DraftView;
}
export function decodeComposition(v: unknown, id?: string, activityId?: string): DTO.CompositionView { const m = 'response', r = exact(v, ['id', 'activity_id', 'recipient_batch_id', 'template_version_id', 'created_at', 'recipient_count', 'drafts', 'send_ready'], m); const actual = identifier(r.id, m), activity = identifier(r.activity_id, m), template = identifier(r.template_version_id, m); identifier(r.recipient_batch_id, m); if ((id && !same(id, actual)) || (activityId && !same(activityId, activity)) || r.send_ready !== false) fail(m); stamp(r.created_at); const count = integer(r.recipient_count, m, 1, 600), drafts = list(r.drafts, m, 600, v => decodeDraft(v, undefined, actual), 1); if (drafts.length !== count || drafts.some((d, i) => d.input_order !== i || !same(d.input.template_version_id as string, template))) fail(m); for (const k of ['id', 'selection_id', 'recipient_snapshot_id'] as const) unique(drafts.map(d => d[k]), m); return { ...r, drafts } as unknown as DTO.CompositionView; }
export function decodePage(v: unknown, activityId: string, offset: number, limit: number): DTO.CompositionPage { const r = exact(v, ['items', 'total', 'limit', 'offset'], 'response'); if (r.offset !== offset || r.limit !== limit) fail('response'); const items = list(r.items, 'response', limit, v => decodeComposition(v, undefined, activityId)), total = integer(r.total, 'response'); unique(items.map(v => v.id), 'response'); if (items.length > Math.max(0, total - offset)) fail('response'); return { items, total, offset, limit }; }
