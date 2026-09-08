import { GAME_FIELDS, type GameCreate, type GameDetail, type GameField, type GameFields, type GamePatch, type ReferenceWork } from '../../shared/games';

export const gameLabels: Record<GameField, string> = {
  name: 'Name', website_url: 'Website URL', steam_app_id: 'Steam ID', developer: 'Developer',
  description: 'Description', tags: 'Tags', languages: 'Languages', release_date: 'Release date', cover_url: 'Cover URL',
};
export interface ReferenceDraft { localId: string; id?: string | null; name: string; url: string; similarities: string; reason: string }
export interface GameDraft { fields: Record<GameField, string>; touched: GameField[]; favorite: boolean; references: ReferenceDraft[]; referencesTouched: boolean; resets: GameField[] }
export type ChangeKey = GameField | 'favorite' | 'reference_works';
export type ConflictChoices = Partial<Record<ChangeKey, 'mine' | 'latest'>>;
export const IDEMPOTENCY_WINDOW_MS = 24 * 60 * 60 * 1000;

export function newRequestKey() { return crypto.randomUUID(); }
export function newReference(reference?: ReferenceWork): ReferenceDraft {
  return { localId: newRequestKey(), ...(reference?.id ? { id: reference.id } : {}), name: reference?.name ?? '', url: reference?.url ?? '', similarities: reference?.similarities.join('\n') ?? '', reason: reference?.reason ?? '' };
}
export function displayField(value: GameFields[GameField]): string { return Array.isArray(value) ? value.join('\n') : value ?? ''; }
export function draftFrom(game: GameDetail | null): GameDraft {
  return { fields: Object.fromEntries(GAME_FIELDS.map(field => [field, game ? displayField(game[field]) : ''])) as Record<GameField, string>, touched: [], favorite: game?.favorite ?? false, references: game?.reference_works.map(newReference) ?? [], referencesTouched: false, resets: [] };
}
export function listValue(value: string) { return value.split(/\r?\n/).map(item => item.trim()).filter(Boolean); }
export function referenceValue(draft: ReferenceDraft): ReferenceWork {
  return { ...(draft.id ? { id: draft.id } : {}), name: draft.name.trim() || null, url: draft.url.trim() || null, similarities: listValue(draft.similarities), reason: draft.reason.trim() || null };
}
export function fieldValue(draft: GameDraft, field: GameField): GameFields[GameField] {
  return field === 'tags' || field === 'languages' ? listValue(draft.fields[field]) : draft.fields[field].trim() || null;
}
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);

