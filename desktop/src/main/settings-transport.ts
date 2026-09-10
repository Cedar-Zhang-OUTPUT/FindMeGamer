import { STEAM_REFERENCES_OPT_IN } from './steam-reference-opt-in';
import { randomUUID } from 'node:crypto';
import { isIP } from 'node:net';
import type { CollectionPlatform, ServiceName } from '../shared/settings';
import { normalizeServiceUrl } from './policies';
import { PublicFailure, type Connection, type Fetcher } from './transport';

type ConnectionPath = `/api/v1/settings/connections/${ServiceName}`;
type CollectionPath = `/api/v1/settings/collection/${CollectionPlatform}`;
type SMTPBody = { host: string; port: number; encryption: 'tls' | 'starttls' | 'none'; username: string; password?: string; from_name: string; reply_to: string; emails_per_minute: number };
export type SettingsRequest =
  | { method: 'GET'; path: ConnectionPath | '/api/v1/settings/collection' | '/api/v1/settings/reanalysis' | '/api/v1/outreach/smtp' }
  | { method: 'POST'; path: ConnectionPath | '/api/v1/outreach/smtp/test-connection' }
  | { method: 'POST'; path: '/api/v1/outreach/smtp/test-email'; body: { recipient: string } }
  | { method: 'PUT'; path: ConnectionPath; body: { secret: string } }
  | { method: 'PUT'; path: CollectionPath; body: { enabled: boolean } }
  | { method: 'PUT'; path: '/api/v1/outreach/smtp'; body: SMTPBody }
  | { method: 'PATCH'; path: '/api/v1/settings/reanalysis'; body: { game_interval_days: number; creator_interval_days: number } };
