import type {
  JsonObject, JsonValue, LibrarySession, ListPage, ListProfilesInput,
  ProfileContact, ProfileDetail, ProfileDetailInput, ProfileFieldGroup, ProfileKind,
  ProfileSummary,
} from '../shared/library';

/** Main owns authentication, origin policy, proxy behavior and HTTP errors. */
export type LibraryRequest = (path: string, query?: Record<string, string>) => Promise<unknown>;

export class LibraryClientError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly retryable = false,
    public readonly correlationId?: string,
  ) {
    super(message);
    this.name = 'LibraryClientError';
  }
}

function invalidResponse(): never {
  throw new LibraryClientError('invalid_response', 'The server returned an unsupported Library response.');
}

function invalidInput(): never {
  throw new LibraryClientError('invalid_input', 'The Library request is invalid.');
}

function isObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function object(value: unknown): Record<string, unknown> {
  return isObject(value) ? value : invalidResponse();
}

function string(value: unknown): string {
  return typeof value === 'string' ? value : invalidResponse();
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function boolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : invalidResponse();
}

const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
const rfc3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i;

function timestamp(value: unknown): string | null {
  const result = nullableString(value);
  if (result !== null && (!rfc3339.test(result) || !Number.isFinite(Date.parse(result)))) invalidResponse();
  return result;
}

function kind(value: unknown): ProfileKind {
  return value === 'games' || value === 'creators' ? value : invalidInput();
}

/** Error envelopes must never become an empty successful list/session. */
function response(value: unknown): Record<string, unknown> {
  const result = object(value);
  if (Object.hasOwn(result, 'error')) {
    const error = object(result.error);
    throw new LibraryClientError(string(error.code), string(error.message), boolean(error.retryable),
      error.correlation_id === undefined ? undefined : string(error.correlation_id));
  }
  return result;
}

function secretField(key: string): boolean {
  if (key === '__proto__' || key === 'constructor' || key === 'prototype') return true;
  const words = key.replace(/([a-z\d])([A-Z])/g, '$1_$2')
    .replace(/([A-Z])([A-Z][a-z])/g, '$1_$2').toLowerCase().split(/[^a-z0-9]+/);
  const material = new Set(['authorization', 'password', 'passwords', 'passwd', 'pwd',
    'bearer', 'cookie', 'cookies', 'secret', 'secrets', 'credential', 'credentials',
    'token', 'tokens', 'jwt']);
  if (words.some(word => material.has(word))) return true;
  const keyQualifiers = new Set(['api', 'access', 'private', 'signing', 'encryption',
    'auth', 'authentication', 'session']);
  if (words.some(word => word === 'key' || word === 'keys') && words.some(word => keyQualifiers.has(word))) return true;
  return /^(?:apikey|accesskey|workspacekey|workspaceaccesskey|geminiapikey|youtubeapikey|authtoken|accesstoken|refreshtoken|clientsecret)$/.test(words.join(''));
}

/** Preserve unknown public business values; no raw credential/config objects enter IPC. */
function publicObject(value: unknown): JsonObject {
  object(value);
  const active = new WeakSet<object>();
  let nodes = 0;
  function visit(item: unknown, depth: number): JsonValue {
    if (++nodes > 100_000 || depth > 36) invalidResponse();
    if (item === null || typeof item === 'string' || typeof item === 'boolean') return item;
    if (typeof item === 'number') return Number.isFinite(item) ? item : invalidResponse();
    if (typeof item !== 'object' || item === null || active.has(item)) invalidResponse();
    active.add(item);
    let result: JsonValue;
    if (Array.isArray(item)) {
      result = Array.from(item, child => visit(child, depth + 1));
    } else {
      const entries = Object.entries(object(item)).map(([key, child]) => {
        if ([...key].length > 512) invalidResponse();
        // Validate even values beneath excluded fields; never silently accept non-JSON.
        return [key, visit(child, depth + 1)] as const;
      });
      result = Object.fromEntries(entries.filter(([key]) => !secretField(key)));
    }
    active.delete(item);
    return result;
  }
  return visit(value, 0) as JsonObject;
}

function text(value: JsonValue | undefined): string | null {
  if (typeof value === 'string') return value.trim() || null;
  return isObject(value) ? text(value.value as JsonValue | undefined) : null;
}

function strings(value: JsonValue | undefined): string[] {
  const values = Array.isArray(value) ? value : isObject(value) ? value.values : undefined;
  if (!Array.isArray(values)) return [];
  return [...new Set(values.filter((item): item is string => typeof item === 'string')
    .map(item => item.trim()).filter(Boolean))];
}

function artwork(value: JsonValue | undefined): string | null {
  const candidate = text(value);
  if (!candidate) return null;
  try {
    const url = new URL(candidate);
    return ['https:', 'http:'].includes(url.protocol) && url.hostname && !url.username && !url.password
      ? candidate : null;
  } catch { return null; }
}