export function createData(draft: GameDraft): GameCreate {
  const entries = GAME_FIELDS.map(field => [field, fieldValue(draft, field)] as const).filter(([, value]) => Array.isArray(value) ? value.length : value !== null);
  return { ...Object.fromEntries(entries), ...(draft.favorite ? { favorite: true } : {}), ...(draft.references.length ? { reference_works: draft.references.map(referenceValue) } : {}) };
}
export function patchData(base: GameDetail, draft: GameDraft): GamePatch {
  const entries = GAME_FIELDS.filter(field => draft.touched.includes(field) && !draft.resets.includes(field) && !equal(fieldValue(draft, field), base[field])).map(field => [field, fieldValue(draft, field)]);
  const originalReferences = base.reference_works.map(reference => referenceValue({ localId: '', ...reference, name: reference.name ?? '', url: reference.url ?? '', similarities: reference.similarities.join('\n'), reason: reference.reason ?? '' }));
  const references = draft.references.map(referenceValue);
  return { expected_revision: base.revision, ...Object.fromEntries(entries), ...(draft.resets.length ? { reset_fields: [...draft.resets] } : {}), ...(draft.favorite !== base.favorite ? { favorite: draft.favorite } : {}), ...(draft.referencesTouched && !equal(originalReferences, references) ? { reference_works: references } : {}) };
}
export function changedKeys(base: GameDetail, draft: GameDraft): ChangeKey[] {
  const patch = patchData(base, draft);
  return [...GAME_FIELDS.filter(field => Object.hasOwn(patch, field) || draft.resets.includes(field)), ...(['favorite', 'reference_works'] as const).filter(field => Object.hasOwn(patch, field))];
}
export function isDirty(base: GameDetail | null, draft: GameDraft): boolean { return base ? changedKeys(base, draft).length > 0 : Object.keys(createData(draft)).length > 0 || draft.references.length > 0; }
export function changeLabel(key: ChangeKey) { return key === 'favorite' ? 'Saved' : key === 'reference_works' ? 'Reference works' : gameLabels[key]; }
export function localChangeValue(draft: GameDraft, key: ChangeKey): unknown { return key === 'favorite' ? draft.favorite : key === 'reference_works' ? draft.references.map(referenceValue) : fieldValue(draft, key); }
export function comparisonValue(value: unknown): string {
  if (value === null || value === '') return 'Empty';
  if (typeof value === 'boolean') return value ? 'Saved' : 'Not saved';
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)).join('\n') : 'Empty list';
  return String(value);
}
export function resolveDraft(base: GameDetail, draft: GameDraft, latest: GameDetail, choices: ConflictChoices): GameDraft {
  const resolved = draftFrom(latest);
  for (const key of changedKeys(base, draft)) {
    if (choices[key] !== 'mine') continue;
    if (key === 'favorite') resolved.favorite = draft.favorite;
    else if (key === 'reference_works') { resolved.references = draft.references.map(reference => ({ ...reference })); resolved.referencesTouched = true; }
    else if (draft.resets.includes(key)) { resolved.resets.push(key); resolved.fields[key] = displayField(latest.source_fields[key]); }
    else { resolved.fields[key] = draft.fields[key]; resolved.touched.push(key); }
  }
  return resolved;
}
export function validWebURL(value: string) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && Boolean(url.hostname) && !url.username && !url.password; } catch { return false; }
}
export function validateDraft(draft: GameDraft, base: GameDetail | null = null): Record<string, string> {
  const errors: Record<string, string> = {};
  const submittedKeys = base ? changedKeys(base, draft) : null;
  if ((!submittedKeys || submittedKeys.includes('name') || submittedKeys.includes('website_url')) && !draft.fields.name.trim() && !draft.fields.website_url.trim()) errors.name = 'Enter a name or website URL.';
  for (const field of GAME_FIELDS) {
    if (submittedKeys && !submittedKeys.includes(field)) continue;
    const value = draft.fields[field].trim();
    const maximum = field === 'description' ? 20000 : ['website_url', 'cover_url'].includes(field) ? 2048 : 255;
    if (field === 'tags' || field === 'languages') { const items = listValue(value); if (items.length > 100 || items.some(item => item.length > 255)) errors[field] = 'Use up to 100 entries, each at most 255 characters.'; }
    else if (value.length > maximum) errors[field] = `Use at most ${maximum.toLocaleString()} characters.`;
    if (value && ['website_url', 'cover_url'].includes(field) && !validWebURL(value)) errors[field] = 'Use an HTTP(S) URL without a username or password.';
    if (field === 'steam_app_id' && value && !/^[1-9][0-9]{0,19}$/.test(value)) errors[field] = 'Use a numeric Steam ID (1–20 digits).';
  }
  const validatesReferences = !submittedKeys || submittedKeys.includes('reference_works');
  if (validatesReferences && draft.references.length > 100) errors.references = 'Use up to 100 reference works.';
  if (validatesReferences) draft.references.forEach((reference, index) => {
    const prefix = `reference-${reference.localId}`;
    if (!reference.name.trim() && !reference.url.trim()) errors[`${prefix}-name`] = `Reference ${index + 1} needs a name or URL.`;
    if (reference.name.trim().length > 255) errors[`${prefix}-name`] = 'Use at most 255 characters.';
    if (reference.url.trim() && (!validWebURL(reference.url.trim()) || reference.url.trim().length > 2048)) errors[`${prefix}-url`] = 'Use an HTTP(S) URL without credentials, at most 2,048 characters.';
    if (reference.reason.trim().length > 20000) errors[`${prefix}-reason`] = 'Use at most 20,000 characters.';
    const similarities = listValue(reference.similarities);
    if (similarities.length > 100 || similarities.some(item => item.length > 255)) errors[`${prefix}-similarities`] = 'Use up to 100 entries, each at most 255 characters.';
  });
  return errors;
}
