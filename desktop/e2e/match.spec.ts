import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, readFile, rm, stat } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { ActivityDetail, ActivityPage, CandidatePage, EvaluationPage, EvaluationResultPage, EvaluationView, PlanPage, PlanView, QueryView } from '../src/shared/match';
import type { CreatorDetail } from '../src/shared/creators';
import type { GameDetail } from '../src/shared/games';
import { isolatedPreferences } from './preferences';

// Opt-in only: pinned cad5565 / 0012 API + worker + fixture HTTP providers.
// Controls are fixture-wide; the coordinator must run this file exclusively.
test.describe.configure({ mode: 'serial' });
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
const PIN = 'cad55656a9a15ef183c6e0ba4ba608bd61a7a1b5';
const ORIGIN = 'http://127.0.0.1:53251';
const MANAGE = '/Users/cedar/Documents/ChatGPT/FindMeGamer/integration/match_frontend/manage.py';
const runFile = promisify(execFile);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
interface Fixture { base_url: string; workspace_key: string; game_id: string; reference_work_ids: string[]; backend_revision: string; migration: string }
interface RecordedPost { requestId: number; path: string; body?: string; idempotencyKey?: string }
interface Harness {
  app: ElectronApplication; page: Page; fixture: Fixture; userData: string;
  read<T>(route: string): Promise<T>; posts(): Promise<RecordedPost[]>;
  diagnostics: { pageErrors: number; consoleProblems: number };
}

async function fixtureFile(): Promise<{ fixture: Fixture; directory: string } | null> {
  const file = process.env.FMG_MATCH_FIXTURE_FILE;
  test.skip(!file, 'Requires the coordinator-owned Match frontend fixture.');
  if (!file) return null;
  expect((await stat(file)).mode & 0o077).toBe(0);
  // manage.py owns this exact private directory; both control.json and
  // events.jsonl live beneath its state/ child (not beside private/).
  const directory = path.dirname(path.resolve(file));
  expect((await stat(directory)).mode & 0o077).toBe(0);
  let fixture: Fixture;
  try { fixture = JSON.parse(await readFile(file, 'utf8')) as Fixture; }
  catch { throw Error('Could not read the private Match fixture; sensitive details suppressed.'); }
  expect(fixture.base_url).toBe(ORIGIN);
  expect(fixture.backend_revision).toBe(PIN);
  expect(fixture.migration).toBe('20260908_0012');
  expect(typeof fixture.workspace_key === 'string' && fixture.workspace_key.length > 0).toBe(true);
  expect(UUID.test(fixture.game_id)).toBe(true);
  expect(fixture.reference_work_ids.length).toBeGreaterThan(0);
  expect(fixture.reference_work_ids.every(id => UUID.test(id))).toBe(true);
  return { fixture, directory };
}

async function control(directory: string, options: string[] = []) {
  // CLI changes only this owned test fixture. Capture neither private files nor
  // command stdout in test reports; never start/stop services or invoke smoke.
  try { await runFile('python3', [MANAGE, 'control', '--directory', directory, ...options], { timeout: 20_000, maxBuffer: 128 * 1024 }); }
  catch { throw Error('Match fixture control failed; inspect the owned fixture privately.'); }
}

