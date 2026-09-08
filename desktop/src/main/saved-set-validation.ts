import type { SavedSetCreate, SavedSetView } from '../shared/savedSets';
import { timestamp } from './creator-validation';
import { fail, identifier, integer, keys, object, sameID, text, type Mode } from './match-validation';

function members(value: unknown, mode: Mode): string[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 600) fail(mode);
  return Array.from(value, item => identifier(item, mode));
}
function name(value: unknown, mode: Mode): string {
  const result = text(value, mode, 255, 1);
  if (!result.trim() || (mode === 'response' && result !== result.trim())) fail(mode);
  return result;
}
export function validateSavedSetBody(value: unknown): SavedSetCreate {
  const raw = object(value, 'input');
  keys(raw, ['request_id', 'name', 'candidate_ids'], 'input');
  const decoded: SavedSetCreate = { request_id: identifier(raw.request_id, 'input'), name: name(raw.name, 'input'), candidate_ids: members(raw.candidate_ids, 'input') };
  // Validation never trims, deduplicates, recases, or reorders the frozen POST.
  return Object.fromEntries(Object.keys(raw).map(key => [key, decoded[key as keyof SavedSetCreate]])) as unknown as SavedSetCreate;
}
export function decodeSavedSet(value: unknown, expected: { id?: string; queryId?: string; activityId?: string; input?: SavedSetCreate } = {}): SavedSetView {
  const raw = object(value, 'response');
  keys(raw, ['id', 'query_id', 'activity_id', 'name', 'candidate_ids', 'count', 'created_at'], 'response');
  const candidateIds = members(raw.candidate_ids, 'response');
  const count = integer(raw.count, 'response', 1, 600);
  if (count !== candidateIds.length || new Set(candidateIds.map(id => id.toLowerCase())).size !== count) fail('response');
  const createdAt = timestamp(raw.created_at, 'response');
  if (createdAt === null) fail('response');
  const result: SavedSetView = {
    id: identifier(raw.id, 'response'), query_id: identifier(raw.query_id, 'response'), activity_id: identifier(raw.activity_id, 'response'),
    name: name(raw.name, 'response'), candidate_ids: candidateIds, count, created_at: createdAt,
  };
  sameID(result.id, expected.id); sameID(result.query_id, expected.queryId); sameID(result.activity_id, expected.activityId);
  if (expected.input) {
    const wanted = [...new Set(expected.input.candidate_ids.map(id => id.toLowerCase()))];
    if (result.name !== expected.input.name.trim() || result.count !== wanted.length
      || result.candidate_ids.some((id, index) => id.toLowerCase() !== wanted[index])) fail('response');
  }
  return result;
}