const servicePath = /^\/api\/v1\/settings\/connections\/(steam|youtube|deepseek|google_ai|x)$/;
const collectionPath = /^\/api\/v1\/settings\/collection\/(youtube|x|twitch|instagram)$/;
const collectionRoot = '/api/v1/settings/collection';
const smtpPath = '/api/v1/outreach/smtp';
const reanalysisPath = '/api/v1/settings/reanalysis';
const LIMIT = 65_536;
export function invalidSettings(): never { throw new PublicFailure('request_invalid', 'Check the settings fields and required values.', false); }
export function deliveryOutcomeUnknown(): PublicFailure { return new PublicFailure('delivery_outcome_unknown', 'Test email delivery could not be confirmed. Check the recipient inbox before sending again.', false); }
export function settingsObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) invalidSettings();
  return value as Record<string, unknown>;
}
export function settingsKeys(raw: Record<string, unknown>, allowed: readonly string[]) {
  if (Object.keys(raw).some(key => !allowed.includes(key))) invalidSettings();
}
export function settingsInteger(value: unknown, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) invalidSettings(); return value;
}
function string(value: unknown, max: number, trim = true): string {
  if (typeof value !== 'string' || [...value].length > max) invalidSettings();
  const normalized = trim ? value.trim() : value;
  if (!normalized || /[\u0000-\u001f\u007f-\u009f]/u.test(value)) invalidSettings(); return normalized;
}
export function settingsEmail(value: unknown): string {
  const email = string(value, 254);
  if (!/^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/u.test(email)) invalidSettings(); return email;
}
export function validateSettingsRequest(value: SettingsRequest): SettingsRequest {
  const raw = settingsObject(value);
  const { path, method } = raw;
  if (typeof path !== 'string') invalidSettings();
  const connection = servicePath.test(path);
  const collection = collectionPath.test(path);
  const hasBody = (method === 'PUT' && (connection || collection || path === smtpPath)) || (method === 'PATCH' && path === reanalysisPath) || (method === 'POST' && path === `${smtpPath}/test-email`);
  if (!hasBody && !(method === 'GET' && (connection || path === collectionRoot || path === smtpPath || path === reanalysisPath)) && !(method === 'POST' && (connection || path === `${smtpPath}/test-connection`))) invalidSettings();
  settingsKeys(raw, hasBody ? ['method', 'path', 'body'] : ['method', 'path']);
  if (!hasBody) return { method, path } as SettingsRequest;
  const body = settingsObject(raw.body);
  let normalized: Record<string, unknown>;
  if (connection) {
    settingsKeys(body, ['secret']);
    if (typeof body.secret !== 'string' || [...body.secret].length < 1 || [...body.secret].length > 16_384) invalidSettings();
    normalized = { secret: body.secret };
  } else if (collection) {
    settingsKeys(body, ['enabled']);
    if (typeof body.enabled !== 'boolean') invalidSettings();
    normalized = { enabled: body.enabled };
  } else if (path === reanalysisPath) {
    settingsKeys(body, ['game_interval_days', 'creator_interval_days']);
    normalized = { game_interval_days: settingsInteger(body.game_interval_days, 1, 90), creator_interval_days: settingsInteger(body.creator_interval_days, 1, 30) };
  } else if (path === `${smtpPath}/test-email`) {
    settingsKeys(body, ['recipient']); normalized = { recipient: settingsEmail(body.recipient) };
  } else {
    settingsKeys(body, ['host', 'port', 'encryption', 'username', 'password', 'from_name', 'reply_to', 'emails_per_minute']);
    const host = string(body.host, 253).toLowerCase().replace(/\.+$/, '');
    // Backend owns global-address and DNS resolution policy; retain valid IP literals.
    if (!host || host === 'localhost' || host.endsWith('.localhost') || (!isIP(host) && host.split('.').some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label)))) invalidSettings();
    if (!['tls', 'starttls', 'none'].includes(body.encryption as string)) invalidSettings();
    normalized = { host, port: settingsInteger(body.port, 1, 65_535), encryption: body.encryption, username: settingsEmail(body.username), from_name: string(body.from_name, 255), reply_to: settingsEmail(body.reply_to), emails_per_minute: settingsInteger(body.emails_per_minute, 1, 60) };
    if (Object.hasOwn(body, 'password')) normalized.password = string(body.password, 16_384);
  }
  return { method, path, body: normalized } as SettingsRequest;
}
async function boundedJSON(response: Response): Promise<unknown> {
  const tooLarge = () => new PublicFailure('response_too_large', 'The settings response is too large.', false);
  if (Number(response.headers.get('content-length')) > LIMIT) { await response.body?.cancel(); throw tooLarge(); }
  const reader = response.body?.getReader();
  if (!reader) throw new PublicFailure('invalid_response', 'The service returned an invalid settings response.', false);
  const chunks: Uint8Array[] = []; let size = 0;
  while (true) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > LIMIT) { await reader.cancel(); throw tooLarge(); } chunks.push(value); }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new PublicFailure('invalid_response', 'The service returned an invalid settings response.', false); }
}
const safeErrors: Record<string, string> = {
  smtp_password_required: 'Enter a password to configure SMTP for the first time.',
  smtp_not_configured: 'Save SMTP settings before testing.',
  connection_not_configured: 'Save the service credential before testing.',
  connection_test_unavailable: 'Testing is unavailable for this service.',
};
export async function authenticatedSettingsRequest(fetcher: Fetcher, connection: Connection, input: SettingsRequest): Promise<unknown> {
  const request = validateSettingsRequest(input);
  let url: string;
  try { url = new URL(request.path, normalizeServiceUrl(connection.serviceUrl)).href; }
  catch { throw new PublicFailure('request_invalid', 'Check the workspace service address.', false); }
  const send = request.path === `${smtpPath}/test-email`;
  try {
    const response = await fetcher(url, { method: request.method, ...('body' in request ? { body: JSON.stringify(request.body) } : {}),
      headers: { ...STEAM_REFERENCES_OPT_IN, Authorization: `Bearer ${connection.key}`, Accept: 'application/json', 'X-Correlation-ID': randomUUID(), ...('body' in request ? { 'Content-Type': 'application/json' } : {}) },
      redirect: 'error', credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (!response.ok) {
      if (send && (response.status >= 500 || response.status === 409)) { await response.body?.cancel(); throw deliveryOutcomeUnknown(); }
      let code: unknown;
      try { const envelope = settingsObject(await boundedJSON(response)); code = settingsObject(envelope.error).code; } catch { /* Never expose upstream text. */ }
      if (typeof code === 'string' && Object.hasOwn(safeErrors, code)) throw new PublicFailure(code, safeErrors[code], false);
      if (response.status === 401) throw new PublicFailure('workspace_key_invalid', 'The workspace key was not accepted. Update it in Settings.', false);
      if (response.status === 403) throw new PublicFailure('access_denied', 'This workspace does not allow the requested access.', false);
      if (response.status === 422) invalidSettings();
      if (send) throw deliveryOutcomeUnknown();
      throw new PublicFailure('service_error', 'The service could not complete the settings request.', request.method === 'GET' && response.status >= 500);
    }
    return await boundedJSON(response);
  } catch (error) {
    if (send && (!(error instanceof PublicFailure) || ['invalid_response', 'response_too_large'].includes(error.code))) throw deliveryOutcomeUnknown();
    if (error instanceof PublicFailure) throw error;
    throw new PublicFailure('network_error', 'Could not reach the service. Check your connection and service address.', request.method === 'GET');
  }
}
