import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import { GameClient } from '../src/main/game-client';
import { LibraryClient } from '../src/main/library-client';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest } from '../src/main/match-transport';
import { SavedSetClient } from '../src/main/saved-set-client';
import { authenticatedSavedSetRequest } from '../src/main/saved-set-transport';
import { SettingsClient } from '../src/main/settings-client';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';
import { authenticatedGameRequest, authenticatedGet, publicResult, type Connection, type Fetcher } from '../src/main/transport';
import type { CreatorDetail, CreatorListInput, CreatorSort } from '../src/shared/creators';
import type { GameListInput, GameSort } from '../src/shared/games';
import type { CandidateListInput, CandidateView } from '../src/shared/match';
import type { Preferences, UpdateState } from '../src/shared/preferences';

// This is a built-renderer + real-HTTP integration check. It deliberately does
// not claim Electron, IPC, Keychain, native shell, or packaged-app acceptance.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
test.describe.configure({ mode: 'serial' });

const FIXTURE_FILE = process.env.FMG_QUERY_RENDERER_FIXTURE_FILE;
test.skip(!FIXTURE_FILE, 'Requires exclusive coordinator handoff of the pinned query fixture and managed Chromium.');
const FIXTURE_ORIGIN = 'http://127.0.0.1:65164';
const BACKEND_PIN = 'a852307d6908e671ae1998c9741f19ffe65f5048';
const MIGRATION_PIN = '20260908_0015';
const ACTIVITY_PREFIX = 'Query UI acceptance ';
const UUID_ROUTE = '[0-9a-fA-F-]{36}';

interface PrivateFixture {
  base_url: string;
  backend_revision: string;
  migration: string;
  workspace_key: string;
}

interface RequestRecord {
  method: string;
  path: string;
  search: string;
}

interface SelectedFixtureActivity {
  id: string;
  name: string;
  queryId: string;
  scopeValue: string;
  resultCount: number;
}

const creatorName = (creator: CreatorDetail) => creator.name || creator.public_name || creator.handle
  || creator.source_identity.account_id || 'Unnamed creator';

function candidateName(candidate: CandidateView): string {
  const display = candidate.account.display_name;
  const handle = candidate.account.handle;
  return typeof display === 'string' && display.trim() ? display
    : typeof handle === 'string' && handle.trim() ? handle : candidate.account_id;
}

async function serveRenderer(): Promise<{ server: Server; origin: string }> {
  const rendererRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../out/renderer');
  const server = createServer(async (request, response) => {
    if (request.method !== 'GET' || !request.url) {
      response.writeHead(405).end();
      return;
    }
    let pathname: string;
    try { pathname = decodeURIComponent(new URL(request.url, 'http://renderer.invalid').pathname); }
    catch { response.writeHead(400).end(); return; }
    const relative = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
    const target = path.resolve(rendererRoot, relative);
    if (target !== rendererRoot && !target.startsWith(`${rendererRoot}${path.sep}`)) {
      response.writeHead(403).end();
      return;
    }
    try {
      const body = await readFile(target);
      const extension = path.extname(target);
      const mime: Record<string, string> = {
        '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
        '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2',
      };
      response.writeHead(200, { 'Content-Type': mime[extension] ?? 'application/octet-stream', 'Cache-Control': 'no-store' });
      response.end(body);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve());
  });
  const address = server.address() as AddressInfo;
  return { server, origin: `http://127.0.0.1:${address.port}` };
}

async function closeServer(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
}

