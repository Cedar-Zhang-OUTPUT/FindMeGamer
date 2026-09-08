import type { JsonObject } from './library';

/** v2 business DTOs. Snake case deliberately matches the final backend contract. */
export interface GameFields {
  name: string | null;
  website_url: string | null;
  steam_app_id: string | null;
  developer: string | null;
  description: string | null;
  tags: string[];
  languages: string[];
  release_date: string | null;
  cover_url: string | null;
}
export type GameField = keyof GameFields;
export const GAME_FIELDS: GameField[] = ['name', 'website_url', 'steam_app_id', 'developer', 'description', 'tags', 'languages', 'release_date', 'cover_url'];
export interface ReferenceWork { id?: string | null; name?: string | null; url?: string | null; similarities: string[]; reason?: string | null }
export interface GameDetail extends GameFields {
  id: string;
  revision: number;
  favorite: boolean;
  reference_works: ReferenceWork[];
  source_fields: GameFields;
  manual_overrides: JsonObject;
  overridden_fields: GameField[];
  source_identity: { steam_app_id: string | null; canonical_url: string | null };
  last_analyzed_at: string | null;
  next_analysis_at: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}
export interface GamePage { items: GameDetail[]; total: number; offset: number; limit: number }
export const GAME_SORTS = ['name', 'recent_updated', 'recent_added'] as const;
export const GAME_WEBSITE_STATUSES = ['all', 'available', 'missing'] as const;
export type GameSort = typeof GAME_SORTS[number];
export type GameWebsiteStatus = typeof GAME_WEBSITE_STATUSES[number];
export interface GameListInput { query?: string; onlyCollection?: boolean; websiteStatus?: GameWebsiteStatus; sort?: GameSort; offset?: number; limit?: number }
export type GameCreate = Partial<GameFields> & { favorite?: boolean; reference_works?: ReferenceWork[] };
export type GamePatch = GameCreate & { expected_revision: number; reset_fields?: GameField[] };
export interface CreateGameInput { data: GameCreate; idempotencyKey: string }
export interface UpdateGameInput { id: string; data: GamePatch }
/** A task can defer navigation until save/discard is explicitly chosen. */
export type NavigationGuard = ((proceed: () => void) => void) & {
  /** The task permits same-origin credential repair while keeping its draft mounted. */
  recovery?: { credentialsChanged: () => void };
};
