import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import type { Preferences, VerifiedRelease } from '../shared/preferences';

export interface UpdateMetadata { lastAttemptAt: string | null; lastCheckedAt: string | null; release: VerifiedRelease | null }
interface Stored { preferences: Preferences; updates: UpdateMetadata }
const defaults = (): Stored => ({ preferences: { appearance: 'system', fontSize: 'default', automaticUpdates: true }, updates: { lastAttemptAt: null, lastCheckedAt: null, release: null } });
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object'
  && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
function validPatch(input: unknown): asserts input is Partial<Preferences> {
  if (!record(input) || Object.keys(input).some(key => !['appearance', 'fontSize', 'automaticUpdates'].includes(key))
    || ('appearance' in input && !['system', 'light', 'dark'].includes(input.appearance as string))
    || ('fontSize' in input && !['small', 'medium', 'default', 'large', 'extra-large'].includes(input.fontSize as string))
    || ('automaticUpdates' in input && typeof input.automaticUpdates !== 'boolean')) throw new Error('Invalid preferences.');
}
const timestamp = (value: unknown): string | null => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : null;

/** Local presentation/update metadata only; writes commit by same-directory atomic rename. */
export class PreferencesStore {
  private queue: Promise<unknown> = Promise.resolve();
  private readonly path: string;
  constructor(private readonly directory: string) { this.path = join(directory, 'preferences.json'); }
  private serialize<T>(work: () => Promise<T>): Promise<T> {
    const next = this.queue.then(work); this.queue = next.catch(() => {}); return next;
  }
  private async load(): Promise<Stored> {
    let source: unknown;
    try { source = JSON.parse(await readFile(this.path, 'utf8')); }
    catch (error) {
      if (error instanceof SyntaxError || (error as NodeJS.ErrnoException).code === 'ENOENT') return defaults();
      throw error;
    }
    const value = defaults();
    if (!record(source)) return value;
    try { validPatch(source.preferences); value.preferences = { ...value.preferences, ...source.preferences }; } catch { /* Invalid local preferences revert to defaults. */ }
    if (record(source.updates)) {
      value.updates.lastAttemptAt = timestamp(source.updates.lastAttemptAt);
      value.updates.lastCheckedAt = timestamp(source.updates.lastCheckedAt);
      const release = source.updates.release;
      if (record(release) && typeof release.version === 'string' && typeof release.url === 'string') value.updates.release = { version: release.version, url: release.url };
    }
    return value;
  }
  private async persist(value: Stored): Promise<void> {
    await mkdir(this.directory, { recursive: true });
    const temporary = join(this.directory, `.preferences-${randomUUID()}.tmp`);
    try { await writeFile(temporary, JSON.stringify(value), { encoding: 'utf8', mode: 0o600, flag: 'wx' }); await rename(temporary, this.path); }
    finally { await rm(temporary, { force: true }); }
  }
  read(): Promise<Preferences> { return this.serialize(async () => (await this.load()).preferences); }
  update(input: unknown): Promise<Preferences> {
    return this.serialize(async () => { validPatch(input); const value = await this.load(); value.preferences = { ...value.preferences, ...input }; await this.persist(value); return value.preferences; });
  }
  restoreAppearance(): Promise<Preferences> { return this.update({ appearance: 'system', fontSize: 'default' }); }
  readUpdateMetadata(): Promise<UpdateMetadata> { return this.serialize(async () => (await this.load()).updates); }
  updateUpdateMetadata(input: Partial<UpdateMetadata>): Promise<void> {
    return this.serialize(async () => {
      const value = await this.load();
      if ('lastAttemptAt' in input) value.updates.lastAttemptAt = timestamp(input.lastAttemptAt);
      if ('lastCheckedAt' in input) value.updates.lastCheckedAt = timestamp(input.lastCheckedAt);
      if ('release' in input) value.updates.release = input.release ? { version: input.release.version, url: input.release.url } : null;
      await this.persist(value);
    });
  }
}
