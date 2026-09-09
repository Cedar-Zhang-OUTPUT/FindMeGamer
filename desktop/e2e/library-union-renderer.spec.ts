import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { readFile, writeFile, readdir, lstat } from 'node:fs/promises';
import { createServer, type Server } from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest } from '../src/main/match-transport';
import { OutreachClient } from '../src/main/outreach-client';
import { authenticatedOutreachRequest } from '../src/main/outreach-transport';
import { DraftsClient } from '../src/main/drafts-client';
import { authenticatedDraftsRequest } from '../src/main/drafts-transport';
import { SendingClient } from '../src/main/sending-client';
import { authenticatedSendingRequest } from '../src/main/sending-transport';
import { CollaborationClient } from '../src/main/collaboration-client';
import { authenticatedCollaborationRequest } from '../src/main/collaboration-transport';
import { GameClient } from '../src/main/game-client';
import { LibraryClient } from '../src/main/library-client';
import { SavedSetClient } from '../src/main/saved-set-client';
import { authenticatedSavedSetRequest } from '../src/main/saved-set-transport';
import { SettingsClient } from '../src/main/settings-client';
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';
import { authenticatedGet, authenticatedGameRequest, publicResult, type Fetcher } from '../src/main/transport';

// Author-only until source/build freeze + API ledger + exclusive lease. This is
// the built production App with a restricted Node bridge, not native Electron.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
const PRIVATE = '/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-rgunwn5k/private';
const ORIGIN = 'http://127.0.0.1:56257', PIN = '28595d84805137dabbdadd31f26f9fa5b51d988b';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const safe = (value: unknown, code: string) => { if (!value) throw new Error(code); };
const sha = (value: Buffer | string) => createHash('sha256').update(value).digest('hex');
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);
async function treeHash(directory: string) {
  const hash = createHash('sha256');
  async function walk(dir: string) { for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) { const full = path.join(dir, entry.name); if (entry.isDirectory()) await walk(full); else if (entry.isFile()) { hash.update(path.relative(directory, full)); hash.update(await readFile(full)); } } }
  await walk(directory); return hash.digest('hex');
}

