import type { SteamRecommendations } from '../shared/games';
import { PublicFailure } from './transport';
function fail(): never { throw new PublicFailure('invalid_response', 'The service returned unsupported Steam recommendation metadata.', false); }
function sourceURL(value: unknown) {
  if (value === null) return;
  if (typeof value !== 'string' || value.length > 2048) fail();
  try { const url = new URL(value); if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) fail(); } catch { fail(); }
}
export function validateReferenceSource(raw: Record<string, unknown>) {
  if (Object.hasOwn(raw, 'source') && !['manual', 'steam_more_like_this'].includes(raw.source as string)) fail();
  if (Object.hasOwn(raw, 'source_url')) sourceURL(raw.source_url);
}
export function decodeSteamRecommendations(value: unknown): SteamRecommendations {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail();
  const r = value as Record<string, unknown>, names = ['status', 'source_url', 'fetched_at'];
  if (Object.keys(r).some(key => !names.includes(key)) || names.some(key => !Object.hasOwn(r, key))) fail();
  if (!['not_fetched', 'available', 'partial', 'unavailable'].includes(r.status as string)) fail();
  sourceURL(r.source_url);
  if (r.fetched_at !== null && (typeof r.fetched_at !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(r.fetched_at) || !Number.isFinite(Date.parse(r.fetched_at)))) fail();
  return r as unknown as SteamRecommendations;
}
