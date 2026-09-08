import type { PublicError, Result } from './bridge';

export type AppearanceMode = 'system' | 'light' | 'dark';
export type FontSize = 'small' | 'medium' | 'default' | 'large' | 'extra-large';
export interface Preferences { appearance: AppearanceMode; fontSize: FontSize; automaticUpdates: boolean }
export interface PreferencesAPI {
  read(): Promise<Result<Preferences>>;
  update(input: Partial<Preferences>): Promise<Result<Preferences>>;
  restoreAppearance(): Promise<Result<Preferences>>;
}
export interface VerifiedRelease { version: string; url: string }
export interface UpdateState {
  phase: 'idle' | 'checking' | 'current' | 'available' | 'failed' | 'development';
  installedVersion: string; lastCheckedAt: string | null; lastAttemptAt: string | null;
  release: VerifiedRelease | null; error: PublicError | null;
}
export interface UpdatesAPI { status(): Promise<Result<UpdateState>>; check(): Promise<Result<UpdateState>> }