test('Library union built renderer preserves four-platform and Creator context without writes', async ({ browser }, testInfo) => {
  test.skip(process.env.FMG_LIBRARY_UNION !== '56257', 'Requires exclusive Library-union fixture lease.');
  test.setTimeout(120_000);
  const run = randomUUID(), ledger = `${PRIVATE}/union-renderer-${run}.json`;
  const report: Record<string, unknown> = { status: 'running', stage: 'bootstrap', evidence: 'headless-built-renderer', screenshots: [] };
  const http: Record<string, number> = {}, bridge: Record<string, number> = {};
  let pageErrors = 0, consoleProblems = 0, forbiddenHTTP = 0, unexpectedBridge = 0, blockedBrowser = 0, posts = 0;
  let context: BrowserContext | undefined, page: Page | undefined, server: Server | undefined;
  let sourceHash: string | undefined, bundleHash: string | undefined, baselineEffects: Record<string, string> | undefined;
  async function checkpoint(stage: string) { report.stage = stage; await writeFile(ledger, JSON.stringify({ ...report, http_counts: http, bridge_counts: bridge }, null, 2), { mode: 0o600 }); }
  async function effects() {
    const result: Record<string, string> = {};
    for (const name of (await readdir(PRIVATE + '/state')).filter(name => /(?:control\.json|events\.jsonl|\.eml)$/.test(name)).sort()) { const full = PRIVATE + '/state/' + name, stat = await lstat(full); safe(stat.isFile() && !stat.isSymbolicLink(), 'state_file'); result[name] = sha(await readFile(full)); }
    return result;
  }
  try {
    const clientStat = await lstat(PRIVATE + '/client.json'); safe(clientStat.isFile() && !clientStat.isSymbolicLink() && (clientStat.mode & 0o777) === 0o600, 'private_permissions');
    const fixture = JSON.parse(await readFile(PRIVATE + '/client.json', 'utf8'));
    safe(fixture.base_url === ORIGIN && fixture.backend_revision === PIN && fixture.migration === '20260908_0019', 'fixture_pin');
    const apiPath = PRIVATE + '/union-report.json';
    const ids = JSON.parse(await readFile(apiPath, 'utf8'));
    safe(ids.backend_revision === PIN && uuid(ids.activity_id) && uuid(ids.query_id) && uuid(ids.plan_id), 'api_fixture_ready');
    const ACTIVITY: string = ids.activity_id;
    let CREATOR = '';
    sourceHash = await treeHash(ROOT + '/src'); bundleHash = await treeHash(ROOT + '/out/renderer'); baselineEffects = await effects();
    Object.assign(report, { source_hash: sourceHash, bundle_hash: bundleHash, api_ledger: apiPath, fixture: { activity_id: ACTIVITY }, backend_revision: PIN });
    const fetcher: Fetcher = async (url, init) => {
      const u = new URL(url), method = init.method ?? 'GET';
      const get = method === 'GET' && /^\/api\/(v1\/(session$|settings\/|outreach\/smtp$)|v2\/(library\/(games|creators)|activities|discovery|saved-sets|outreach\/))/.test(u.pathname);
      if (u.origin !== ORIGIN || !get) { forbiddenHTTP++; throw new Error('http_scope'); }
      const family = `${method} ${u.pathname.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi, ':id')}`; http[family] = (http[family] ?? 0) + 1;
      return fetch(u, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
    };
    const connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
    const match = new MatchClient(r => authenticatedMatchRequest(fetcher, connection, r)), outreach = new OutreachClient(r => authenticatedOutreachRequest(fetcher, connection, r));
    const drafts = new DraftsClient(r => authenticatedDraftsRequest(fetcher, connection, r)), sending = new SendingClient(r => authenticatedSendingRequest(fetcher, connection, r));
    const collaboration = new CollaborationClient(r => authenticatedCollaborationRequest(fetcher, connection, r));
    const games = new GameClient(r => authenticatedGameRequest(fetcher, connection, r)), library = new LibraryClient((r, q) => authenticatedGet(fetcher, connection, r, q));
    const creators = new CreatorClient(r => authenticatedCreatorRequest(fetcher, connection, r)), savedSets = new SavedSetClient(r => authenticatedSavedSetRequest(fetcher, connection, r)), settings = new SettingsClient(r => authenticatedSettingsRequest(fetcher, connection, r));
    const activity = await match.activity(ACTIVITY), candidates = await match.candidates({queryId:ids.query_id,offset:0,limit:100});
    safe(candidates.items.length === 8, 'union_candidate_count');
    CREATOR = candidates.items[0].creator_id;
    safe(uuid(CREATOR), 'creator_identity'); report.fixture = {activity_id:ACTIVITY, creator_id:CREATOR, query_id:ids.query_id};
    const scoped = (v: any) => { safe(v.activityId === ACTIVITY, 'activity_scope'); return v; };
    const actions: Record<string, (input?: any) => Promise<unknown>> = {
      'connection.status': async () => ({ serviceUrl: ORIGIN, hasKey: true, storageAvailable: true }), 'connection.test': async () => { await library.session(); return { authenticated: true, proxy: 'system', route: 'direct' }; },
      'preferences.read': async () => ({ appearance: 'system', fontSize: 'default', automaticUpdates: false }), 'updates.status': async () => ({ phase: 'development', installedVersion: '0.2.0-alpha.1', lastCheckedAt: null, lastAttemptAt: null, release: null, error: null }),
      'library.list': v => library.list(v), 'library.detail': v => library.detail(v), 'games.list': v => games.list(v), 'games.detail': v => games.detail(v), 'creators.list': v => creators.list(v),
      'creators.detail': v => { safe(v === CREATOR, 'creator_scope'); return creators.detail(v); }, 'creators.works': v => { safe(v.creatorId === CREATOR, 'creator_scope'); return creators.works(v); },
      'settings.collection': () => settings.collection(), 'settings.smtp': () => settings.smtp(), 'match.activities': v => match.activities(v), 'match.activity': v => { safe(v === ACTIVITY, 'activity_scope'); return match.activity(v); },
      'match.plans': v => match.plans(scoped(v)), 'match.plan': v => match.plan(v), 'match.query': v => match.query(v), 'match.candidates': v => match.candidates(v), 'match.evaluations': v => match.evaluations(v), 'match.evaluation': v => match.evaluation(v), 'match.evaluationResults': v => match.evaluationResults(v), 'savedSets.list': v => savedSets.list(v),
      'outreach.selections': v => outreach.selections(scoped(v)), 'outreach.batches': v => outreach.batches(scoped(v)), 'drafts.compositions': v => drafts.compositions(scoped(v)), 'sending.batches': v => sending.batches(scoped(v)),
      'collaboration.list': v => collaboration.list(scoped(v)),
      'collaboration.creatorHistory': v => { safe(v.creatorId === CREATOR, 'creator_scope'); return collaboration.creatorHistory(v); },

    };
    server = createServer(async (req, res) => {
      const renderer = ROOT + '/out/renderer', relative = req.url === '/' ? 'index.html' : String(req.url).split('?')[0].replace(/^\/+/, ''), file = path.resolve(renderer, relative);
      if (req.method !== 'GET' || !file.startsWith(renderer + '/')) { res.writeHead(403).end(); return; }
      try { const mime: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }; res.writeHead(200, { 'Content-Type': mime[path.extname(file)] ?? 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(await readFile(file)); } catch { res.writeHead(404).end(); }
    });
    await new Promise<void>(resolve => server!.listen(0, '127.0.0.1', resolve)); const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    context = await browser.newContext({ viewport: { width: 1320, height: 920 }, reducedMotion: 'reduce' });
    context.setDefaultTimeout(12_000);context.setDefaultNavigationTimeout(15_000);
    await context.route('**/*', route => { const url = route.request().url(); if (url.startsWith(origin + '/') || url.startsWith('data:') || url.startsWith('about:')) return route.continue(); blockedBrowser++; return route.abort(); });
    page = await context.newPage(); page.on('pageerror', () => pageErrors++); page.on('console', message => { if (['error', 'warning'].includes(message.type())) consoleProblems++; });
    await page.exposeBinding('__fmgInvoke', async (_source, name: string, input: unknown) => { bridge[name] = (bridge[name] ?? 0) + 1; const action = actions[name]; if (!action) { unexpectedBridge++; return { ok: false, error: { code: 'fixture_scope', message: 'Action is outside this verification.', retryable: false } }; } return publicResult(() => action(input)); });
    await page.addInitScript(() => {
      const group = (name: string, methods: string[]) => Object.fromEntries(methods.map(method => [method, (input?: unknown) => (window as any).__fmgInvoke(`${name}.${method}`, input)]));
      Object.defineProperty(window, 'desktop', { configurable: false, value: {
        connection: group('connection', ['status', 'test', 'save', 'clear']), preferences: group('preferences', ['read', 'update', 'restoreAppearance']), updates: group('updates', ['status', 'check']), library: group('library', ['list', 'detail']), games: group('games', ['list', 'detail', 'create', 'update']),
        creators: group('creators', ['list', 'detail', 'create', 'update', 'rebind', 'works', 'createWork', 'updateWork', 'createContact', 'updateContact']), settings: group('settings', ['collection', 'connection', 'setCollection', 'replaceConnection', 'testConnection', 'reanalysis', 'saveReanalysis', 'smtp', 'saveSMTP', 'testSMTP', 'sendTestEmail']),
        match: group('match', ['activities', 'activity', 'createActivity', 'plans', 'plan', 'createPlan', 'retryPlan', 'query', 'candidates', 'stop', 'continueDiscovery', 'evaluations', 'evaluate', 'evaluation', 'evaluationResults', 'retryEvaluation']), savedSets: group('savedSets', ['list', 'detail', 'results', 'create']), outreach: group('outreach', ['selections', 'selection', 'add', 'bulk', 'update', 'cancel', 'batches', 'batch', 'freeze']),
        drafts: group('drafts', ['templates', 'template', 'registerCanonical', 'createTemplate', 'compositions', 'composition', 'createComposition', 'edit', 'refresh', 'retry', 'senderFacts']), sending: group('sending', ['qualify', 'send', 'batches', 'batch', 'retry', 'resolve']), collaboration: group('collaboration', ['list', 'detail', 'creatorHistory', 'update', 'respond']), openExternal: (v: string) => (window as any).__fmgInvoke('openExternal', v),
      } });
    });
    await checkpoint('open_activity'); await page.goto(origin);
    await expect(page.getByText('Workspace connected', {exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Match',exact:true}).click();
    await page.getByRole('button',{name:`Open ${activity.name}`,exact:true}).click();
    const history=page.getByRole('combobox',{name:'Search history',exact:true});
    await expect(history).toBeVisible(); await history.selectOption('plan:'+ids.plan_id);
    const results=page.getByRole('region',{name:'Candidate results',exact:true});
    await expect(results.getByRole('article')).toHaveCount(8);
    const sources=page.getByRole('region',{name:'Collection sources',exact:true});
    await expect(sources.getByText('Real-time data unavailable',{exact:true})).toHaveCount(2);
    await expect(sources.locator('.match-source-status')).toHaveCount(4);
    await expect(page.getByRole('button',{name:'Add campaign brief',exact:true})).toBeDisabled();
    const shot=async(name:string)=>{const file=testInfo.outputPath(name);await page!.screenshot({path:file});(report.screenshots as string[]).push(file);};
    await shot('union-results.png');await checkpoint('four_platform_conditions');
    await page.getByRole('button',{name:'Adjust conditions',exact:true}).click();
    const form=page.getByRole('form',{name:'Discovery conditions',exact:true});
    for(const name of ['YouTube','X','Twitch','Instagram'])await expect(form.getByRole('checkbox',{name,exact:true})).toBeEnabled();
    await shot('four-platform-conditions.png');await form.getByRole('button',{name:'Cancel',exact:true}).click();
    await checkpoint('evaluation');
    await page.getByRole('tab',{name:/^Match briefs/}).click();
    await expect(page.getByRole('region',{name:'Evaluation results',exact:true}).getByRole('article')).toHaveCount(8);
    await shot('union-evaluations.png');
    await page.getByRole('tab',{name:'Candidates',exact:true}).click();
    await checkpoint('creator');
    const first=results.getByRole('article').first();
    await first.getByRole('button',{name:'View creator',exact:true}).click();
    const tabs=page.getByRole('tablist',{name:'Creator record sections',exact:true});
    await expect(tabs.getByRole('tab',{name:'Profile',exact:true})).toHaveAttribute('aria-selected','true');
    await tabs.getByRole('tab',{name:'Invitations',exact:true}).click();
    await expect(page.getByRole('button',{name:'All activities',exact:true})).toBeVisible();
    await tabs.getByRole('tab',{name:'Profile',exact:true}).click();
    await shot('creator-profile.png');
    await page.getByRole('button',{name:'Back to activity',exact:true}).click();
    await expect(history).toHaveValue('plan:'+ids.plan_id);
    await expect(results.getByRole('article')).toHaveCount(8);
    await page.setViewportSize({width:760,height:920});
    safe(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'narrow_layout');
    await shot('union-narrow.png');
    safe(posts===0&&pageErrors===0&&forbiddenHTTP===0&&unexpectedBridge===0,'readonly_runtime');
    report.status='passed';await checkpoint('complete');
  } catch (error) {
    report.status = 'failed'; report.error = error instanceof Error && /^[a-z0-9_]+$/.test(error.message) ? error.message : 'ui_assertion_failed';
    if(error instanceof Error)report.locator_failure=error.message.match(/waiting for ([^\n]+)/)?.[1]??null;
    await checkpoint(String(report.stage));
    try { if (page) { const failed = testInfo.outputPath('union-failure.png'); await page.screenshot({ path: failed }); (report.screenshots as string[]).push(failed); } } catch { report.failure_screenshot = 'unavailable'; }
  } finally {
    try { await context?.close(); if (server) await new Promise<void>(resolve => server!.close(() => resolve())); } catch { report.status = 'failed'; report.cleanup_error = 'close_failed'; }
    try {
      if (baselineEffects) { report.fixture_effects_unchanged = JSON.stringify(await effects()) === JSON.stringify(baselineEffects); if (!report.fixture_effects_unchanged) { report.status = 'failed'; report.error = 'fixture_effects_changed'; } }
      if (sourceHash && bundleHash) { report.source_hash_after = await treeHash(ROOT + '/src'); report.bundle_hash_after = await treeHash(ROOT + '/out/renderer'); if (sourceHash !== report.source_hash_after || bundleHash !== report.bundle_hash_after) { report.status = 'failed'; report.error = 'source_freeze_changed'; } }
    } catch { report.status = 'failed'; report.final_check_error = 'physical_evidence_unavailable'; }
    report.http_counts = http; report.bridge_counts = bridge; report.get_requests = Object.entries(http).filter(([key]) => key.startsWith('GET ')).reduce((sum, [, value]) => sum + value, 0); report.post_requests = posts; report.errors = { pageErrors, consoleProblems, forbiddenHTTP, unexpectedBridge, blockedBrowser };
    await writeFile(ledger, JSON.stringify(report, null, 2), { mode: 0o600 }); console.log(JSON.stringify({ status: report.status, stage: report.stage, ledger }));
  }
  safe(report.status === 'passed', `union_renderer_failed_${String(report.stage)}`);
});