test('built React query UI uses real production clients against the pinned HTTP fixture', async ({ browser }, testInfo) => {
  test.setTimeout(180_000);
  if (!FIXTURE_FILE) return;

  expect(path.basename(FIXTURE_FILE)).toBe('client.json');
  const directory = path.dirname(FIXTURE_FILE);
  expect((await stat(FIXTURE_FILE)).mode & 0o777).toBe(0o600);
  expect((await stat(directory)).mode & 0o777).toBe(0o700);
  let fixture: PrivateFixture;
  try { fixture = JSON.parse(await readFile(FIXTURE_FILE, 'utf8')) as PrivateFixture; }
  catch { throw new Error('Private renderer fixture unavailable; sensitive details suppressed.'); }
  expect(fixture.base_url).toBe(FIXTURE_ORIGIN);
  expect(fixture.backend_revision).toBe(BACKEND_PIN);
  expect(fixture.migration).toBe(MIGRATION_PIN);
  expect(typeof fixture.workspace_key === 'string' && fixture.workspace_key.length > 0).toBe(true);

  const records: RequestRecord[] = [];
  const unexpectedRequests: { method: string; path: string }[] = [];
  const readRoutes = [
    /^\/api\/v1\/session$/,
    /^\/api\/v1\/settings\/collection$/,
    /^\/api\/v2\/library\/(creators|games)(\/|$)/,
    /^\/api\/v2\/activities(\/|$)/,
    /^\/api\/v2\/discovery\//,
  ];
  const savedSetCreate = new RegExp(`^/api/v2/discovery/queries/${UUID_ROUTE}/saved-sets$`);
  const fetcher: Fetcher = async (url, init) => {
    const target = new URL(url);
    const method = String(init.method ?? 'GET').toUpperCase();
    const allowed = target.origin === FIXTURE_ORIGIN
      && (method === 'GET' ? readRoutes.some(route => route.test(target.pathname))
        : method === 'POST' && savedSetCreate.test(target.pathname));
    if (!allowed) {
      unexpectedRequests.push({ method, path: target.pathname });
      throw new Error('Renderer integration request escaped the strict fixture allowlist.');
    }
    records.push({ method, path: target.pathname, search: target.search });
    return fetch(target, {
      ...init,
      signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]),
    });
  };

  const connection: Connection = { serviceUrl: FIXTURE_ORIGIN, key: fixture.workspace_key };
  const creators = new CreatorClient(input => authenticatedCreatorRequest(fetcher, connection, input));
  const games = new GameClient(input => authenticatedGameRequest(fetcher, connection, input));
  const match = new MatchClient(input => authenticatedMatchRequest(fetcher, connection, input));
  const savedSets = new SavedSetClient(input => authenticatedSavedSetRequest(fetcher, connection, input));
  const settings = new SettingsClient(input => authenticatedSettingsRequest(fetcher, connection, input));
  const library = new LibraryClient((route, query) => authenticatedGet(fetcher, connection, route, query));

  async function findFixtureActivity(): Promise<SelectedFixtureActivity> {
    for (let offset = 0; ; offset += 100) {
      const activities = await match.activities({ offset, limit: 100 });
      for (const item of activities.items.filter(activity => activity.name.startsWith(ACTIVITY_PREFIX))) {
        const detail = await match.activity(item.id);
        const sets = await savedSets.list({ activityId: item.id, offset: 0, limit: 100 });
        const explicit = sets.items.find(set => set.name === 'Explicit subset' && set.count === 2);
        if (!explicit || !detail.queries.some(query => query.id === explicit.query_id)) continue;
        const candidates = await match.candidates({ queryId: explicit.query_id, evidence: 'all', sort: 'relevance', offset: 0, limit: 100 });
        if (candidates.total < 2) continue;
        const plans = await match.plans({ activityId: item.id, offset: 0, limit: 200 });
        const plan = plans.items.find(value => value.query_id === explicit.query_id);
        return {
          id: item.id, name: item.name, queryId: explicit.query_id,
          scopeValue: plan ? `plan:${plan.id}` : `query:${explicit.query_id}`,
          resultCount: detail.queries.find(query => query.id === explicit.query_id)!.result_count,
        };
      }
      if (offset + activities.items.length >= activities.total) break;
    }
    throw new Error('No fresh Query UI acceptance activity with its own two-member Explicit subset was found.');
  }

  const selected = await findFixtureActivity();
  const creatorInputs = new Map<CreatorSort, CreatorListInput>();
  const creatorPages = new Map<CreatorSort, Awaited<ReturnType<CreatorClient['list']>>>();
  for (const sort of ['relevance', 'followers', 'recent_publish', 'recent_added'] as const) {
    const input: CreatorListInput = { query: '', platforms: [], languages: ['en'], sort, onlyCollection: false, offset: 0, limit: 50 };
    creatorInputs.set(sort, input);
    creatorPages.set(sort, await creators.list(input));
  }
  expect(creatorPages.get('relevance')!.total).toBe(3);
  for (const page of creatorPages.values()) {
    expect(page.items).toHaveLength(3);
    expect(page.items.every(item => (item.recent_works?.length ?? 0) <= 3)).toBe(true);
  }

  const gamePages = new Map<GameSort, Awaited<ReturnType<GameClient['list']>>>();
  for (const sort of ['recent_updated', 'recent_added', 'name'] as const) {
    const input: GameListInput = { query: '', onlyCollection: false, websiteStatus: 'available', sort, offset: 0, limit: 24 };
    const page = await games.list(input);
    expect(page.total).toBeGreaterThan(0);
    expect(page.items.every(item => Boolean(item.website_url?.trim()))).toBe(true);
    gamePages.set(sort, page);
  }
  const currentGameCandidates = await match.candidates({ queryId: selected.queryId, evidence: 'current_game', sort: 'relevance', offset: 0, limit: 100 });
  const allFollowerCandidates = await match.candidates({ queryId: selected.queryId, evidence: 'all', sort: 'followers', offset: 0, limit: 100 });
  const markedCandidate = allFollowerCandidates.items.find(item => item.creator && !item.identity_changed);
  expect(markedCandidate, 'The accepted fixture must retain an inspectable current Creator candidate.').toBeTruthy();

  let preferences: Preferences = { appearance: 'system', fontSize: 'default', automaticUpdates: true };
  const updateState: UpdateState = {
    phase: 'development', installedVersion: '0.2.0-alpha.1', lastCheckedAt: null, lastAttemptAt: null,
    release: null, error: null,
  };
  const unexpectedBridgeCalls: string[] = [];
  const rejected = async (name: string): Promise<never> => {
    unexpectedBridgeCalls.push(name);
    throw new Error('Renderer attempted an operation outside this read-only integration flow.');
  };
  const actions: Record<string, (input: any) => Promise<unknown>> = {
    'connection.status': async () => ({ serviceUrl: FIXTURE_ORIGIN, hasKey: true, storageAvailable: true }),
    'connection.test': async () => { await library.session(); return { authenticated: true, proxy: 'system', route: 'direct' }; },
    'connection.save': () => rejected('connection.save'),
    'connection.clear': () => rejected('connection.clear'),
    'preferences.read': async () => preferences,
    'preferences.update': async input => { preferences = { ...preferences, ...input }; return preferences; },
    'preferences.restoreAppearance': async () => { preferences = { ...preferences, appearance: 'system', fontSize: 'default' }; return preferences; },
    'updates.status': async () => updateState,
    'updates.check': async () => updateState,
    'library.list': input => library.list(input),
    'library.detail': input => library.detail(input),
    'games.list': input => games.list(input),
    'games.detail': input => games.detail(input),
    'games.create': () => rejected('games.create'),
    'games.update': () => rejected('games.update'),
    'creators.list': input => creators.list(input),
    'creators.detail': input => creators.detail(input),
    'creators.works': input => creators.works(input),
    'creators.create': () => rejected('creators.create'),
    'creators.update': () => rejected('creators.update'),
    'creators.rebind': () => rejected('creators.rebind'),
    'creators.createContact': () => rejected('creators.createContact'),
    'creators.updateContact': () => rejected('creators.updateContact'),
    'creators.createWork': () => rejected('creators.createWork'),
    'creators.updateWork': () => rejected('creators.updateWork'),
    'settings.collection': () => settings.collection(),
    'settings.setCollection': () => rejected('settings.setCollection'),
    'settings.connection': () => rejected('settings.connection'),
    'settings.replaceConnection': () => rejected('settings.replaceConnection'),
    'settings.testConnection': () => rejected('settings.testConnection'),
    'settings.reanalysis': () => rejected('settings.reanalysis'),
    'settings.saveReanalysis': () => rejected('settings.saveReanalysis'),
    'settings.smtp': () => rejected('settings.smtp'),
    'settings.saveSMTP': () => rejected('settings.saveSMTP'),
    'settings.testSMTP': () => rejected('settings.testSMTP'),
    'settings.sendTestEmail': () => rejected('settings.sendTestEmail'),
    'match.activities': input => match.activities(input),
    'match.activity': input => match.activity(input),
    'match.plans': input => match.plans(input),
    'match.plan': input => match.plan(input),
    'match.query': input => match.query(input),
    'match.candidates': (input: CandidateListInput) => match.candidates(input),
    'match.evaluations': input => match.evaluations(input),
    'match.evaluation': input => match.evaluation(input),
    'match.evaluationResults': input => match.evaluationResults(input),
    'match.createActivity': () => rejected('match.createActivity'),
    'match.createPlan': () => rejected('match.createPlan'),
    'match.retryPlan': () => rejected('match.retryPlan'),
    'match.stop': () => rejected('match.stop'),
    'match.continueDiscovery': () => rejected('match.continueDiscovery'),
    'match.evaluate': () => rejected('match.evaluate'),
    'match.retryEvaluation': () => rejected('match.retryEvaluation'),
    'savedSets.list': input => savedSets.list(input),
    'savedSets.detail': input => savedSets.detail(input),
    'savedSets.results': input => savedSets.results(input),
    'savedSets.create': input => savedSets.create(input),
    'openExternal': async () => undefined,
  };

  const { server, origin: rendererOrigin } = await serveRenderer();
  const context = await browser.newContext({ viewport: { width: 1320, height: 920 }, reducedMotion: 'reduce' });
  let blockedBrowserRequests = 0;
  await context.route('**/*', async route => {
    let requestOrigin = '';
    try { requestOrigin = new URL(route.request().url()).origin; } catch { /* Non-network schemes are not permitted here. */ }
    if (requestOrigin === rendererOrigin) await route.continue();
    else { blockedBrowserRequests++; await route.abort('blockedbyclient'); }
  });
  const page = await context.newPage();
  let pageErrors = 0;
  let consoleProblems = 0;
  let sensitiveBrowserMessage = false;
  page.on('pageerror', error => {
    const message = String(error);
    pageErrors++;
    if (message.includes(fixture.workspace_key)) sensitiveBrowserMessage = true;
  });
  page.on('console', message => {
    if (message.type() !== 'error' && message.type() !== 'warning') return;
    consoleProblems++;
    if (message.text().includes(fixture.workspace_key)) sensitiveBrowserMessage = true;
  });

  try {
    await page.exposeBinding('__fmgInvoke', async (_source, name: string, input: unknown) => {
      const action = actions[name];
      if (!action) {
        unexpectedBridgeCalls.push(name);
        return publicResult(() => Promise.reject(new Error('Unknown renderer bridge action.')));
      }
      return publicResult(() => action(input));
    });
    await page.addInitScript(() => {
      const invoke = (name: string, input?: unknown) => (window as any).__fmgInvoke(name, input);
      const group = (name: string, methods: string[]) => Object.fromEntries(methods.map(method => [method, (input?: unknown) => invoke(`${name}.${method}`, input)]));
      Object.defineProperty(window, 'desktop', { configurable: false, enumerable: true, value: {
        connection: group('connection', ['status', 'save', 'test', 'clear']),
        preferences: group('preferences', ['read', 'update', 'restoreAppearance']),
        updates: group('updates', ['status', 'check']),
        library: group('library', ['list', 'detail']),
        games: group('games', ['list', 'detail', 'create', 'update']),
        creators: group('creators', ['list', 'detail', 'create', 'update', 'rebind', 'createContact', 'updateContact', 'works', 'createWork', 'updateWork']),
        settings: group('settings', ['collection', 'setCollection', 'connection', 'replaceConnection', 'testConnection', 'reanalysis', 'saveReanalysis', 'smtp', 'saveSMTP', 'testSMTP', 'sendTestEmail']),
        match: group('match', ['activities', 'createActivity', 'activity', 'plans', 'createPlan', 'plan', 'retryPlan', 'query', 'candidates', 'stop', 'continueDiscovery', 'evaluations', 'evaluate', 'evaluation', 'evaluationResults', 'retryEvaluation']),
        savedSets: group('savedSets', ['list', 'detail', 'results', 'create']),
        openExternal: (url: string) => invoke('openExternal', url),
      } });
    });

    await page.goto(rendererOrigin, { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/FindMeGamer/);
    await expect(page.getByRole('heading', { name: 'Library', level: 1 })).toBeVisible();
    await expect(page.getByText('Workspace connected', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
    await expect(page.locator('[data-testid="vite-error-overlay"], vite-error-overlay')).toHaveCount(0);

    const creatorList = page.getByRole('list', { name: 'Creators' });
    await expect(creatorList).toBeVisible();
    const languageButton = page.getByRole('button', { name: 'Languages: Any' });
    const creatorListReads = () => records.filter(record => record.method === 'GET' && record.path === '/api/v2/library/creators').length;

    const beforeCancel = creatorListReads();
    await languageButton.click();
    await page.getByRole('dialog', { name: 'Languages' }).getByLabel('English · en').check();
    await page.getByRole('dialog', { name: 'Languages' }).getByRole('button', { name: 'Cancel' }).click();
    await expect(languageButton).toBeFocused();
    expect(creatorListReads()).toBe(beforeCancel);

    const beforeEscape = creatorListReads();
    await languageButton.click();
    await page.getByRole('dialog', { name: 'Languages' }).getByLabel('English · en').check();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Languages' })).toHaveCount(0);
    await expect(languageButton).toBeFocused();
    expect(creatorListReads()).toBe(beforeEscape);

    await languageButton.click();
    await page.getByRole('dialog', { name: 'Languages' }).getByLabel('English · en').check();
    await page.getByRole('dialog', { name: 'Languages' }).getByRole('button', { name: 'Apply' }).click();
    await expect(page.locator('.creator-library .list-caption').getByText('1–3 of 3', { exact: true })).toBeVisible();
    await expect(creatorList.getByRole('button').first()).toHaveAttribute('aria-label', `Open ${creatorName(creatorPages.get('relevance')!.items[0])}`);
    expect(records.some(record => record.path === '/api/v2/library/creators' && record.search.includes('languages=en'))).toBe(true);

    const creatorSort = page.getByLabel('Sort creators');
    for (const sort of ['followers', 'recent_publish', 'recent_added', 'relevance'] as const) {
      await creatorSort.selectOption(sort);
      await expect(creatorSort).toHaveValue(sort);
      await expect(creatorList.getByRole('button').first()).toHaveAttribute('aria-label', `Open ${creatorName(creatorPages.get(sort)!.items[0])}`);
    }

    const creatorTab = page.getByRole('tab', { name: 'Creators' });
    await creatorTab.focus();
    await page.keyboard.press('ArrowRight');
    const gameTab = page.getByRole('tab', { name: 'Games' });
    await expect(gameTab).toHaveAttribute('aria-selected', 'true');
    await expect(gameTab).toBeFocused();
    const gamesList = page.getByRole('list', { name: 'Games' });
    await expect(gamesList).toBeVisible();
    const website = page.getByLabel('Website');
    await website.selectOption('available');
    await expect(website).toHaveValue('available');
    const gameSort = page.getByLabel('Sort games');
    for (const sort of ['recent_updated', 'recent_added', 'name'] as const) {
      await gameSort.selectOption(sort);
      const expected = gamePages.get(sort)!;
      await expect(page.locator('.game-pagination span')).toHaveText(`1–${expected.items.length} of ${expected.total}`);
      await expect(gamesList.getByRole('button').first()).toHaveAttribute('aria-label', `Open ${expected.items[0].name || expected.items[0].website_url || 'Untitled game'}`);
    }

    await page.getByRole('button', { name: 'Match', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Match', level: 1 })).toBeVisible();
    let activityButton = page.getByRole('button', { name: `Open ${selected.name}` });
    for (let pageNumber = 0; await activityButton.count() === 0 && pageNumber < 10; pageNumber++) {
      const next = page.getByRole('button', { name: 'Next page' });
      expect(await next.isEnabled()).toBe(true);
      await next.click();
      await expect(page.getByText(/\d+–\d+ of \d+/).first()).toBeVisible();
      activityButton = page.getByRole('button', { name: `Open ${selected.name}` });
    }
    await activityButton.click();
    await expect(page.getByRole('heading', { name: selected.name, level: 1 })).toBeVisible();
    const searchHistory = page.getByLabel('Search history');
    await searchHistory.selectOption(selected.scopeValue);
    await expect(searchHistory).toHaveValue(selected.scopeValue);

    const queryControls = page.getByLabel('Candidate filters and order');
    const evidence = queryControls.getByLabel('Evidence');
    const order = queryControls.getByLabel('Order');
    await expect(queryControls).toBeVisible();
    await evidence.selectOption('current_game');
    await expect(queryControls.getByRole('status')).toHaveText(`${currentGameCandidates.total} matching of ${selected.resultCount} discovered`);
    await evidence.selectOption('all');
    await order.selectOption('followers');
    await expect(queryControls.getByRole('status')).toHaveText(`${allFollowerCandidates.total} matching of ${selected.resultCount} discovered`);

    const savedName = `Renderer saved ${randomUUID().slice(0, 8)}`;
    await page.getByRole('button', { name: 'Save list' }).click();
    const composer = page.getByRole('form', { name: 'Save candidate list' });
    await composer.getByLabel('List name').fill(savedName);
    const chosenCard = page.getByRole('article', { name: candidateName(markedCandidate!) });
    await chosenCard.getByRole('checkbox', { name: `Include ${candidateName(markedCandidate!)} in saved list` }).check();
    await expect(composer.getByText('1 marked', { exact: true })).toBeVisible();
    await composer.getByRole('button', { name: 'Save 1 creator' }).click();

    const savedResults = page.getByRole('region', { name: 'Saved list results' });
    await expect(savedResults.getByRole('heading', { name: savedName, level: 2 })).toBeVisible();
    await expect(savedResults.getByText('1 saved', { exact: true })).toBeVisible();
    await expect(savedResults.getByRole('article')).toHaveCount(1);
    const savedViewCreator = savedResults.getByRole('button', { name: 'View creator' });
    await savedViewCreator.scrollIntoViewIfNeeded();
    const savedScroll = await page.locator('.main-scroll').evaluate(element => element.scrollTop);
    await savedViewCreator.click();
    await expect(page.getByRole('heading', { name: creatorName(markedCandidate!.creator!), level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Back to activity' }).click();
    await expect(savedResults.getByRole('heading', { name: savedName, level: 2 })).toBeVisible();
    await expect(savedViewCreator).toBeFocused();
    expect(Math.abs(await page.locator('.main-scroll').evaluate(element => element.scrollTop) - savedScroll)).toBeLessThanOrEqual(2);

    await savedResults.getByRole('button', { name: 'Original search' }).click();
    await expect(queryControls).toBeVisible();
    await expect(evidence).toHaveValue('all');
    await expect(order).toHaveValue('followers');
    const originalViewCreator = page.getByRole('region', { name: 'Candidate results' }).getByRole('button', { name: 'View creator' }).first();
    await originalViewCreator.scrollIntoViewIfNeeded();
    const originalScroll = await page.locator('.main-scroll').evaluate(element => element.scrollTop);
    await originalViewCreator.click();
    await expect(page.getByRole('button', { name: 'Back to activity' })).toBeVisible();
    await page.getByRole('button', { name: 'Back to activity' }).click();
    await expect(queryControls).toBeVisible();
    await expect(evidence).toHaveValue('all');
    await expect(order).toHaveValue('followers');
    await expect(originalViewCreator).toBeFocused();
    expect(Math.abs(await page.locator('.main-scroll').evaluate(element => element.scrollTop) - originalScroll)).toBeLessThanOrEqual(2);

    async function assertNoHorizontalOverflow(label: string) {
      const geometry = await page.evaluate(() => {
        const root = document.documentElement;
        const body = document.body;
        const main = document.querySelector<HTMLElement>('.main-scroll');
        return {
          root: { client: root.clientWidth, scroll: root.scrollWidth },
          body: { client: body.clientWidth, scroll: body.scrollWidth },
          main: main ? { client: main.clientWidth, scroll: main.scrollWidth } : null,
        };
      });
      expect(geometry.root.scroll, `${label}: document overflow`).toBeLessThanOrEqual(geometry.root.client + 1);
      expect(geometry.body.scroll, `${label}: body overflow`).toBeLessThanOrEqual(geometry.body.client + 1);
      expect(geometry.main, `${label}: main scroller missing`).not.toBeNull();
      expect(geometry.main!.scroll, `${label}: main overflow`).toBeLessThanOrEqual(geometry.main!.client + 1);
    }

    await assertNoHorizontalOverflow('wide 1320');
    await page.screenshot({ path: testInfo.outputPath('query-renderer-wide.png'), fullPage: true });
    await page.setViewportSize({ width: 760, height: 720 });
    await assertNoHorizontalOverflow('narrow 760');
    await page.screenshot({ path: testInfo.outputPath('query-renderer-narrow.png'), fullPage: true });
    await page.setViewportSize({ width: 1320, height: 920 });
    await page.evaluate(() => { document.documentElement.style.fontSize = '135%'; });
    expect(await page.evaluate(() => Number.parseFloat(getComputedStyle(document.documentElement).fontSize))).toBeCloseTo(21.6, 1);
    await assertNoHorizontalOverflow('large font 135%');
    await page.screenshot({ path: testInfo.outputPath('query-renderer-large-font.png'), fullPage: true });

    const writes = records.filter(record => record.method !== 'GET');
    expect(writes).toHaveLength(1);
    expect(writes[0].method).toBe('POST');
    expect(savedSetCreate.test(writes[0].path)).toBe(true);
    expect(unexpectedRequests).toEqual([]);
    expect(unexpectedBridgeCalls).toEqual([]);
    expect(records.some(record => /selection|outreach|smtp/i.test(record.path))).toBe(false);
    // Remote artwork is intentionally blocked in this integration harness; the
    // production Artwork fallback must keep the public UI usable without it.
    testInfo.annotations.push({ type: 'external browser requests blocked', description: String(blockedBrowserRequests) });
    expect(sensitiveBrowserMessage).toBe(false);
    expect(pageErrors).toBe(0);
    expect(consoleProblems).toBe(0);
  } finally {
    await context.close();
    await closeServer(server);
  }
});