async function launch(fixture: Fixture): Promise<Harness> {
  const userData = await mkdtemp(path.join(tmpdir(), 'fmg-match-v2-e2e-'));
  await isolatedPreferences(userData);
  const env = Object.fromEntries(Object.entries(process.env).filter(([key, value]) => value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string, string>;
  let app: ElectronApplication | undefined;
  try {
    const executablePath = process.env.FMG_PACKAGED_EXECUTABLE;
    app = await electron.launch({ args: [...(executablePath ? [] : ['.']), `--user-data-dir=${userData}`], ...(executablePath ? { executablePath } : {}), cwd: process.cwd(), env, chromiumSandbox: true });
    const page = await app.firstWindow();
    const diagnostics = { pageErrors: 0, consoleProblems: 0 };
    page.on('pageerror', () => diagnostics.pageErrors++);
    page.on('console', message => { if (message.type() === 'error' || message.type() === 'warning') diagnostics.consoleProblems++; });
    await app.evaluate(({ BrowserWindow, session }, origin) => {
      BrowserWindow.getAllWindows()[0].setSize(1320, 920);
      // Passive evidence only, not a request/response mock. Authorization is
      // deliberately never copied; no request or response is rewritten.
      const records: { requestId: number; path: string; body?: string; idempotencyKey?: string }[] = [];
      (globalThis as unknown as { matchE2EPosts: typeof records }).matchE2EPosts = records;
      const network = session.fromPartition('workspace-network').webRequest;
      const filter = { urls: [`${origin}/api/v2/*`] };
      const inScope = (url: string) => /^\/api\/v2\/(activities(?:\/|$)|discovery\/)/.test(new URL(url).pathname);
      network.onBeforeRequest(filter, (details, callback) => {
        if (details.method === 'POST' && inScope(details.url)) {
          const bytes = (details.uploadData ?? []).flatMap(part => part.bytes ? [part.bytes] : []);
          records.push({ requestId: details.id, path: new URL(details.url).pathname, ...(bytes.length ? { body: Buffer.concat(bytes).toString('utf8') } : {}) });
        }
        callback({ cancel: false });
      });
      network.onBeforeSendHeaders(filter, (details, callback) => {
        const record = records.find(item => item.requestId === details.id);
        const header = Object.keys(details.requestHeaders).find(key => key.toLowerCase() === 'idempotency-key');
        if (record && header) record.idempotencyKey = details.requestHeaders[header];
        callback({});
      });
    }, fixture.base_url);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await expect(page).toHaveURL('fmg://app/index.html');
    await expect(page).toHaveTitle('FindMeGamer');
    await expect(page.locator('vite-error-overlay, webpack-dev-server-client-overlay')).toHaveCount(0);
    await page.getByRole('button', { name: 'Open Settings', exact: true }).click();
    await page.getByLabel('Service URL').fill(fixture.base_url);
    const key = page.getByLabel('Workspace key', { exact: true });
    try { await key.fill(fixture.workspace_key); }
    catch { throw Error('Test credential entry failed; sensitive details suppressed.'); }
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.getByText('Connection verified', { exact: true })).toBeVisible();
    expect(await key.inputValue() === '').toBe(true);
    await page.getByRole('button', { name: 'Match', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Match', exact: true })).toBeVisible();
    const read = async <T,>(route: string): Promise<T> => {
      if (!/^\/api\/v2\/(activities|discovery|library)\b/.test(route)) throw Error('Read-only fixture route is outside the Match scope.');
      let response: Response;
      try { response = await fetch(`${fixture.base_url}${route}`, { method: 'GET', headers: { Authorization: `Bearer ${fixture.workspace_key}` }, redirect: 'error', signal: AbortSignal.timeout(10_000) }); }
      catch { throw Error('Read-only Match fixture request failed; sensitive details suppressed.'); }
      if (!response.ok) throw Error(`Read-only Match fixture check failed (HTTP ${response.status}).`);
      return response.json() as Promise<T>;
    };
    return { app, page, fixture, userData, diagnostics, read,
      posts: () => app!.evaluate(() => (globalThis as unknown as { matchE2EPosts: RecordedPost[] }).matchE2EPosts) };
  } catch (error) { await app?.close(); await rm(userData, { recursive: true, force: true }); throw error; }
}
async function close(harness: Harness | undefined) {
  if (!harness) return;
  try { await harness.app.close(); } finally { await rm(harness.userData, { recursive: true, force: true }); }
}
async function screenshot(harness: Harness, name: string) {
  const directory = process.env.FMG_MATCH_SCREENSHOT_DIR;
  if (!directory) return;
  const roots = [tmpdir(), '/tmp', '/private/tmp'].map(root => path.resolve(root) + path.sep);
  if (!path.isAbsolute(directory) || !roots.some(root => path.resolve(directory).startsWith(root))) throw Error('Match screenshots require an absolute temporary directory.');
  expect(await harness.page.locator('input[type="password"]').evaluateAll(nodes => nodes.every(node => (node as HTMLInputElement).value === ''))).toBe(true);
  await mkdir(directory, { recursive: true });
  await harness.page.screenshot({ path: path.join(directory, `${name}.png`) });
}
async function post(harness: Harness, route: string, occurrence = 0) {
  await expect.poll(async () => (await harness.posts()).filter(item => item.path === route).length).toBe(occurrence + 1);
  const result = (await harness.posts()).filter(item => item.path === route)[occurrence];
  expect(result.idempotencyKey).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
  return result;
}
async function createActivity(h: Harness, name: string): Promise<ActivityDetail> {
  const game = await h.read<GameDetail>(`/api/v2/library/games/${h.fixture.game_id}`);
  expect(game.name).toBe('Moonseed Garden Together');
  await h.page.getByRole('button', { name: 'New activity', exact: true }).click();
  await h.page.getByRole('textbox', { name: 'Activity name', exact: true }).fill(name);
  const picker = h.page.getByRole('region', { name: 'Linked game', exact: true });
  await picker.getByRole('searchbox', { name: 'Search games', exact: true }).fill('Moonseed Garden Together');
  await picker.getByRole('searchbox', { name: 'Search games', exact: true }).press('Enter');
  await picker.getByRole('button', { name: 'Select game Moonseed Garden Together', exact: true }).click();
  await h.page.getByRole('button', { name: 'Use game', exact: true }).click();
  const gameSection = h.page.getByRole('region', { name: 'Activity game', exact: true });
  await expect(gameSection.getByRole('heading', { name: 'Moonseed Garden Together', exact: true })).toBeVisible();
  const references = gameSection.locator('summary').filter({ hasText: /^Reference works$/ });
  await references.focus(); await references.press('Enter');
  for (const id of h.fixture.reference_work_ids) {
    const reference = game.reference_works.find(item => item.id === id);
    expect(Boolean(reference?.name)).toBe(true);
    await gameSection.getByRole('checkbox', { name: reference!.name!, exact: true }).check();
  }
  await h.page.getByRole('button', { name: 'Create activity', exact: true }).click();
  const submitted = await post(h, '/api/v2/activities');
  expect(JSON.parse(submitted.body!)).toEqual({ name, game_id: h.fixture.game_id, reference_work_ids: h.fixture.reference_work_ids });
  let matches: ActivityPage['items'] = [];
  await expect.poll(async () => { matches = (await h.read<ActivityPage>('/api/v2/activities?limit=100&offset=0')).items.filter(item => item.name === name); return matches.length; }).toBe(1);
  const saved = await h.read<ActivityDetail>(`/api/v2/activities/${matches[0].id}`);
  expect(saved.game_id).toBe(h.fixture.game_id);
  expect(saved.source_snapshot.game).toMatchObject({ id: h.fixture.game_id, name: game.name, description: game.description });
  expect((saved.source_snapshot.references as { id: string }[]).map(item => item.id)).toEqual(h.fixture.reference_work_ids);
  await expect(h.page.getByRole('heading', { name, exact: true })).toBeVisible();
  return saved;
}
async function findCreators(h: Harness, activityId: string, batchTarget: number) {
  const platforms = h.page.getByRole('group', { name: 'Platforms', exact: true });
  await platforms.getByRole('checkbox', { name: 'YouTube', exact: true }).check();
  await platforms.getByRole('checkbox', { name: 'X', exact: true }).check();
  await expect(platforms.getByRole('checkbox', { name: 'Twitch · Unavailable', exact: true })).toBeDisabled();
  await expect(platforms.getByRole('checkbox', { name: 'Instagram · Unavailable', exact: true })).toBeDisabled();
  const advanced = h.page.locator('.discovery-advanced summary');
  await advanced.focus(); await advanced.press('Enter');
  await h.page.getByRole('spinbutton', { name: 'Batch target', exact: true }).fill(String(batchTarget));
  await h.page.getByRole('button', { name: 'Find creators', exact: true }).click();
  const submitted = await post(h, `/api/v2/activities/${activityId}/discovery-plans`);
  const data = JSON.parse(submitted.body!);
  expect(data).toMatchObject({ mode: 'discover', platforms: ['youtube', 'x'], batch_target: batchTarget });
  expect(data).not.toHaveProperty('providers');
  let plans: PlanPage | undefined;
  await expect.poll(async () => { plans = await h.read<PlanPage>(`/api/v2/activities/${activityId}/discovery-plans?limit=50&offset=0`); return plans.total; }).toBe(1);
  return { id: plans!.items[0].id, data, submitted };
}
async function planSettled(h: Harness, id: string, minimumAttempt = 1): Promise<PlanView> {
  let value: PlanView | undefined;
  await expect.poll(async () => { value = await h.read<PlanView>(`/api/v2/discovery/plans/${id}`); return value.attempt >= minimumAttempt && ['ready', 'failed'].includes(value.status); }, { timeout: 60_000 }).toBe(true);
  return value!;
}
async function querySettled(h: Harness, id: string, batches = 1): Promise<QueryView> {
  let value: QueryView | undefined;
  await expect.poll(async () => {
    value = await h.read<QueryView>(`/api/v2/discovery/queries/${id}`);
    return value.batches.length >= batches && !['queued', 'running'].includes(value.status) && !value.batches.some(batch => ['queued', 'running'].includes(batch.status));
  }, { timeout: 60_000 }).toBe(true);
  return value!;
}
async function candidates(h: Harness, queryId: string) { return h.read<CandidatePage>(`/api/v2/discovery/queries/${queryId}/results?limit=100&offset=0`); }
async function completeDiscovery(h: Harness, initial: QueryView) {
  let query = initial;
  const preserved = (await candidates(h, query.id)).items.map(item => item.id);
  for (let batch = 0; query.status !== 'completed' && batch < 5; batch++) {
    const before = query.batches.length;
    await h.page.getByRole('button', { name: 'Continue discovery', exact: true }).click();
    query = await querySettled(h, query.id, before + 1);
    const current = await candidates(h, query.id);
    expect(preserved.every(id => current.items.some(item => item.id === id))).toBe(true);
    expect(new Set(current.items.map(item => item.id)).size).toBe(current.items.length);
  }
  expect(query.status).toBe('completed'); expect(query.result_count).toBe(6);
  expect(Object.values(query.sources).map(source => (source as { status: string }).status)).toEqual(['exhausted', 'exhausted']);
  const results = await candidates(h, query.id);
  expect(results.total).toBe(6); expect(results.items).toHaveLength(6);
  expect(new Set(results.items.map(item => `${item.platform}:${item.account_id}`)).size).toBe(6);
  expect(results.items.every(item => !item.selected && !item.identity_changed)).toBe(true);
  await expect(h.page.getByRole('region', { name: 'Candidate results', exact: true }).getByRole('article')).toHaveCount(6);
  await expect(h.page.getByRole('button', { name: 'Continue discovery', exact: true })).toBeDisabled();
  return results;
}
function hasPrivateRanking(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  if (Array.isArray(value)) return value.some(hasPrivateRanking);
  return Object.entries(value).some(([key, item]) => /^(score|rank|rank_position|input_order|.*_score)$/.test(key) || hasPrivateRanking(item));
}
async function assertHealth(h: Harness) {
  expect(h.diagnostics).toEqual({ pageErrors: 0, consoleProblems: 0 });
  expect((await readFile(path.join(h.userData, 'credentials.json'), 'utf8')).includes(h.fixture.workspace_key)).toBe(false);
  expect((await h.posts()).every(item => /^[A-Za-z0-9._:-]{8,128}$/.test(item.idempotencyKey ?? ''))).toBe(true);
}

test('Match v2 real planning, retained discovery pages, explicit six-candidate evaluation and Creator return', async () => {
  test.setTimeout(180_000);
  const loaded = await fixtureFile(); if (!loaded) return;
  let h: Harness | undefined;
  try {
    h = await launch(loaded.fixture);
    const name = `Desktop Match ${randomUUID().slice(0, 8)}`;
    const activity = await createActivity(h, name);
    await screenshot(h, 'match-conditions');
    const created = await findCreators(h, activity.id, 1);
    const plan = await planSettled(h, created.id);
    expect(plan.status).toBe('ready'); expect(plan.query_id).not.toBeNull();
    expect(plan.conditions).toEqual(created.data); expect(plan.source_snapshot).toEqual(activity.source_snapshot);
    let query = await querySettled(h, plan.query_id!);
    expect(query.status).toBe('paused'); expect(query.result_count).toBe(2);
    await expect(h.page.getByRole('region', { name: 'Candidate results', exact: true }).getByRole('article')).toHaveCount(2);
    const initialIds = (await candidates(h, query.id)).items.map(item => item.id);
    const found = await completeDiscovery(h, query);
    expect(initialIds.every(id => found.items.some(item => item.id === id))).toBe(true);
    const unknown = found.items.filter(item => item.account.follower_count === null);
    expect(unknown).toHaveLength(2);
    await expect(h.page.getByRole('region', { name: 'Candidate results', exact: true }).getByText('Followers unknown', { exact: true })).toHaveCount(2);
    expect((await h.read<EvaluationPage>(`/api/v2/discovery/queries/${query.id}/evaluations`)).total).toBe(0);
    await screenshot(h, 'match-candidates');
    await h.page.getByRole('button', { name: 'Evaluate 6 loaded', exact: true }).click();
    const evaluationPost = await post(h, `/api/v2/discovery/queries/${query.id}/evaluations`);
    expect(JSON.parse(evaluationPost.body!)).toEqual({ candidate_ids: found.items.map(item => item.id) });
    let runs: EvaluationPage | undefined;
    await expect.poll(async () => { runs = await h!.read<EvaluationPage>(`/api/v2/discovery/queries/${query.id}/evaluations`); return runs.total; }).toBe(1);
    const runId = runs!.items[0].id;
    let run: EvaluationView | undefined;
    await expect.poll(async () => { run = await h!.read<EvaluationView>(`/api/v2/discovery/evaluations/${runId}`); return run.status; }, { timeout: 60_000 }).toBe('completed');
    expect(run!.candidate_count).toBe(6); expect(run!.matched_count).toBe(6);
    const briefs = await h.read<EvaluationResultPage>(`/api/v2/discovery/evaluations/${runId}/results?limit=100&offset=0`);
    expect(briefs.total).toBe(6); expect(briefs.items).toHaveLength(6);
    expect(briefs.items.map(item => item.candidate_id).sort()).toEqual(found.items.map(item => item.id).sort());
    expect(briefs.items.every(item => item.match_brief?.confidence === 'limited' && !item.selected && !item.sender_watched && !item.stale && !item.identity_changed)).toBe(true);
    expect(briefs.items.every(item => ['unknown', 'metadata_only'].includes(item.evidence_status))).toBe(true);
    expect(hasPrivateRanking(briefs)).toBe(false);
    const evaluations = h.page.getByRole('region', { name: 'Evaluation results', exact: true });
    await expect(evaluations.getByRole('article')).toHaveCount(6);
    await expect(evaluations.locator('.match-summary')).toHaveCount(6);
    const first = evaluations.getByRole('article').first();
    const disclosure = first.locator('summary').filter({ hasText: /^Fit and evidence$/ });
    await disclosure.focus(); await disclosure.press('Enter');
    await expect(first.getByRole('heading', { name: 'Limitations', exact: true })).toBeVisible();
    await screenshot(h, 'match-briefs');
    await h.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(760, 720));
    await expect.poll(() => h!.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await screenshot(h, 'match-briefs-narrow');
    await h.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1320, 920));
    const current = await h.read<CreatorDetail>(`/api/v2/library/creators/${briefs.items[0].creator_id}`);
    const creatorName = current.name || current.public_name || current.handle || current.source_identity.account_id || 'Unnamed creator';
    await first.getByRole('button', { name: 'View current creator', exact: true }).click();
    await expect(h.page.getByRole('heading', { name: creatorName, exact: true, level: 1 })).toBeVisible();
    await expect(h.page.getByRole('button', { name: 'Edit profile', exact: true })).toBeVisible();
    await h.page.getByRole('tab', { name: 'Profile', exact: true }).focus(); await h.page.keyboard.press('ArrowRight');
    await expect(h.page.getByRole('tab', { name: 'Emails', exact: true })).toHaveAttribute('aria-selected', 'true');
    await screenshot(h, 'match-current-creator');
    await h.page.getByRole('button', { name: 'Back to activity', exact: true }).click();
    await expect(evaluations.getByRole('article')).toHaveCount(6);
    await expect(h.page.getByRole('combobox', { name: 'Evaluation history', exact: true })).toHaveValue(runId);
    expect((await h.posts()).filter(item => item.path.endsWith('/evaluations'))).toHaveLength(1);
    const posts = await h.posts(); expect(new Set(posts.map(item => item.idempotencyKey)).size).toBe(posts.length);
    await assertHealth(h);
  } finally { await close(h); }
});

test('Match v2 real model retry, partial source preservation and held-page stop/continue recovery', async () => {
  test.setTimeout(180_000);
  const loaded = await fixtureFile(); if (!loaded) return;
  let h: Harness | undefined;
  try {
    await control(loaded.directory, ['--model-fail', 'planning']);
    h = await launch(loaded.fixture);
    const activity = await createActivity(h, `Desktop Match recovery ${randomUUID().slice(0, 8)}`);
    const created = await findCreators(h, activity.id, 100);
    const failed = await planSettled(h, created.id);
    expect(failed.status).toBe('failed'); expect(failed.retryable).toBe(true); expect(failed.query_id).toBeNull();
    await expect(h.page.getByRole('button', { name: 'Retry planning', exact: true })).toBeVisible();
    expect((await h.posts()).filter(item => item.path.endsWith('/retry'))).toHaveLength(0);
    await screenshot(h, 'match-planning-failed');
    await control(loaded.directory, ['--source-fail', 'x']);
    await h.page.getByRole('button', { name: 'Retry planning', exact: true }).click();
    const retry = await post(h, `/api/v2/discovery/plans/${created.id}/retry`);
    expect(retry.body === undefined || retry.body === '').toBe(true);
    expect(retry.idempotencyKey).not.toBe(created.submitted.idempotencyKey);
    const ready = await planSettled(h, created.id, 2);
    expect(ready.status).toBe('ready'); expect(ready.attempt).toBe(2); expect(ready.query_id).not.toBeNull();
    const partial = await querySettled(h, ready.query_id!);
    expect(partial.status).toBe('paused'); expect(partial.result_count).toBe(3);
    expect(partial.sources).toMatchObject({ youtube: { status: 'exhausted' }, x: { status: 'failed' } });
    expect(partial.batches.at(-1)?.reason).toBe('provider_failed');
    const firstIds = (await candidates(h, partial.id)).items.map(item => item.id);
    await expect(h.page.getByRole('region', { name: 'Candidate results', exact: true }).getByRole('article')).toHaveCount(3);
    await expect(h.page.getByText('X · Failed', { exact: true })).toBeVisible();
    await screenshot(h, 'match-source-partial');
    const eventsFile = path.join(loaded.directory, 'state', 'events.jsonl');
    const eventOffset = (await readFile(eventsFile, 'utf8')).split('\n').filter(Boolean).length;
    await control(loaded.directory, ['--hold', 'x']);
    await h.page.getByRole('button', { name: 'Continue discovery', exact: true }).click();
    await expect.poll(async () => (await readFile(eventsFile, 'utf8')).split('\n').filter(Boolean).slice(eventOffset).some(line => {
      const event = JSON.parse(line) as { endpoint: string; status: string | number }; return event.endpoint === 'x' && event.status === 'held';
    }), { timeout: 10_000 }).toBe(true);
    await h.page.getByRole('button', { name: 'Stop discovery', exact: true }).click();
    const stop = await post(h, `/api/v2/discovery/queries/${partial.id}/stop`);
    expect(stop.body === undefined || stop.body === '').toBe(true);
    await expect.poll(async () => (await h!.read<QueryView>(`/api/v2/discovery/queries/${partial.id}`)).stop_requested).toBe(true);
    await control(loaded.directory);
    const stopped = await querySettled(h, partial.id, partial.batches.length + 1);
    expect(stopped.status).toBe('stopped'); expect(stopped.stop_requested).toBe(true);
    expect(stopped.result_count).toBe(5);
    const stoppedItems = await candidates(h, partial.id);
    expect(firstIds.every(id => stoppedItems.items.some(item => item.id === id))).toBe(true);
    const recovered = await completeDiscovery(h, stopped);
    expect(firstIds.every(id => recovered.items.some(item => item.id === id))).toBe(true);
    expect((await h.read<PlanPage>(`/api/v2/activities/${activity.id}/discovery-plans`)).total).toBe(1);
    expect((await h.read<EvaluationPage>(`/api/v2/discovery/queries/${partial.id}/evaluations`)).total).toBe(0);
    await assertHealth(h);
  } finally { try { await control(loaded.directory); } finally { await close(h); } }
});
