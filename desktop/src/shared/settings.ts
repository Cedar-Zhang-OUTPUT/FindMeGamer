import type { Result } from './bridge';

export const serviceNames = ['steam', 'youtube', 'deepseek', 'google_ai', 'x'] as const;
export type ServiceName = typeof serviceNames[number];
export type TestStatus = 'success' | 'failure' | null;
export interface ServiceStatus { configured: boolean; lastTestStatus: TestStatus; lastTestedAt: string | null }
export interface ReanalysisSettings { gameIntervalDays: number; creatorIntervalDays: number }
export type SMTPEncryption = 'tls' | 'starttls' | 'none';
export interface SMTPInput {
  host: string; port: number; encryption: SMTPEncryption; username: string;
  password?: string; fromName: string; replyTo: string; emailsPerMinute: number;
}
export interface SMTPStatus {
  configured: boolean; host: string | null; port: number | null; encryption: SMTPEncryption | null;
  username: string | null; fromName: string | null; replyTo: string | null; emailsPerMinute: number;
  lastTestStatus: TestStatus; lastTestedAt: string | null;
}
export interface SMTPTestResult { succeeded: boolean; lastTestStatus: Exclude<TestStatus, null>; lastTestedAt: string }
export interface SettingsAPI {
  connection(service: ServiceName): Promise<Result<ServiceStatus>>;
  replaceConnection(input: { service: ServiceName; secret: string }): Promise<Result<ServiceStatus>>;
  testConnection(service: ServiceName): Promise<Result<ServiceStatus>>;
  reanalysis(): Promise<Result<ReanalysisSettings>>;
  saveReanalysis(input: ReanalysisSettings): Promise<Result<ReanalysisSettings>>;
  smtp(): Promise<Result<SMTPStatus>>;
  saveSMTP(input: SMTPInput): Promise<Result<SMTPStatus>>;
  testSMTP(): Promise<Result<SMTPTestResult>>;
  sendTestEmail(input: { recipient: string }): Promise<Result<SMTPTestResult>>;
}
