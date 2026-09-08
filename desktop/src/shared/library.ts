/** Read-only public Library contract. Access keys never belong in these DTOs. */
export type ProfileKind = 'games' | 'creators';
export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
export interface JsonObject { [key: string]: JsonValue }

export interface LibrarySession {
  workspaceName: string;
  apiVersion: string;
  serviceConnections: Record<string, boolean>;
}

export interface ListProfilesInput {
  kind: ProfileKind;
  query?: string;
  onlyCollection?: boolean;
  cursor?: string;
  limit?: number;
}

export interface ProfileDetailInput { kind: ProfileKind; id: string }

export interface ProfileSummary {
  id: string;
  kind: ProfileKind;
  name: string;
  sourceId: string;
  canonicalUrl: string;
  summary: string | null;
  artworkUrl: string | null;
  favorite: boolean;
  /** The API exposes last_analyzed_at, not a general profile updated_at. */
  updatedAt: string | null;
  subscribers: number | null;
  tags: string[];
}

export interface ListPage {
  items: ProfileSummary[];
  nextCursor: string | null;
}

export interface ProfileContact {
  email: string;
  source: string;
  sourceUrl: string | null;
  validationState: string;
  purpose: string | null;
}

export interface ProfileFieldGroup {
  id: 'facts' | 'brief' | 'analysis' | 'sources' | 'model' | 'prompt';
  label: string;
  data: JsonObject;
}

export interface ProfileDetail extends ProfileSummary {
  contacts: ProfileContact[];
  manualNotes: string | null;
  groups: ProfileFieldGroup[];
  /** Public business fields, including unknown nested fields; render as text, never HTML. */
  raw: JsonObject;
}

// Wire shapes mirror backend/openapi.json, not Swift generator wrapper types.
export interface SessionResponse {
  workspace_name: string;
  api_version: string;
  service_connections: Record<string, boolean>;
}

export interface CreatorContactResponse {
  email: string;
  source: string;
  source_url: string | null;
  validation_state: string;
  purpose?: string | null;
}

export interface ProfileCardResponse {
  id: string;
  name: string;
  canonical_url: string;
  favorite: boolean;
  current_facts: JsonObject;
  brief: JsonObject;
  source_status: JsonObject;
  last_analyzed_at: string | null;
  next_analysis_at: string | null;
}

export interface GameProfileCardResponse extends ProfileCardResponse {
  type?: 'game';
  steam_app_id: string;
}

export interface CreatorProfileCardResponse extends ProfileCardResponse {
  type?: 'creator';
  youtube_channel_id: string;
  contact: CreatorContactResponse | null;
  contacts?: CreatorContactResponse[];
}

export interface CursorPageResponse<T> { items: T[]; next_cursor: string | null }

export interface ProfileAnalysisResponse {
  analysis: JsonObject;
  model_metadata: JsonObject;
  prompt_metadata: JsonObject;
}

export type GameProfileDetailResponse = GameProfileCardResponse & ProfileAnalysisResponse;
export type CreatorProfileDetailResponse = CreatorProfileCardResponse & ProfileAnalysisResponse & {
  manual_notes: string | null;
};

export interface APIErrorResponse {
  error: { code: string; message: string; retryable: boolean; correlation_id?: string };
}