function contact(value: unknown): ProfileContact {
  const item = object(value);
  return { email: string(item.email), source: string(item.source),
    sourceUrl: nullableString(item.source_url), validationState: string(item.validation_state),
    purpose: item.purpose === undefined ? null : nullableString(item.purpose) };
}

function card(value: unknown, requestedKind: ProfileKind) {
  const raw = publicObject(response(value));
  const expectedType = requestedKind === 'games' ? 'game' : 'creator';
  if (raw.type !== undefined && raw.type !== expectedType) invalidResponse();
  const id = string(raw.id);
  if (!uuid.test(id)) invalidResponse();
  const facts = object(raw.current_facts) as JsonObject;
  const brief = object(raw.brief) as JsonObject;
  object(raw.source_status);
  const count = facts.subscriber_count;
  const factTags = strings(facts.genres);
  const summary: ProfileSummary = {
    id, kind: requestedKind, name: string(raw.name),
    sourceId: string(requestedKind === 'games' ? raw.steam_app_id : raw.youtube_channel_id),
    canonicalUrl: string(raw.canonical_url), favorite: boolean(raw.favorite),
    updatedAt: timestamp(raw.last_analyzed_at),
    nextAnalysisAt: timestamp(raw.next_analysis_at),
    summary: requestedKind === 'games'
      ? text(facts.short_description) ?? text(brief.positioning_premise)
      : text(brief.performance_context),
    artworkUrl: requestedKind === 'games'
      ? artwork(facts.cover_image_url) ?? artwork(facts.header_image_url) : artwork(facts.avatar_url),
    subscribers: requestedKind === 'creators' && typeof count === 'number'
      && Number.isSafeInteger(count) && count >= 0 ? count : null,
    tags: requestedKind === 'games' ? (factTags.length ? factTags : strings(brief.genres))
      : strings(brief.content_focus),
  };
  let contacts: ProfileContact[] = [];
  if (requestedKind === 'creators') {
    const preferred = raw.contact === null ? null : contact(raw.contact);
    if (raw.contacts === undefined) contacts = preferred ? [preferred] : [];
    else if (Array.isArray(raw.contacts)) contacts = raw.contacts.map(contact);
    else invalidResponse();
  }
  return { raw, summary, contacts };
}

export class LibraryClient {
  constructor(private readonly request: LibraryRequest) {}

  async session(): Promise<LibrarySession> {
    const raw = response(await this.request('/api/v1/session'));
    const connections = object(raw.service_connections);
    return { workspaceName: string(raw.workspace_name), apiVersion: string(raw.api_version),
      serviceConnections: Object.fromEntries(Object.entries(connections)
        .map(([name, value]) => [name, boolean(value)])) };
  }

  async list(input: ListProfilesInput): Promise<ListPage> {
    if (!isObject(input)) invalidInput();
    const requestedKind = kind(input.kind);
    const query = input.query === undefined ? '' : input.query;
    const onlyCollection = input.onlyCollection === undefined ? false : input.onlyCollection;
    const limit = input.limit === undefined ? 50 : input.limit;
    if (typeof query !== 'string' || [...query].length > 255
      || typeof onlyCollection !== 'boolean' || !Number.isInteger(limit) || limit < 1 || limit > 100
      || (input.cursor !== undefined && (typeof input.cursor !== 'string'
        || !input.cursor || [...input.cursor].length > 2048))) invalidInput();
    const params: Record<string, string> = { query, only_collection: String(onlyCollection), limit: String(limit) };
    if (input.cursor !== undefined) params.cursor = input.cursor;
    const raw = response(await this.request(`/api/v1/profiles/${requestedKind}`, params));
    if (!Array.isArray(raw.items)) invalidResponse();
    const nextCursor = nullableString(raw.next_cursor);
    if (nextCursor !== null && (!nextCursor || [...nextCursor].length > 2048)) invalidResponse();
    return { items: raw.items.map(value => card(value, requestedKind).summary), nextCursor };
  }

  async detail(input: ProfileDetailInput): Promise<ProfileDetail> {
    if (!isObject(input)) invalidInput();
    const requestedKind = kind(input.kind);
    if (typeof input.id !== 'string' || !uuid.test(input.id)) invalidInput();
    const decoded = card(await this.request(`/api/v1/profiles/${requestedKind}/${input.id}`), requestedKind);
    if (decoded.summary.id.toLowerCase() !== input.id.toLowerCase()) invalidResponse();
    const { raw } = decoded;
    const groupFields = [
      ['facts', 'Facts', 'current_facts'], ['brief', 'Brief', 'brief'],
      ['analysis', 'Analysis', 'analysis'], ['sources', 'Sources', 'source_status'],
      ['model', 'Model metadata', 'model_metadata'], ['prompt', 'Prompt metadata', 'prompt_metadata'],
    ] as const;
    const groups: ProfileFieldGroup[] = groupFields.map(([id, label, field]) => ({
      id, label, data: object(raw[field]) as JsonObject,
    }));
    return { ...decoded.summary, contacts: decoded.contacts, groups, raw,
      manualNotes: requestedKind === 'creators' ? nullableString(raw.manual_notes) : null };
  }
}
