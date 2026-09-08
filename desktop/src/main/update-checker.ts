import type { UpdateState, VerifiedRelease } from '../shared/preferences';
import type { PreferencesStore } from './preferences-store';

export const UPDATE_MANIFEST_URL = 'https://44.233.174.193/updates/macos.json';
export const RELEASES_URL = 'https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases';
export const MAX_RESPONSE_BYTES = 32768;
export const UPDATE_TIMEOUT_MS = 20000;
export const AUTOMATIC_INTERVAL_MS = 24 * 60 * 60 * 1000;
interface Version { core: string[]; prerelease: string[]; plain: boolean }
function parseVersion(value: string): Version | null {
  if (value.length > 128) return null;
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/.exec(value);
  if (!match) return null;
  const prerelease = match[4]?.split('.') ?? [];
  if (prerelease.some(part => /^\d+$/.test(part) && part.length > 1 && part[0] === '0')) return null;
  return { core: match.slice(1, 4), prerelease, plain: !match[4] && !match[5] };
}
const numericCompare = (a: string, b: string) => a.length !== b.length ? Math.sign(a.length - b.length) : a === b ? 0 : a < b ? -1 : 1;
function compare(a: Version, b: Version): number {
  for (let i = 0; i < 3; i++) { const result = numericCompare(a.core[i], b.core[i]); if (result) return result; }
  if (!a.prerelease.length || !b.prerelease.length) return Math.sign(Number(!a.prerelease.length) - Number(!b.prerelease.length));
  for (let i = 0; i < Math.min(a.prerelease.length, b.prerelease.length); i++) {
    const left = a.prerelease[i], right = b.prerelease[i]; if (left === right) continue;
    const ln = /^\d+$/.test(left), rn = /^\d+$/.test(right);
    return ln && rn ? numericCompare(left, right) : ln !== rn ? ln ? -1 : 1 : left < right ? -1 : 1;
  }
  return Math.sign(a.prerelease.length - b.prerelease.length);
}
function validatedRelease(version: unknown, url: unknown): VerifiedRelease | null {
  if (typeof version !== 'string' || typeof url !== 'string' || !parseVersion(version)?.plain) return null;
  // Inspect the raw URL: URL normalization would conceal explicit :443 or dot segments.
  const match = /^https:\/\/github\.com\/Cedar-Zhang-OUTPUT\/FindMeGamer\/releases\/tag\/(v?((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))(?:-internal\.[1-9]\d*)?)$/.exec(url);
  return match && match[2] === version && parseVersion(match[1].replace(/^v/, '')) ? { version, url } : null;
}
class UpdateFailure extends Error {
  constructor(readonly code: string, message: string) { super(message); }
}
const invalid = () => new UpdateFailure('invalid_update', 'The update information could not be verified.');
async function readRelease(response: Response): Promise<VerifiedRelease> {
  if (response.redirected || (response.url && response.url !== UPDATE_MANIFEST_URL)) throw invalid();
  if (response.status !== 200) throw new UpdateFailure('update_unavailable', response.status === 429 ? 'Too many update checks. Try again later.' : 'The update service is unavailable. Try again later.');
  if (Number(response.headers.get('content-length')) > MAX_RESPONSE_BYTES) { void response.body?.cancel().catch(() => {}); throw invalid(); }
  if (!response.body) throw invalid();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try {
    for (;;) { const { value, done } = await reader.read(); if (done) break; total += value.byteLength; if (total > MAX_RESPONSE_BYTES) { void reader.cancel().catch(() => {}); throw invalid(); } chunks.push(value); }
  } finally { reader.releaseLock(); }
  const body = new Uint8Array(total); let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  const source = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body));
  const release = source?.schema_version === 1 ? validatedRelease(source.version, source.release_page_url) : null;
  if (!release) throw invalid(); return release;
}
interface Options { installedVersion: string; fetcher: typeof fetch; preferences: Pick<PreferencesStore, 'read' | 'readUpdateMetadata' | 'updateUpdateMetadata'>; clock?: () => Date }
export class UpdateChecker {
  private state: UpdateState;
  private readonly ready: Promise<void>;
  private active: Promise<UpdateState> | null = null;
  private readonly clock: () => Date;
  constructor(private readonly options: Options) {
    this.clock = options.clock ?? (() => new Date());
    this.state = { phase: parseVersion(options.installedVersion) ? 'idle' : 'development', installedVersion: options.installedVersion, lastCheckedAt: null, lastAttemptAt: null, release: null, error: null };
    this.ready = this.restore();
  }
  private async restore(): Promise<void> {
    const saved = await this.options.preferences.readUpdateMetadata();
    this.state.lastAttemptAt = saved.lastAttemptAt; this.state.lastCheckedAt = saved.lastCheckedAt;
    const release = saved.release && validatedRelease(saved.release.version, saved.release.url);
    const installed = parseVersion(this.options.installedVersion);
    if (release && installed && compare(parseVersion(release.version)!, installed) > 0) { this.state.release = release; this.state.phase = 'available'; }
  }
  async status(): Promise<UpdateState> { await this.ready; return structuredClone(this.state); }
  check(): Promise<UpdateState> {
    if (this.active) return this.active;
    this.active = this.perform().finally(() => { this.active = null; }); return this.active;
  }
  async checkAutomatically(): Promise<UpdateState> {
    await this.ready;
    if (!(await this.options.preferences.read()).automaticUpdates) return this.status();
    const age = this.state.lastAttemptAt ? this.clock().getTime() - Date.parse(this.state.lastAttemptAt) : null;
    if (age !== null && age >= 0 && age < AUTOMATIC_INTERVAL_MS) return this.status();
    return this.check();
  }
  private async perform(): Promise<UpdateState> {
    await this.ready;
    const installed = parseVersion(this.options.installedVersion);
    if (!installed) return this.status();
    this.state.phase = 'checking'; this.state.error = null; this.state.lastAttemptAt = this.clock().toISOString();
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await this.options.preferences.updateUpdateMetadata({ lastAttemptAt: this.state.lastAttemptAt });
      const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error('timeout')); }, UPDATE_TIMEOUT_MS); });
      const request = this.options.fetcher(UPDATE_MANIFEST_URL, { method: 'GET', redirect: 'error', credentials: 'omit', cache: 'no-store', headers: { Accept: 'application/json' }, signal: controller.signal }).then(readRelease);
      const release = await Promise.race([request, timeout]);
      const available = compare(parseVersion(release.version)!, installed) > 0 ? release : null;
      const checked = this.clock().toISOString();
      await this.options.preferences.updateUpdateMetadata({ lastCheckedAt: checked, release: available });
      this.state.release = available; this.state.lastCheckedAt = checked; this.state.phase = available ? 'available' : 'current';
    } catch (error) {
      this.state.phase = 'failed'; this.state.error = { code: error instanceof UpdateFailure ? error.code : 'update_unavailable', message: error instanceof UpdateFailure ? error.message : 'Could not check for updates. Try again later.', retryable: true };
    } finally { if (timer) clearTimeout(timer); }
    return this.status();
  }
}
