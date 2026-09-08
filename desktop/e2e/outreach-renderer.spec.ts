import { expect, test, type BrowserContext } from '@playwright/test';
import { readFile, stat, writeFile } from 'node:fs/promises';
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
import { OutreachClient } from '../src/main/outreach-client';
import { authenticatedOutreachRequest } from '../src/main/outreach-transport';
import { SavedSetClient } from '../src/main/saved-set-client';
import { authenticatedSavedSetRequest } from '../src/main/saved-set-transport';
import { SettingsClient } from '../src/main/settings-client';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';
import { authenticatedGameRequest, authenticatedGet, publicResult, type Connection, type Fetcher } from '../src/main/transport';
import type { CandidateView } from '../src/shared/match';
import type { Preparation, RecipientBatchPage } from '../src/shared/outreach';
import type { Preferences, UpdateState } from '../src/shared/preferences';

// Built production renderer + production clients + real pinned HTTP. This does
// not claim Electron, IPC, Keychain, native shell, or packaged-app acceptance.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
test.describe.configure({ mode: 'serial' });

const FIXTURE_FILE = process.env.FMG_QUERY_RENDERER_FIXTURE_FILE;
const ACTIVITY_ID = process.env.FMG_OUTREACH_ACTIVITY_ID;
const HISTORY_ONLY = process.env.FMG_OUTREACH_HISTORY_ONLY === '1';
test.skip(!FIXTURE_FILE || !ACTIVITY_ID,
  'Requires the exclusive pinned fixture handoff, public F7 Activity ID, and coordinator-approved managed Chromium run.');

const FIXTURE_ORIGIN = 'http://127.0.0.1:65164';
const BACKEND_PIN = 'a852307d6908e671ae1998c9741f19ffe65f5048';
const MIGRATION_PIN = '20260908_0015';
const PINNED_ACTIVITY_ID = '40425b20-7241-4e44-965b-0ac3a5fb0165';
const PINNED_QUERY_IDS = new Set(['e24f9146-ac23-492f-86c1-894dd04f003a', '8f7bbd81-6076-4ecc-922a-2aed471a77a4']);
const PINNED_ACTIVE_SELECTION_ID = '98772f17-93b7-4191-b5b5-a6404d8946af';
const PINNED_CANCELLED_SELECTION_ID = '3bc9cc29-2d0d-46ba-a667-a04dcc1dc24e';
const PINNED_CREATOR_ID = '14b26ddb-02e5-460f-a67f-77a1f1b7dd12';
const PINNED_FIRST_CONTACT_ID = 'd4e1335b-da1a-46b2-8406-de8a7df5349c';
const PINNED_SELECTED_CONTACT_ID = 'cab88107-9a2b-49be-8fb8-df7ff02f51cd';
const PINNED_BATCH_IDS = new Set(['adb1bbf2-6c01-4d98-a813-017d4ba69e81', 'bf4967e1-2364-4098-bc67-42f47296a7a6']);
const PINNED_UNSELECTED_CANDIDATE_IDS = new Set([
  'bd68ab41-5c2a-4f1b-abb7-7a232e503d95', '27e81059-903c-4918-8316-3310138db17e',
  'c3984925-c3c2-4df1-bba8-77cfb7ab1362', '0bc7ba17-8402-4cce-a586-7de8649053f0',
  'e06d87db-84a0-434a-8ace-db04e5d39d8d', 'c2c9201c-e31c-4501-8eb8-a75deb48aa30',
]);
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

const identityKey = (value: { platform: string; account_id: string }) => `${value.platform}\u0000${value.account_id}`;
const preparationName = (value: Preparation) => value.name || value.public_name || value.identity.account_id;
const candidateName = (value: CandidateView) => {
  const display = value.account.display_name, handle = value.account.handle;
  return typeof display === 'string' && display.trim() ? display
    : typeof handle === 'string' && handle.trim() ? handle : value.account_id;
};

