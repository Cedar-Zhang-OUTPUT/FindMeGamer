import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, expect, test } from 'vitest';
import { PreferencesStore } from '../src/main/preferences-store';

const directories: string[] = [];
async function setup() { const directory = await mkdtemp(join(tmpdir(), 'fmg-preferences-')); directories.push(directory); return { directory, store: new PreferencesStore(directory) }; }
afterEach(async () => { await Promise.all(directories.splice(0).map(path => rm(path, { recursive: true, force: true }))); });

test('defaults survive missing and corrupt files', async () => {
  const { directory, store } = await setup();
  expect(await store.read()).toEqual({ appearance: 'system', fontSize: 'default', automaticUpdates: true });
  await writeFile(join(directory, 'preferences.json'), '{broken');
  expect(await new PreferencesStore(directory).read()).toEqual({ appearance: 'system', fontSize: 'default', automaticUpdates: true });
});
test('serializes updates, persists them and restores appearance without automatic updates', async () => {
  const { directory, store } = await setup();
  await Promise.all([store.update({ appearance: 'dark' }), store.update({ fontSize: 'extra-large' }), store.update({ automaticUpdates: false })]);
  expect(await new PreferencesStore(directory).read()).toEqual({ appearance: 'dark', fontSize: 'extra-large', automaticUpdates: false });
  expect(await store.restoreAppearance()).toEqual({ appearance: 'system', fontSize: 'default', automaticUpdates: false });
  expect(await readdir(directory)).toEqual(['preferences.json']);
  expect(JSON.parse(await readFile(join(directory, 'preferences.json'), 'utf8')).preferences.automaticUpdates).toBe(false);
});
test.each([null, [], { appearance: 'auto' }, { fontSize: 12 }, { automaticUpdates: 'true' }, { secret: 'do-not-store' }].map(input => ({ input })))('rejects invalid patch $input without changing persisted preferences', async ({ input }) => {
  const { store } = await setup();
  await store.update({ appearance: 'light' });
  await expect(store.update(input)).rejects.toThrow();
  expect((await store.read()).appearance).toBe('light');
});
test('invalid stored values revert to defaults and never project surplus credentials', async () => {
  const { directory } = await setup();
  await writeFile(join(directory, 'preferences.json'), JSON.stringify({ preferences: { appearance: 'dark', secret: 'sensitive' }, updates: { lastAttemptAt: 'invalid' }, businessRecords: ['private'] }));
  const store = new PreferencesStore(directory);
  expect(await store.read()).toEqual({ appearance: 'system', fontSize: 'default', automaticUpdates: true });
  expect((await store.readUpdateMetadata()).lastAttemptAt).toBeNull();
  await store.update({ appearance: 'light' });
  expect(await readFile(join(directory, 'preferences.json'), 'utf8')).not.toMatch(/sensitive|private/);
});
test('persists update metadata independently of preference changes', async () => {
  const { directory, store } = await setup();
  await Promise.all([store.updateUpdateMetadata({ lastAttemptAt: '2026-09-08T00:00:00.000Z' }), store.update({ appearance: 'dark' })]);
  expect((await new PreferencesStore(directory).readUpdateMetadata()).lastAttemptAt).toBe('2026-09-08T00:00:00.000Z');
  expect((await store.read()).appearance).toBe('dark');
});
test.each([new Date(), new Map(), new (class UnexpectedPatch { appearance = 'dark'; })()].map(input => ({ input })))('rejects non-plain patch $input', async ({ input }) => {
  const { store } = await setup();
  await store.update({ appearance: 'light' });
  await expect(store.update(input)).rejects.toThrow('Invalid preferences.');
  expect((await store.read()).appearance).toBe('light');
});
