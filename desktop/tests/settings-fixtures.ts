import { vi } from 'vitest';
import type { Result } from '../src/shared/bridge';
import type { Preferences } from '../src/shared/preferences';
import type { SettingsAPI, SMTPStatus } from '../src/shared/settings';
import { creatorAPIMock } from './creator-api-mock';
import { creatorFixture } from './creator-fixtures';
import { matchAPIMock } from './match-api-mock';
import { collectionSettingsFixture } from './collection-fixtures';
import { outreachAPIMock } from './outreach-api-mock';
import type { DraftsAPI } from '../src/shared/drafts';
import { builtinTemplate, compositionFixture, draftFixture, templateVersion } from './drafts-fixtures';
import { qualificationFixture, sendBatchFixture, deliveryFixture } from './sending-fixtures';
import type { SendingAPI } from '../src/shared/sending';

export const ok = <T>(data: T): Result<T> => ({ ok: true, data });
export const emptySMTP: SMTPStatus = { configured: false, host: null, port: null, encryption: null, username: null, fromName: null, replyTo: null, emailsPerMinute: 10, lastTestStatus: null, lastTestedAt: null };
export function settingsBridgeMock() {
  let preferences: Preferences = { appearance: 'system', fontSize: 'default', automaticUpdates: true };
  let collection = collectionSettingsFixture();
  const settings: SettingsAPI = {
    collection: vi.fn(async () => ok(collection)),
    setCollection: vi.fn(async input => ok(collection = { items: collection.items.map(item => item.platform === input.platform ? { ...item, enabled: input.enabled,
      availability: !input.enabled ? 'disabled' : !item.implemented ? 'not_implemented' : item.credentials_configured ? 'configured_unverified' : 'missing_connection' } : item) })),
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
  const sending: SendingAPI = {
    qualify: vi.fn(async () => ok(qualificationFixture())), send: vi.fn(async () => ok(sendBatchFixture())),
    batches: vi.fn(async input => ok({items:[],total:0,offset:input.offset??0,limit:input.limit??50})),
    batch: vi.fn(async () => ok(sendBatchFixture())), retry: vi.fn(async () => ok(deliveryFixture())), resolve: vi.fn(async () => ok(deliveryFixture())),
  };
  const drafts: DraftsAPI = {
    templates: vi.fn(async () => ok({ items: [], builtin: structuredClone(builtinTemplate) })),
    template: vi.fn(async () => ok(structuredClone(templateVersion))),
    registerCanonical: vi.fn(async () => ok(structuredClone(templateVersion))),
    createTemplate: vi.fn(async () => ok(structuredClone(templateVersion))),
    compositions: vi.fn(async input => ok({ items: [], total: 0, offset: input.offset ?? 0, limit: input.limit ?? 50 })),
    composition: vi.fn(async () => ok(compositionFixture())),
    createComposition: vi.fn(async () => ok(compositionFixture())),
    edit: vi.fn(async () => ok(draftFixture())),
    refresh: vi.fn(async () => ok(draftFixture())),
    retry: vi.fn(async () => ok(draftFixture())),
    senderFacts: vi.fn(async () => ok(compositionFixture())),
  };
  vi.mocked(creators.list).mockResolvedValue(ok({items:[creatorFixture('Pixel Harbor','Pixel Harbor')],total:1,limit:50,offset:0}));
  vi.mocked(creators.detail).mockImplementation(async id => ok(creatorFixture(id,id)));
  return { sending, drafts, outreach:outreachAPIMock(),savedSets:{list:vi.fn(async()=>ok({items:[],total:0,offset:0,limit:50})),detail:vi.fn(),results:vi.fn(),create:vi.fn()}, match:matchAPIMock(), creators, settings, preferences: {
    read: vi.fn(async () => ok(preferences)),
    update: vi.fn(async (input: Partial<Preferences>) => ok(preferences = {...preferences,...input})),
    restoreAppearance: vi.fn(async () => ok(preferences = {...preferences,appearance:'system',fontSize:'default'})),
  }, updates: {
    status: vi.fn(async () => ok({phase:'idle' as const, installedVersion:'0.2.0-alpha.1',lastCheckedAt:null,lastAttemptAt:null,release:null,error:null})),
    check: vi.fn(async () => ok({phase:'current' as const, installedVersion:'0.2.0-alpha.1',lastCheckedAt:'2026-09-08T01:00:00Z',lastAttemptAt:'2026-09-08T01:00:00Z',release:null,error:null})),
  } };
}
