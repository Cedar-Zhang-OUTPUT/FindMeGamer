import { expect, test } from '@playwright/test';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest } from '../src/main/match-transport';
import { SettingsClient } from '../src/main/settings-client';
import { authenticatedSettingsRequest, type SettingsRequest } from '../src/main/settings-transport';
import type { CollectionPlatformState, CollectionSettings } from '../src/shared/settings';
import type { QueryView } from '../src/shared/match';
import type { Connection, Fetcher } from '../src/main/transport';

// Opt-in only: the coordinator owns this synthetic fixture and its shared policy.
// This is a real Node HTTP adapter check, not Electron, Keychain, or packaged E2E.
test.describe.configure({ mode: 'serial' });
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

const ORIGIN = 'http://127.0.0.1:59414';
const PIN = 'b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857';
const MIGRATION = '20260908_0014';
const UUID_SOURCE = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const UUID = new RegExp(`^${UUID_SOURCE}$`, 'i');

interface Fixture {
  base_url: string;
  workspace_key: string;
  backend_revision: string;
  migration: string;
}

interface RequestRecord { method: string; path: string }

function state(value: CollectionSettings, platform: CollectionPlatformState['platform']) {
  const found = value.items.find(item => item.platform === platform);
  expect(found, `Missing ${platform} collection state`).toBeDefined();
  return found!;
}

function queryState(value: QueryView) {
  return {
    status: value.status,
    result_count: value.result_count,
    requests_reserved: value.requests_reserved,
    scanned_reserved: value.scanned_reserved,
    batches: value.batches,
    sources: value.sources,
    usage: value.usage,
  };
}

test('real collection GET/PUT persists, restores, and starts no provider or model work', async () => {
  test.setTimeout(30_000);
  const file = process.env.FMG_COLLECTION_FIXTURE_FILE;
  test.skip(!file, 'Requires the coordinator-owned collection-switch fixture.');
  if (!file) return;

  const resolvedFile = path.resolve(file);
  const directory = path.dirname(resolvedFile);
  expect(path.basename(resolvedFile)).toBe('client.json');
  expect((await stat(directory)).mode & 0o777).toBe(0o700);
  expect((await stat(resolvedFile)).mode & 0o777).toBe(0o600);

  let fixture: Fixture;
  try { fixture = JSON.parse(await readFile(resolvedFile, 'utf8')) as Fixture; }
  catch { throw Error('Could not read the private collection fixture; sensitive details suppressed.'); }
  expect(fixture.base_url).toBe(ORIGIN);
  expect(fixture.backend_revision).toBe(PIN);
  expect(fixture.migration).toBe(MIGRATION);
  expect(typeof fixture.workspace_key === 'string' && fixture.workspace_key.length > 0).toBe(true);

  const records: RequestRecord[] = [];
  const fetcher: Fetcher = async (url, init) => {
    const target = new URL(url);
    const method = init.method ?? 'GET';
    const settingsRead = method === 'GET' && target.pathname === '/api/v1/settings/collection';
    const settingsWrite = method === 'PUT' && target.pathname === '/api/v1/settings/collection/youtube';
    const matchRead = method === 'GET' && (
      target.pathname === '/api/v2/activities'
      || new RegExp(`^/api/v2/activities/${UUID_SOURCE}$`, 'i').test(target.pathname)
      || new RegExp(`^/api/v2/discovery/queries/${UUID_SOURCE}$`, 'i').test(target.pathname)
    );
    if (target.origin !== ORIGIN || target.username || target.password || (!settingsRead && !settingsWrite && !matchRead)) {
      throw Error('Collection fixture request escaped its read/write allowlist.');
    }
    records.push({ method, path: target.pathname });
    const signals = [AbortSignal.timeout(10_000), init.signal].filter((signal): signal is AbortSignal => signal instanceof AbortSignal);
    return fetch(target, { ...init, signal: AbortSignal.any(signals) });
  };
  const connection: Connection = { serviceUrl: fixture.base_url, key: fixture.workspace_key };
  const settings = new SettingsClient((request: SettingsRequest) => authenticatedSettingsRequest(fetcher, connection, request));
  const match = new MatchClient(request => authenticatedMatchRequest(fetcher, connection, request));
  const events = path.join(directory, 'state', 'events.jsonl');

  let original: CollectionSettings | undefined;
  let originalQuery: QueryView | undefined;
  let eventBytes: number | undefined;
  let restoreNeeded = false;
  try {
    original = await settings.collection();
    expect(original.items.map(item => item.platform)).toEqual(['youtube', 'x', 'twitch', 'instagram']);
    expect(new Set(original.items.map(item => item.platform)).size).toBe(4);
    eventBytes = (await readFile(events)).byteLength;

    const activities = await match.activities({ offset: 0, limit: 100 });
    let queryID: string | undefined;
    for (const activity of activities.items) {
      const detail = await match.activity(activity.id);
      const settled = detail.queries.find(query => !['queued', 'running'].includes(query.status)
        && !query.batches.some(batch => ['queued', 'running'].includes(batch.status)));
      if (settled) { queryID = settled.id; break; }
    }
    expect(queryID, 'The collection fixture must retain one settled Match query.').toMatch(UUID);
    originalQuery = await match.query(queryID!);

    const youtube = state(original, 'youtube');
    // Set before sending: a dropped response could still follow a committed PUT.
    restoreNeeded = true;
    const toggled = await settings.setCollection({ platform: 'youtube', enabled: !youtube.enabled });
    expect(toggled.items).toHaveLength(4);
    expect(state(toggled, 'youtube')).toMatchObject({
      platform: 'youtube',
      enabled: !youtube.enabled,
      implemented: youtube.implemented,
      credentials_configured: youtube.credentials_configured,
    });
    expect(toggled.items.filter(item => item.platform !== 'youtube')).toEqual(original.items.filter(item => item.platform !== 'youtube'));

    const persisted = await settings.collection();
    expect(persisted).toEqual(toggled);
    expect(persisted.items.map(item => item.credentials_configured)).toEqual(original.items.map(item => item.credentials_configured));
  } finally {
    if (original && restoreNeeded) {
      await settings.setCollection({ platform: 'youtube', enabled: state(original, 'youtube').enabled });
      expect(await settings.collection()).toEqual(original);
    }
    if (originalQuery) expect(queryState(await match.query(originalQuery.id))).toEqual(queryState(originalQuery));
    if (eventBytes !== undefined) expect((await readFile(events)).byteLength).toBe(eventBytes);
  }

  expect(records.length).toBeGreaterThan(0);
  expect(records.every(record => Object.keys(record).sort().join(',') === 'method,path')).toBe(true);
  expect(records.every(record => record.method === 'GET' || (record.method === 'PUT' && record.path === '/api/v1/settings/collection/youtube'))).toBe(true);
});
