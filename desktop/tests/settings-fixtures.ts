import { vi } from 'vitest';
import type { Result } from '../src/shared/bridge';
import type { Preferences } from '../src/shared/preferences';
import type { SettingsAPI, SMTPStatus } from '../src/shared/settings';
import { creatorAPIMock } from './creator-api-mock';
import { creatorFixture } from './creator-fixtures';
import { matchAPIMock } from './match-api-mock';

export const ok = <T>(data: T): Result<T> => ({ ok: true, data });
export const emptySMTP: SMTPStatus = { configured: false, host: null, port: null, encryption: null, username: null, fromName: null, replyTo: null, emailsPerMinute: 10, lastTestStatus: null, lastTestedAt: null };
export function settingsBridgeMock() {
  let preferences: Preferences = { appearance: 'system', fontSize: 'default', automaticUpdates: true };
  const settings: SettingsAPI = {
    connection: vi.fn(async () => ok({ configured: false, lastTestStatus: null, lastTestedAt: null })),
    replaceConnection: vi.fn(async () => ok({ configured: true, lastTestStatus: null, lastTestedAt: null })),
    testConnection: vi.fn(async () => ok({ configured: true, lastTestStatus: 'success' as const, lastTestedAt: '2026-09-08T01:00:00Z' })),
    reanalysis: vi.fn(async () => ok({gameIntervalDays:30,creatorIntervalDays:7})),
    saveReanalysis: vi.fn(async input => ok(input)),
    smtp: vi.fn(async () => ok(emptySMTP)),
    saveSMTP: vi.fn(async input => ok({...input, configured:true, password:undefined, lastTestStatus:null,lastTestedAt:null})),
    testSMTP: vi.fn(async () => ok({succeeded:true,lastTestStatus:'success' as const,lastTestedAt:'2026-09-08T01:00:00Z'})),
    sendTestEmail: vi.fn(async () => ok({succeeded:true,lastTestStatus:'success' as const,lastTestedAt:'2026-09-08T01:00:00Z'})),
  };
  const creators = creatorAPIMock();
  vi.mocked(creators.list).mockResolvedValue(ok({items:[creatorFixture('Pixel Harbor','Pixel Harbor')],total:1,limit:50,offset:0}));
  vi.mocked(creators.detail).mockImplementation(async id => ok(creatorFixture(id,id)));
  return { match:matchAPIMock(), creators, settings, preferences: {
    read: vi.fn(async () => ok(preferences)),
    update: vi.fn(async (input: Partial<Preferences>) => ok(preferences = {...preferences,...input})),
    restoreAppearance: vi.fn(async () => ok(preferences = {...preferences,appearance:'system',fontSize:'default'})),
  }, updates: {
    status: vi.fn(async () => ok({phase:'idle' as const, installedVersion:'0.2.0-alpha.1',lastCheckedAt:null,lastAttemptAt:null,release:null,error:null})),
    check: vi.fn(async () => ok({phase:'current' as const, installedVersion:'0.2.0-alpha.1',lastCheckedAt:'2026-09-08T01:00:00Z',lastAttemptAt:'2026-09-08T01:00:00Z',release:null,error:null})),
  } };
}