async function serveRenderer(): Promise<{ server: Server; origin: string }> {
  const rendererRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../out/renderer');
  const server = createServer(async (request, response) => {
    if (request.method !== 'GET' || !request.url) { response.writeHead(405).end(); return; }
    let pathname: string;
    try { pathname = decodeURIComponent(new URL(request.url, 'http://renderer.invalid').pathname); }
    catch { response.writeHead(400).end(); return; }
    const relative = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
    const target = path.resolve(rendererRoot, relative);
    if (target !== rendererRoot && !target.startsWith(`${rendererRoot}${path.sep}`)) { response.writeHead(403).end(); return; }
    try {
      const body = await readFile(target), extension = path.extname(target);
      const mime: Record<string, string> = {
        '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
        '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2',
      };
      response.writeHead(200, { 'Content-Type': mime[extension] ?? 'application/octet-stream', 'Cache-Control': 'no-store' });
      response.end(body);
    } catch { response.writeHead(404).end(); }
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve());
  });
  return { server, origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}` };
}

async function closeServer(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
}

test('production renderer prepares explicit outreach people and preserves immutable history through real HTTP', async ({ browser }, testInfo) => {
  test.setTimeout(180_000);
  const activityId = ACTIVITY_ID;
  if (!FIXTURE_FILE || !activityId) return;

  expect(activityId).toBe(PINNED_ACTIVITY_ID);
  expect(path.basename(FIXTURE_FILE)).toBe('client.json');
  const privateDirectory = path.dirname(FIXTURE_FILE);
  expect((await stat(FIXTURE_FILE)).mode & 0o777).toBe(0o600);
  expect((await stat(privateDirectory)).mode & 0o777).toBe(0o700);
  let fixture: PrivateFixture;
  try { fixture = JSON.parse(await readFile(FIXTURE_FILE, 'utf8')) as PrivateFixture; }
  catch { throw new Error('Private renderer fixture unavailable; sensitive details suppressed.'); }
  expect(fixture.base_url).toBe(FIXTURE_ORIGIN);
  expect(fixture.backend_revision).toBe(BACKEND_PIN);
  expect(fixture.migration).toBe(MIGRATION_PIN);
  expect(typeof fixture.workspace_key === 'string' && fixture.workspace_key.length > 0).toBe(true);

  const records: RequestRecord[] = [];
  const unexpectedRequests: { method: string; path: string }[] = [];
  const unexpectedBridgeCalls: string[] = [];
  const bridgeCalls = new Map<string, number>();
  let blockedBrowserRequests = 0, pageErrors = 0, consoleProblems = 0, sensitiveBrowserMessage = false;
  let managedContext: BrowserContext | null = null;
  let rendererServer: Server | null = null;
  try {
  const activityBase = `/api/v2/activities/${activityId}`;
  const selectionCollection = new RegExp(`^${activityBase}/selections$`);
  const selectionBulk = new RegExp(`^${activityBase}/selections/bulk$`);
  const selectionMutation = new RegExp(`^${activityBase}/selections/${UUID_ROUTE}/(update|cancel)$`);
  const batchCollection = new RegExp(`^${activityBase}/recipient-batches$`);
  const queryStop = new RegExp(`^/api/v2/discovery/queries/(${[...PINNED_QUERY_IDS].join('|')})/stop$`);
  const readRoutes = [
    /^\/api\/v1\/session$/, /^\/api\/v1\/settings\/collection$/,
    /^\/api\/v2\/library\/(creators|games)(\/|$)/, /^\/api\/v2\/activities(\/|$)/, /^\/api\/v2\/discovery\//,
  ];
  const fetcher: Fetcher = async (url, init) => {
    const target = new URL(url), method = String(init.method ?? 'GET').toUpperCase();
    const allowedRead = method === 'GET' && readRoutes.some(route => route.test(target.pathname));
    const allowedWrite = !HISTORY_ONLY && method === 'POST' && (selectionCollection.test(target.pathname) || selectionBulk.test(target.pathname)
      || selectionMutation.test(target.pathname) || batchCollection.test(target.pathname) || queryStop.test(target.pathname));
    if (target.origin !== FIXTURE_ORIGIN || (!allowedRead && !allowedWrite)) {
      unexpectedRequests.push({ method, path: target.pathname });
      throw new Error('Outreach renderer request escaped the strict fixture allowlist.');
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
  const library = new LibraryClient((route, query) => authenticatedGet(fetcher, connection, route, query));
  const match = new MatchClient(input => authenticatedMatchRequest(fetcher, connection, input));
  const outreach = new OutreachClient(input => authenticatedOutreachRequest(fetcher, connection, input));
  const savedSets = new SavedSetClient(input => authenticatedSavedSetRequest(fetcher, connection, input));
  const settings = new SettingsClient(input => authenticatedSettingsRequest(fetcher, connection, input));

  let activityPageOffset = -1;
  let listedActivityName = '';
  for (let offset = 0; offset < 10_000; offset += 50) {
    const page = await match.activities({ offset, limit: 50 });
    const found = page.items.find(item => item.id === activityId);
    if (found) { activityPageOffset = offset; listedActivityName = found.name; break; }
    if (offset + page.items.length >= page.total) break;
  }
  expect(activityPageOffset, 'The exact accepted Activity must remain in the public list.').toBeGreaterThanOrEqual(0);
  const activity = await match.activity(activityId);
  expect(activity.id).toBe(activityId);
  expect(activity.name).toBe(listedActivityName);
  expect(new Set(activity.queries.map(item => item.id))).toEqual(PINNED_QUERY_IDS);
  const exactSourceSnapshot = JSON.stringify(activity.source_snapshot);
  expect(exactSourceSnapshot.length).toBeGreaterThan(2);

  const initialSelections = await outreach.selections({ activityId, includeCancelled: true, offset: 0, limit: 200 });
  expect(initialSelections.total).toBe(HISTORY_ONLY ? 3 : 2);
  const initialActive = initialSelections.items.find(item => item.id === PINNED_ACTIVE_SELECTION_ID);
  const initialCancelled = initialSelections.items.find(item => item.id === PINNED_CANCELLED_SELECTION_ID);
  expect(initialActive?.active).toBe(true);
  expect(initialCancelled?.active).toBe(false);
  expect(initialActive?.creator_id).toBe(PINNED_CREATOR_ID);
  expect(initialActive?.public_name).toBeTruthy();
  expect(initialActive?.public_name_confirmed).toBe(HISTORY_ONLY);
  expect(initialActive?.contact_status).toBe(HISTORY_ONLY ? 'eligible' : 'changed');
  expect(initialActive?.selected_contact?.id).toBe(PINNED_SELECTED_CONTACT_ID);
  expect(initialActive?.contact_options.some(item => item.id === PINNED_FIRST_CONTACT_ID && item.status === 'eligible')).toBe(true);
  const pinnedCurrentContact = initialActive?.contact_options.find(item => item.id === PINNED_SELECTED_CONTACT_ID);
  expect(pinnedCurrentContact?.status).toBe('eligible');
  if (!HISTORY_ONLY) {
    expect(pinnedCurrentContact?.purpose).not.toBe(initialActive?.selected_contact?.purpose);
    expect(pinnedCurrentContact?.source_url).not.toBe(initialActive?.selected_contact?.source_url);
  }
  const initialBatches = await outreach.batches({ activityId, offset: 0, limit: 200 });
  expect(initialBatches.total).toBe(HISTORY_ONLY ? 3 : 2);
  expect(new Set(initialBatches.items.filter(item => !HISTORY_ONLY || PINNED_BATCH_IDS.has(item.id)).map(item => item.id))).toEqual(PINNED_BATCH_IDS);
  const historyBatchIds = initialBatches.items.filter(item => !PINNED_BATCH_IDS.has(item.id)).map(item => item.id);
  if (HISTORY_ONLY) {
    expect(historyBatchIds).toHaveLength(1);
    expect(initialSelections.items.filter(item => item.active)).toHaveLength(2);
  }

  const plansPage = await match.plans({ activityId, offset: 0, limit: 200 });
  const plans = await Promise.all(plansPage.items.map(item => match.plan(item.id)));
  const selectedIdentityKeys = new Set(initialSelections.items.filter(item => item.active).map(item => identityKey(item.identity)));
  let targetPlan = plans[0];
  let targetCandidates: CandidateView[] = [];
  let unselectedCandidate: CandidateView | undefined;
  for (const plan of plans) {
    if (HISTORY_ONLY) break;
    if (!plan.query_id || !PINNED_QUERY_IDS.has(plan.query_id)) continue;
    const page = await match.candidates({ queryId: plan.query_id, evidence: 'all', sort: 'relevance', offset: 0, limit: 100 });
    const candidate = page.items.find(item => !item.identity_changed && PINNED_UNSELECTED_CANDIDATE_IDS.has(item.id)
      && !selectedIdentityKeys.has(identityKey(item)));
    if (candidate) { targetPlan = plan; targetCandidates = page.items; unselectedCandidate = candidate; break; }
  }
  if (!HISTORY_ONLY) {
    expect(targetPlan?.query_id && PINNED_QUERY_IDS.has(targetPlan.query_id)).toBe(true);
    expect(targetCandidates.length).toBeGreaterThan(0);
    expect(unselectedCandidate, 'The fixed Activity must retain one current, naturally unselected candidate row.').toBeTruthy();
  }
  const targetQueryId = targetPlan.query_id!;
  const unselectedName = HISTORY_ONLY ? '' : candidateName(unselectedCandidate!);
  const activeName = preparationName(initialActive!);
  const sensitiveBrowserValues = [fixture.workspace_key, ...initialActive!.contact_options.map(item => item.email)];

  const knownCandidateIds = new Set(targetCandidates.map(item => item.id));
  const knownSelectionIds = new Set(initialSelections.items.map(item => item.id));
  const knownBatchIds = new Set(initialBatches.items.map(item => item.id));
  const knownCreatorIds = new Set([...targetCandidates.map(item => item.creator_id), ...initialSelections.items.map(item => item.creator_id)]);
  let addedPreparation: Preparation | null = null;
  let frozenBatchId = '';
  let latestBatchPage: RecipientBatchPage | null = null;
  let lastBatchReadId = '';
  const count = (name: string) => bridgeCalls.get(name) ?? 0;
  const ownActivity = (name: string, input: { activityId?: unknown }) => {
    if (input?.activityId !== activityId) { unexpectedBridgeCalls.push(`${name}:activity`); throw new Error('Business action targeted another Activity.'); }
  };
  const rejected = async (name: string): Promise<never> => {
    unexpectedBridgeCalls.push(name);
    throw new Error('Renderer attempted an operation outside the accepted outreach flow.');
  };
  const preferences: Preferences = { appearance: 'system', fontSize: 'default', automaticUpdates: true };
  const updateState: UpdateState = {
    phase: 'development', installedVersion: '0.2.0-alpha.1', lastCheckedAt: null, lastAttemptAt: null,
    release: null, error: null,
  };
  const actions: Record<string, (input: any) => Promise<unknown>> = {
    'connection.status': async () => ({ serviceUrl: FIXTURE_ORIGIN, hasKey: true, storageAvailable: true }),
    'connection.test': async () => { await library.session(); return { authenticated: true, proxy: 'system', route: 'direct' }; },
    'connection.save': () => rejected('connection.save'),
    'connection.clear': () => rejected('connection.clear'),
    'preferences.read': async () => preferences,
    'preferences.update': () => rejected('preferences.update'),
    'preferences.restoreAppearance': () => rejected('preferences.restoreAppearance'),
    'updates.status': async () => updateState,
    'updates.check': async () => updateState,
    'library.list': input => library.list(input),
    'library.detail': input => library.detail(input),
    'games.list': input => games.list(input),
    'games.detail': input => games.detail(input),
    'games.create': () => rejected('games.create'),
    'games.update': () => rejected('games.update'),
    'creators.list': input => creators.list(input),
    'creators.detail': input => {
      if (!knownCreatorIds.has(input)) return rejected('creators.detail:foreign');
      return creators.detail(input);
    },
    'creators.works': input => {
      if (!knownCreatorIds.has(input?.creatorId)) return rejected('creators.works:foreign');
      return creators.works(input);
    },
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
    'match.activity': input => {
      if (input !== activityId) return rejected('match.activity:foreign');
      return match.activity(input);
    },
    'match.plans': input => { ownActivity('match.plans', input); return match.plans(input); },
    'match.plan': input => {
      if (!plans.some(item => item.id === input)) return rejected('match.plan:foreign');
      return match.plan(input);
    },
    'match.query': input => {
      if (!PINNED_QUERY_IDS.has(input)) return rejected('match.query:foreign');
      return match.query(input);
    },
    'match.candidates': input => {
      if (!PINNED_QUERY_IDS.has(input?.queryId)) return rejected('match.candidates:foreign');
      return match.candidates(input);
    },
    'match.evaluations': input => {
      if (!PINNED_QUERY_IDS.has(input?.queryId)) return rejected('match.evaluations:foreign');
      return match.evaluations(input);
    },
    'match.evaluation': input => match.evaluation(input),
    'match.evaluationResults': input => match.evaluationResults(input),
    'match.stop': input => {
      if (input?.queryId !== targetQueryId) return rejected('match.stop:foreign');
      return match.stop(input);
    },
    'match.createActivity': () => rejected('match.createActivity'),
    'match.createPlan': () => rejected('match.createPlan'),
    'match.retryPlan': () => rejected('match.retryPlan'),
    'match.continueDiscovery': () => rejected('match.continueDiscovery'),
    'match.evaluate': () => rejected('match.evaluate'),
    'match.retryEvaluation': () => rejected('match.retryEvaluation'),
    'savedSets.list': input => { ownActivity('savedSets.list', input); return savedSets.list(input); },
    'savedSets.detail': input => savedSets.detail(input),
    'savedSets.results': input => savedSets.results(input),
    'savedSets.create': () => rejected('savedSets.create'),
    'outreach.selections': input => { ownActivity('outreach.selections', input); return outreach.selections(input); },
    'outreach.selection': input => {
      ownActivity('outreach.selection', input);
      if (!knownSelectionIds.has(input?.id)) return rejected('outreach.selection:foreign');
      return outreach.selection(input);
    },
    'outreach.add': async input => {
      ownActivity('outreach.add', input);
      if (!knownCandidateIds.has(input?.data?.candidate_id)) return rejected('outreach.add:foreign');
      const result = await outreach.add(input); knownSelectionIds.add(result.id); addedPreparation = result; return result;
    },
    'outreach.bulk': async input => {
      ownActivity('outreach.bulk', input);
      const additions: string[] = input?.data?.add_candidate_ids ?? [];
      const cancellations: Array<{ selection_id: string }> = input?.data?.cancel_selections ?? [];
      if (additions.some(id => !knownCandidateIds.has(id)) || cancellations.some(item => !knownSelectionIds.has(item.selection_id))) {
        return rejected('outreach.bulk:foreign');
      }
      const result = await outreach.bulk(input); result.added_selection_ids.forEach(id => knownSelectionIds.add(id)); return result;
    },
    'outreach.update': input => {
      ownActivity('outreach.update', input);
      if (!knownSelectionIds.has(input?.id)) return rejected('outreach.update:foreign');
      return outreach.update(input);
    },
    'outreach.cancel': input => {
      ownActivity('outreach.cancel', input);
      if (!knownSelectionIds.has(input?.id)) return rejected('outreach.cancel:foreign');
      return outreach.cancel(input);
    },
    'outreach.batches': async input => {
      ownActivity('outreach.batches', input);
      const result = await outreach.batches(input); latestBatchPage = result; return result;
    },
    'outreach.batch': input => {
      ownActivity('outreach.batch', input);
      if (!knownBatchIds.has(input?.id)) return rejected('outreach.batch:foreign');
      lastBatchReadId = input.id;
      return outreach.batch(input);
    },
    'outreach.freeze': async input => {
      ownActivity('outreach.freeze', input);
      const recipients: Array<{ selection_id: string }> = input?.data?.recipients ?? [];
      if (recipients.length !== 2 || recipients.some(item => !knownSelectionIds.has(item.selection_id))) return rejected('outreach.freeze:foreign');
      const result = await outreach.freeze(input); frozenBatchId = result.id; knownBatchIds.add(result.id); return result;
    },
    'openExternal': () => rejected('openExternal'),
  };

  const { server, origin: rendererOrigin } = await serveRenderer();
  rendererServer = server;
  const context = await browser.newContext({ viewport: { width: 1320, height: 920 }, reducedMotion: 'reduce' });
  managedContext = context;
  await context.route('**/*', async route => {
    let requestOrigin = '';
    try { requestOrigin = new URL(route.request().url()).origin; } catch { /* Non-network schemes stay blocked. */ }
    if (requestOrigin === rendererOrigin) await route.continue();
    else { blockedBrowserRequests++; await route.abort('blockedbyclient'); }
  });
  const page = await context.newPage();
  page.on('pageerror', error => {
    const message = String(error); pageErrors++;
    if (sensitiveBrowserValues.some(value => message.includes(value))) sensitiveBrowserMessage = true;
  });
  page.on('console', message => {
    const text = message.text();
    if (sensitiveBrowserValues.some(value => text.includes(value))) sensitiveBrowserMessage = true;
    if (['error', 'warning'].includes(message.type())) consoleProblems++;
  });

  async function assertNoHorizontalOverflow(label: string) {
    const geometry = await page.evaluate(() => {
      const root = document.documentElement, body = document.body, main = document.querySelector<HTMLElement>('.main-scroll');
      return { root: [root.clientWidth, root.scrollWidth], body: [body.clientWidth, body.scrollWidth],
        main: main ? [main.clientWidth, main.scrollWidth] : null };
    });
    expect(geometry.root[1], `${label}: document overflow`).toBeLessThanOrEqual(geometry.root[0] + 1);
    expect(geometry.body[1], `${label}: body overflow`).toBeLessThanOrEqual(geometry.body[0] + 1);
    expect(geometry.main, `${label}: main scroller missing`).not.toBeNull();
    expect(geometry.main![1], `${label}: main overflow`).toBeLessThanOrEqual(geometry.main![0] + 1);
  }

    await page.exposeBinding('__fmgInvoke', async (_source, name: string, input: unknown) => {
      bridgeCalls.set(name, count(name) + 1);
      if (HISTORY_ONLY && ['outreach.add', 'outreach.bulk', 'outreach.update', 'outreach.cancel', 'outreach.freeze', 'match.stop'].includes(name)) {
        return publicResult(() => rejected(name));
      }
      const action = actions[name];
      if (!action) { unexpectedBridgeCalls.push(name); return publicResult(() => Promise.reject(new Error('Unknown renderer bridge action.'))); }
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
        outreach: group('outreach', ['selections', 'selection', 'add', 'bulk', 'update', 'cancel', 'batches', 'batch', 'freeze']),
        openExternal: (url: string) => invoke('openExternal', url),
      } });
    });

    await page.goto(rendererOrigin, { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/FindMeGamer/);
    await expect(page.getByText('Workspace connected', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
    await expect(page.locator('[data-testid="vite-error-overlay"], vite-error-overlay')).toHaveCount(0);

    await page.getByRole('button', { name: 'Match', exact: true }).click();
    await expect(page.getByRole('list', { name: 'Activities' })).toBeVisible();
    for (let offset = 0; offset < activityPageOffset; offset += 50) {
      const next = page.getByRole('button', { name: 'Next page' });
      await expect(next).toBeEnabled(); await next.click();
    }
    await page.getByRole('button', { name: `Open ${activity.name}` }).click();
    await expect(page.getByRole('heading', { name: activity.name, level: 1 })).toBeVisible();
    if (HISTORY_ONLY) {
      const exactHistoryBatchId = historyBatchIds[0];
      const history = page.getByText('Preparation history', { exact: true });
      await history.focus(); await page.keyboard.press('Enter');
      await expect.poll(() => latestBatchPage?.items.some(item => item.id === exactHistoryBatchId) ?? false).toBe(true);
      const historyIndex = latestBatchPage!.items.findIndex(item => item.id === exactHistoryBatchId);
      expect(historyIndex).toBeGreaterThanOrEqual(0);
      await page.locator('.outreach-history li').nth(historyIndex).getByRole('button').click();
      await expect(page.getByText('History · read only', { exact: true })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Original snapshot', level: 3 })).toBeVisible();
      const viewPrimary = page.getByRole('button', { name: `View ${activeName}`, exact: true });
      await viewPrimary.focus(); await page.keyboard.press('Enter');
      await expect(page.getByRole('region', { name: 'Original preparation snapshot' }).first()).toBeVisible();
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.getByText('Unsaved Match changes', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('region', { name: 'Preparation editor' })).toHaveCount(0);
      await expect(page.getByRole('button', { name: /^Edit / })).toHaveCount(0);
      await expect(page.getByRole('button', { name: /^Save/ })).toHaveCount(0);
      expect(lastBatchReadId).toBe(exactHistoryBatchId);
      expect(count('outreach.batch')).toBe(1);
      for (const [label, width, height, largeFont] of [
        ['wide', 1320, 920, false], ['narrow', 760, 720, false], ['large-font', 1320, 920, true],
      ] as const) {
        await page.setViewportSize({ width, height });
        await page.evaluate(enlarged => {
          document.documentElement.style.fontSize = enlarged ? '135%' : '';
          document.querySelectorAll<HTMLElement>('*').forEach(element => {
            if (element.scrollTop) element.scrollTop = 0;
          });
          window.scrollTo(0, 0);
        }, largeFont);
        if (largeFont) expect(await page.evaluate(() => Number.parseFloat(getComputedStyle(document.documentElement).fontSize))).toBeCloseTo(21.6, 1);
        await assertNoHorizontalOverflow(`history ${label}`);
        await page.screenshot({ path: testInfo.outputPath(`outreach-history-${label}.png`), fullPage: true });
      }
      expect(JSON.stringify((await match.activity(activityId)).source_snapshot)).toBe(exactSourceSnapshot);
      expect(records.every(item => item.method === 'GET')).toBe(true);
      expect(unexpectedRequests).toEqual([]);
      expect(unexpectedBridgeCalls).toEqual([]);
      expect(count('settings.connection') + count('settings.reanalysis') + count('settings.smtp')).toBe(0);
      expect(sensitiveBrowserMessage).toBe(false);
      expect(pageErrors).toBe(0);
      expect(consoleProblems).toBe(0);
      return;
    }
    const searchHistory = page.getByLabel('Search history');
    await searchHistory.selectOption(`plan:${targetPlan.id}`);
    await expect(searchHistory).toHaveValue(`plan:${targetPlan.id}`);
    const candidateRegion = page.getByRole('region', { name: 'Candidate results' });
    const outreachChoice = candidateRegion.getByRole('checkbox', { name: `Select ${unselectedName} for outreach` });
    await expect(outreachChoice).not.toBeChecked();
    await outreachChoice.focus(); await page.keyboard.press('Space');
    await expect(outreachChoice).toBeChecked();
    await expect(page.getByRole('button', { name: 'Selected · 2' })).toBeVisible();
    expect(addedPreparation).not.toBeNull();
    expect(addedPreparation!.selected_contact).toBeNull();

    const selectedButton = page.getByRole('button', { name: 'Selected · 2' });
    await selectedButton.focus(); await page.keyboard.press('Enter');
    const selectedWorkspace = page.getByRole('region', { name: 'Selected people' });
    await expect(selectedWorkspace.getByRole('heading', { name: 'Selected · 2' })).toBeVisible();
    await expect(selectedWorkspace.getByRole('button', { name: 'Prepare 2' })).toBeEnabled();
    await selectedWorkspace.getByRole('button', { name: `Edit ${preparationName(addedPreparation!)}` }).click();
    const nullEditor = selectedWorkspace.getByRole('region', { name: 'Preparation editor' });
    await expect(nullEditor.getByRole('radio', { name: 'None' })).toBeChecked();
    await selectedWorkspace.getByRole('button', { name: 'Close details' }).click();

    await selectedWorkspace.getByRole('button', { name: 'Prepare 2' }).click();
    const preparationWorkspace = page.getByRole('region', { name: 'Outreach preparation' });
    await expect(preparationWorkspace.getByRole('heading', { name: 'Preparation · 2' })).toBeVisible();
    await expect(preparationWorkspace.getByText('Not ready to send', { exact: true })).toBeVisible();
    expect(frozenBatchId).not.toBe('');

    await preparationWorkspace.getByRole('button', { name: `Edit ${activeName}` }).click();
    const editor = preparationWorkspace.getByRole('region', { name: 'Preparation editor' });
    const confirmation = editor.getByRole('checkbox', { name: `Confirm “${initialActive!.public_name}” as public name` });
    await expect(confirmation).not.toBeChecked();
    const currentContact = initialActive!.contact_options.find(item => item.id === initialActive!.selected_contact?.id && item.status === 'eligible');
    expect(initialActive!.contact_status).toBe('changed');
    expect(currentContact?.id).toBe(PINNED_SELECTED_CONTACT_ID);
    const savedVersion = editor.locator('.preparation-choice.observed input[type="radio"]');
    const currentVersion = editor.locator(`input[type="radio"][value="current:${PINNED_SELECTED_CONTACT_ID}"]`);
    await expect(savedVersion).toBeChecked();
    await expect(currentVersion).not.toBeChecked();
    await currentVersion.focus(); await page.keyboard.press('Space');
    await expect(currentVersion).toBeChecked();
    await expect(currentVersion.locator('xpath=ancestor::label')).toContainText(currentContact!.purpose ?? 'No purpose');
    await confirmation.focus(); await page.keyboard.press('Space');
    await expect(confirmation).toBeChecked();
    await editor.getByRole('button', { name: 'View creator' }).click();
    await expect(page.getByRole('heading', { name: activeName, level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Back to activity' }).click();
    await expect(confirmation).toBeChecked();
    await editor.getByRole('button', { name: 'Save changes' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Changes saved' })).toBeVisible();

    const originalDisclosure = preparationWorkspace.getByText('Original snapshot', { exact: true });
    await originalDisclosure.click();
    const frozenSnapshot = preparationWorkspace.getByRole('region', { name: 'Original preparation snapshot' });
    await frozenSnapshot.getByText('Recorded preparation details').click();
    await expect(frozenSnapshot.getByText('Not confirmed', { exact: true })).toBeVisible();
    if (initialActive!.selected_contact) {
      await expect(frozenSnapshot.getByText(initialActive!.selected_contact.source_url ?? 'Not recorded', { exact: true })).toBeVisible();
    } else {
      await expect(frozenSnapshot.getByText('No email selected', { exact: true }).first()).toBeVisible();
    }

    await assertNoHorizontalOverflow('wide 1320');
    await page.screenshot({ path: testInfo.outputPath('outreach-renderer-wide.png'), fullPage: true });
    await page.setViewportSize({ width: 760, height: 720 });
    await assertNoHorizontalOverflow('narrow 760');
    await page.screenshot({ path: testInfo.outputPath('outreach-renderer-narrow.png'), fullPage: true });
    await page.setViewportSize({ width: 1320, height: 920 });
    await page.evaluate(() => { document.documentElement.style.fontSize = '135%'; });
    expect(await page.evaluate(() => Number.parseFloat(getComputedStyle(document.documentElement).fontSize))).toBeCloseTo(21.6, 1);
    await assertNoHorizontalOverflow('large font 135%');
    await page.screenshot({ path: testInfo.outputPath('outreach-renderer-large-font.png'), fullPage: true });

    await preparationWorkspace.getByRole('button', { name: 'Back to candidates' }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByLabel('Candidate filters and order')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Continue discovery' })).toBeVisible();
    const postsBeforeHistory = records.filter(item => item.method === 'POST').length;
    const history = page.getByText('Preparation history', { exact: true });
    await history.focus(); await page.keyboard.press('Enter');
    await expect.poll(() => latestBatchPage?.items.some(item => item.id === frozenBatchId) ?? false).toBe(true);
    const frozenHistoryIndex = latestBatchPage!.items.findIndex(item => item.id === frozenBatchId);
    expect(frozenHistoryIndex).toBeGreaterThanOrEqual(0);
    const frozenHistory = page.locator('.outreach-history li').nth(frozenHistoryIndex).getByRole('button');
    await expect(frozenHistory).toBeVisible(); await frozenHistory.click();
    await expect(page.getByText('History · read only', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Original snapshot', level: 3 })).toBeVisible();
    await page.getByRole('button', { name: `View ${activeName}` }).click();
    await expect(page.getByRole('region', { name: 'Original preparation snapshot' }).first()).toBeVisible();
    expect(lastBatchReadId).toBe(frozenBatchId);
    expect(records.filter(item => item.method === 'POST')).toHaveLength(postsBeforeHistory);

    const writes = records.filter(item => item.method === 'POST');
    expect(writes.map(item => item.path)).toEqual([
      `${activityBase}/selections`, `/api/v2/discovery/queries/${targetQueryId}/stop`,
      `${activityBase}/recipient-batches`, `${activityBase}/selections/${PINNED_ACTIVE_SELECTION_ID}/update`,
    ]);
    expect(count('outreach.add')).toBe(1);
    expect(count('outreach.update')).toBe(1);
    expect(count('outreach.freeze')).toBe(1);
    expect(count('outreach.bulk')).toBe(0);
    expect(count('outreach.cancel')).toBe(0);
    expect(count('match.stop')).toBe(1);
    expect(count('match.createActivity') + count('match.createPlan') + count('match.continueDiscovery') + count('match.evaluate')).toBe(0);
    expect(count('outreach.selections')).toBeGreaterThan(0);
    expect(count('outreach.batches')).toBeGreaterThan(0);
    expect(count('outreach.batch')).toBeGreaterThan(0);
    expect(count('settings.collection')).toBeGreaterThan(0);
    expect(count('settings.connection') + count('settings.reanalysis') + count('settings.smtp')).toBe(0);
    expect(PINNED_BATCH_IDS.has(frozenBatchId)).toBe(false);
    expect(JSON.stringify((await match.activity(activityId)).source_snapshot)).toBe(exactSourceSnapshot);
    expect(unexpectedRequests).toEqual([]);
    expect(unexpectedBridgeCalls).toEqual([]);
    expect(blockedBrowserRequests, 'Remote artwork/CDN requests must be intercepted by Chromium.').toBeGreaterThan(0);
    expect(sensitiveBrowserMessage).toBe(false);
    expect(pageErrors).toBe(0);
    expect(consoleProblems).toBe(0);
  } finally {
    try {
      const requestCounts = new Map<string, { method: string; path: string; count: number }>();
      for (const item of records) {
        const key = `${item.method} ${item.path}`;
        const previous = requestCounts.get(key);
        requestCounts.set(key, { method: item.method, path: item.path, count: (previous?.count ?? 0) + 1 });
      }
      const ledgerPath = testInfo.outputPath('sanitized-outreach-ledger.json');
      await writeFile(ledgerPath, JSON.stringify({ requests: [...requestCounts.values()],
        bridgeCalls: Object.fromEntries([...bridgeCalls.entries()].sort(([left], [right]) => left.localeCompare(right))),
        unexpectedRequestCount: unexpectedRequests.length, unexpectedBridgeCallCount: unexpectedBridgeCalls.length,
        blockedBrowserRequests, pageErrors, consoleProblems, sensitiveBrowserMessage }));
      await testInfo.attach('sanitized-outreach-ledger', {
        path: ledgerPath,
        contentType: 'application/json',
      });
    } catch { /* Diagnostic export must never prevent browser/server cleanup. */ }
    try { if (managedContext) await managedContext.close(); }
    finally { if (rendererServer) await closeServer(rendererServer); }
  }
});
