import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, expect, test, vi } from 'vitest';
import { PreferencesStore } from '../src/main/preferences-store';
import { UpdateChecker } from '../src/main/update-checker';

const dirs: string[] = [];
const releaseURL = 'https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v1.2.3';
const manifest = (version = '1.2.3', url = releaseURL) => ({ schema_version: 1, version, release_page_url: url });
const response = (value: unknown) => new Response(JSON.stringify(value));
async function setup(fetcher: typeof fetch = async () => response(manifest()), installedVersion = '1.2.2', clock = () => new Date('2026-09-08T00:00:00Z')) {
  const directory = await mkdtemp(join(tmpdir(), 'fmg-updates-')); dirs.push(directory);
  const preferences = new PreferencesStore(directory);
  return { preferences, checker: new UpdateChecker({ installedVersion, fetcher, preferences, clock }) };
}
afterEach(async () => { vi.useRealTimers(); await Promise.all(dirs.splice(0).map(path => rm(path, { recursive: true, force: true }))); });

test('trusted newer release is available with isolated request policy and successful timestamps', async () => {
  const fetcher = vi.fn<typeof fetch>(async () => response(manifest()));
  const { checker } = await setup(fetcher);
  expect(await checker.check()).toMatchObject({ phase: 'available', release: { version: '1.2.3', url: releaseURL }, lastCheckedAt: '2026-09-08T00:00:00.000Z', lastAttemptAt: '2026-09-08T00:00:00.000Z' });
  expect(fetcher.mock.calls[0][0]).toBe('https://44.233.174.193/updates/macos.json');
  expect(fetcher.mock.calls[0][1]).toMatchObject({ redirect: 'error', credentials: 'omit', cache: 'no-store', headers: { Accept: 'application/json' } });
});
test.each(['1.2.3-alpha.9', '1.2.3-1', '1.2.3-alpha+build.5', '0.99.999', '1.2.2+build'])('release outranks installed %s', async version => {
  const { checker } = await setup(undefined, version); expect((await checker.check()).phase).toBe('available');
});
test.each(['1.2.3', '1.2.3+new', '1.3.0-alpha', '99999999999999999999.0.0'])('does not offer older or equivalent release to %s', async version => {
  const { checker } = await setup(undefined, version); expect(await checker.check()).toMatchObject({ phase: 'current', release: null });
});
test.each(['dev', '01.2.3', '1.2.3-01', '1.2', '1.2.3+', 'v1.2.3'])('invalid installed %s stays development without network', async version => {
  const fetcher = vi.fn<typeof fetch>(); const { checker } = await setup(fetcher, version);
  expect((await checker.check()).phase).toBe('development'); expect(fetcher).not.toHaveBeenCalled();
});
test.each([
  releaseURL + '?a=1', releaseURL + '#x', releaseURL.replace('github.com', 'github.com:443'),
  releaseURL.replace('github.com', 'user@github.com'), releaseURL.replace('Cedar-Zhang-OUTPUT', 'attacker'),
  releaseURL.replace('v1.2.3', 'v1.2.4'), releaseURL.replace('v1.2.3', 'v1.2.3-alpha.1'),
  releaseURL + '-internal.0', releaseURL + '-internal.01', releaseURL.replace('https:', 'http:'),
  releaseURL.replace('/tag/', '/other/../tag/'), releaseURL.replace('v1.2.3', '%761.2.3'),
])('rejects untrusted release URL %s', async url => {
  const { checker } = await setup(async () => response(manifest('1.2.3', url)));
  expect(await checker.check()).toMatchObject({ phase: 'failed', release: null, lastCheckedAt: null });
});
test('allows a matching positive internal release tag', async () => {
  const { checker } = await setup(async () => response(manifest('1.2.3', releaseURL + '-internal.2')));
  expect((await checker.check()).phase).toBe('available');
});
test.each([{ ...manifest(), schema_version: 2 }, manifest('1.2.3+build'), manifest('1.2.3-alpha'), { version: '1.2.3' }])('rejects malformed manifest %j', async value => {
  const { checker } = await setup(async () => response(value)); expect((await checker.check()).phase).toBe('failed');
});
test('deduplicates checks and retains verified release on error across restart', async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>(() => new Promise(resolve => { finish = resolve; }));
  const { checker, preferences } = await setup(fetcher);
  const first = checker.check(); const second = checker.check();
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  expect((await checker.status()).phase).toBe('checking');
  finish(response(manifest())); await Promise.all([first, second]);
  const failed = new UpdateChecker({ installedVersion: '1.2.2', preferences, fetcher: async () => { throw new Error('secret network diagnostics'); } });
  expect(await failed.check()).toMatchObject({ phase: 'failed', release: { version: '1.2.3', url: releaseURL }, lastCheckedAt: '2026-09-08T00:00:00.000Z' });
  expect(JSON.stringify(await failed.status())).not.toContain('secret network diagnostics');
});
test('automatic failed attempt cooldown persists, permits clock rollback and respects disabled preference', async () => {
  let now = new Date('2026-09-08T00:00:00Z');
  const fetcher = vi.fn<typeof fetch>(async () => { throw new Error('offline'); });
  const { preferences, checker } = await setup(fetcher, '1.2.2', () => now);
  await checker.checkAutomatically();
  const restarted = new UpdateChecker({ installedVersion: '1.2.2', preferences, fetcher, clock: () => now });
  now = new Date('2026-09-08T23:59:59Z'); await restarted.checkAutomatically(); expect(fetcher).toHaveBeenCalledTimes(1);
  now = new Date('2026-09-09T00:00:00Z'); await restarted.checkAutomatically(); expect(fetcher).toHaveBeenCalledTimes(2);
  now = new Date('2026-09-08T00:00:00Z'); await restarted.checkAutomatically(); expect(fetcher).toHaveBeenCalledTimes(3);
  await preferences.update({ automaticUpdates: false }); now = new Date('2026-09-11T00:00:00Z');
  await restarted.checkAutomatically(); expect(fetcher).toHaveBeenCalledTimes(3);
});
test.each([new Response('x'.repeat(32769)), new Response('{}', { headers: { 'content-length': '32769' } }), new Response('{}', { status: 302 }), new Response('{}', { status: 429 })])('rejects oversized and unsuccessful responses', async res => {
  const { checker } = await setup(async () => res); expect((await checker.check()).phase).toBe('failed');
});
test('aborts and finishes a stalled update request after twenty seconds', async () => {
  const fetcher = vi.fn<typeof fetch>(() => new Promise(() => {}));
  const other = await setup(fetcher); vi.useFakeTimers(); const timed = other.checker.check();
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  await vi.advanceTimersByTimeAsync(20000); expect((await timed).phase).toBe('failed');
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
});
test('accepts exactly the maximum body size', async () => {
  const body = JSON.stringify(manifest()).padEnd(32768, ' ');
  const { checker } = await setup(async () => new Response(body));
  expect((await checker.check()).phase).toBe('available');
});
test('does not trust a cached foreign release or one superseded by installed version', async () => {
  const { preferences } = await setup();
  await preferences.updateUpdateMetadata({ release: { version: '1.2.3', url: 'https://evil.test/release' } });
  let checker = new UpdateChecker({ installedVersion: '1.2.2', preferences, fetcher: vi.fn() });
  expect((await checker.status()).release).toBeNull();
  await preferences.updateUpdateMetadata({ release: { version: '1.2.3', url: releaseURL } });
  checker = new UpdateChecker({ installedVersion: '1.2.3', preferences, fetcher: vi.fn() });
  expect((await checker.status()).release).toBeNull();
});
test('response URL must remain the approved manifest endpoint', async () => {
  const res = response(manifest()); Object.defineProperty(res, 'url', { value: 'https://evil.test/manifest' });
  const { checker } = await setup(async () => res); expect((await checker.check()).phase).toBe('failed');
});
test('returned snapshots cannot mutate a verified release', async () => {
  const { checker } = await setup(); const snapshot = await checker.check();
  snapshot.release!.url = 'https://evil.test';
  expect((await checker.status()).release?.url).toBe(releaseURL);
});
