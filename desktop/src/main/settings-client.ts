import type { ServiceName, ServiceStatus, ReanalysisSettings, SMTPInput, SMTPStatus, SMTPTestResult, TestStatus, SMTPEncryption } from '../shared/settings';
import { serviceNames } from '../shared/settings';
import { PublicFailure } from './transport';
import { deliveryOutcomeUnknown, invalidSettings, settingsKeys, settingsObject, validateSettingsRequest, type SettingsRequest } from './settings-transport';
export type SettingsRequestHandler = (input: SettingsRequest) => Promise<unknown>;
function invalidResponse(): never { throw new PublicFailure('invalid_response', 'The service returned an invalid settings response.', false); }
function object(value: unknown): Record<string, unknown> { try { return settingsObject(value); } catch { return invalidResponse(); } }
function bool(value: unknown): boolean { if (typeof value !== 'boolean') invalidResponse(); return value; }
function text(value: unknown): string | null { if (value !== null && (typeof value !== 'string' || value.length > 1024)) invalidResponse(); return value; }
function integer(value: unknown, max: number): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1 || value > max) invalidResponse(); return value; }
function timestamp(value: unknown): string | null { const result = text(value); if (result !== null && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(result) || !Number.isFinite(Date.parse(result)))) invalidResponse(); return result; }
function status(value: unknown): TestStatus { if (value !== null && value !== 'success' && value !== 'failure') invalidResponse(); return value; }
function service(value: unknown): ServiceName { if (typeof value !== 'string' || !(serviceNames as readonly string[]).includes(value)) invalidSettings(); return value as ServiceName; }
function connectionStatus(value: unknown): ServiceStatus { const raw = object(value); return { configured: bool(raw.configured), lastTestStatus: status(raw.last_test_status), lastTestedAt: timestamp(raw.last_tested_at) }; }
function reanalysis(value: unknown): ReanalysisSettings { const raw = object(value); return { gameIntervalDays: integer(raw.game_interval_days, 90), creatorIntervalDays: integer(raw.creator_interval_days, 30) }; }
function smtpStatus(value: unknown): SMTPStatus {
  const raw = object(value);
  if (raw.encryption !== null && !['tls', 'starttls', 'none'].includes(raw.encryption as string)) invalidResponse();
  return { ...connectionStatus(raw), host: text(raw.host), port: raw.port === null ? null : integer(raw.port, 65_535), encryption: raw.encryption as SMTPEncryption | null, username: text(raw.username), fromName: text(raw.from_name), replyTo: text(raw.reply_to), emailsPerMinute: integer(raw.emails_per_minute, 60) };
}
function testResult(value: unknown): SMTPTestResult {
  const raw = object(value); const lastTestStatus = status(raw.last_test_status); const lastTestedAt = timestamp(raw.last_tested_at);
  if (lastTestStatus === null || lastTestedAt === null) invalidResponse();
  return { succeeded: bool(raw.succeeded), lastTestStatus, lastTestedAt };
}
export class SettingsClient {
  constructor(private readonly request: SettingsRequestHandler) {}
  private perform(input: SettingsRequest) { return this.request(validateSettingsRequest(input)); }
  async connection(value: ServiceName): Promise<ServiceStatus> { return connectionStatus(await this.perform({ method: 'GET', path: `/api/v1/settings/connections/${service(value)}` })); }
  async replaceConnection(input: { service: ServiceName; secret: string }): Promise<ServiceStatus> {
    const raw = settingsObject(input); settingsKeys(raw, ['service', 'secret']);
    return connectionStatus(await this.perform({ method: 'PUT', path: `/api/v1/settings/connections/${service(raw.service)}`, body: { secret: raw.secret as string } }));
  }
  async testConnection(value: ServiceName): Promise<ServiceStatus> { return connectionStatus(await this.perform({ method: 'POST', path: `/api/v1/settings/connections/${service(value)}` })); }
  async reanalysis(): Promise<ReanalysisSettings> { return reanalysis(await this.perform({ method: 'GET', path: '/api/v1/settings/reanalysis' })); }
  async saveReanalysis(input: ReanalysisSettings): Promise<ReanalysisSettings> {
    const raw = settingsObject(input); settingsKeys(raw, ['gameIntervalDays', 'creatorIntervalDays']);
    return reanalysis(await this.perform({ method: 'PATCH', path: '/api/v1/settings/reanalysis', body: { game_interval_days: raw.gameIntervalDays as number, creator_interval_days: raw.creatorIntervalDays as number } }));
  }
  async smtp(): Promise<SMTPStatus> { return smtpStatus(await this.perform({ method: 'GET', path: '/api/v1/outreach/smtp' })); }
  async saveSMTP(input: SMTPInput): Promise<SMTPStatus> {
    const raw = settingsObject(input); settingsKeys(raw, ['host', 'port', 'encryption', 'username', 'password', 'fromName', 'replyTo', 'emailsPerMinute']);
    return smtpStatus(await this.perform({ method: 'PUT', path: '/api/v1/outreach/smtp', body: { host: input.host, port: input.port, encryption: input.encryption, username: input.username, from_name: input.fromName, reply_to: input.replyTo, emails_per_minute: input.emailsPerMinute, ...(Object.hasOwn(raw, 'password') ? { password: input.password } : {}) } }));
  }
  async testSMTP(): Promise<SMTPTestResult> { return testResult(await this.perform({ method: 'POST', path: '/api/v1/outreach/smtp/test-connection' })); }
  async sendTestEmail(input: { recipient: string }): Promise<SMTPTestResult> {
    const raw = settingsObject(input); settingsKeys(raw, ['recipient']);
    const request = validateSettingsRequest({ method: 'POST', path: '/api/v1/outreach/smtp/test-email', body: { recipient: raw.recipient as string } });
    try { return testResult(await this.request(request)); }
    catch (error) {
      if (error instanceof PublicFailure && ['request_invalid', 'workspace_key_invalid', 'access_denied', 'smtp_not_configured'].includes(error.code)) throw error;
      throw deliveryOutcomeUnknown();
    }
  }
}
