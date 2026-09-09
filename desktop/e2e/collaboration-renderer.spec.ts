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
const PRIVATE = '/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-xmmhoufp/private';
const ORIGIN = 'http://127.0.0.1:64692', PIN = '5706ad76f924991b80ee2a7fb6806528366be5ce';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const safe = (value: unknown, code: string) => { if (!value) throw new Error(code); };
const sha = (value: Buffer | string) => createHash('sha256').update(value).digest('hex');
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);
async function treeHash(directory: string) {
  const hash = createHash('sha256');
  async function walk(dir: string) { for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) { const full = path.join(dir, entry.name); if (entry.isDirectory()) await walk(full); else if (entry.isFile()) { hash.update(path.relative(directory, full)); hash.update(await readFile(full)); } } }
  await walk(directory); return hash.digest('hex');
}

test('C built renderer saves only explicit notes and retains unsaved collaboration context', async ({ browser }, testInfo) => {
  const globalReadOnly = process.env.FMG_GLOBAL_OUTREACH === '64692';
  test.skip(!globalReadOnly && (process.env.FMG_C_RENDERER_FROZEN !== '64692' || process.env.FMG_C_RENDERER_UPDATE !== 'approved'), 'Requires exclusive fixture lease and an explicit verification mode.');
  test.setTimeout(120_000);
  const run = randomUUID(), ledger = `${PRIVATE}/c-renderer-${run}.json`, marker = `Synthetic C renderer notes verification ${run}`;
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
    const apiPath = path.resolve(process.env.FMG_C_API_LEDGER ?? '');
    safe(path.dirname(apiPath) === PRIVATE && /^c-collaboration-[a-f0-9-]+\.json$/.test(path.basename(apiPath)), 'api_ledger_path');
    const apiStat = await lstat(apiPath); safe(apiStat.isFile() && !apiStat.isSymbolicLink() && (apiStat.mode & 0o777) === 0o600, 'api_ledger_permissions');
    const apiLedger = JSON.parse(await readFile(apiPath, 'utf8')), ids = apiLedger.renderer_fixture;
    safe(apiLedger.status === 'passed' && apiLedger.backend_revision === PIN && ids && uuid(ids.activity_id) && uuid(ids.selection_id) && uuid(ids.creator_id), 'api_fixture_ready');
    const ACTIVITY: string = ids.activity_id, SELECTION: string = ids.selection_id, CREATOR: string = ids.creator_id;
    sourceHash = await treeHash(ROOT + '/src'); bundleHash = await treeHash(ROOT + '/out/renderer'); baselineEffects = await effects();
    Object.assign(report, { source_hash: sourceHash, bundle_hash: bundleHash, api_ledger: apiPath, fixture: { activity_id: ACTIVITY, selection_id: SELECTION, creator_id: CREATOR }, backend_revision: PIN });
    let expectedRevision = -1;
    const fetcher: Fetcher = async (url, init) => {
      const u = new URL(url), method = init.method ?? 'GET';
      const get = method === 'GET' && /^\/api\/(v1\/(session$|settings\/|outreach\/smtp$)|v2\/(library\/(games|creators)|activities|discovery|saved-sets|outreach\/))/.test(u.pathname);
      const update = !globalReadOnly && method === 'POST' && u.pathname === `/api/v2/activities/${ACTIVITY}/invitations/${SELECTION}/update` && posts === 0;
      if (u.origin !== ORIGIN || !(get || update)) { forbiddenHTTP++; throw new Error('http_scope'); }
      if (update) { const body = JSON.parse(String(init.body)); safe(Object.keys(body).sort().join(',') === 'expected_revision,notes' && body.expected_revision === expectedRevision && body.notes === marker, 'exact_notes_body'); posts++; }
      const family = `${method} ${u.pathname.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi, ':id')}`; http[family] = (http[family] ?? 0) + 1;
      return fetch(u, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
    };
    const connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
    const match = new MatchClient(r => authenticatedMatchRequest(fetcher, connection, r)), outreach = new OutreachClient(r => authenticatedOutreachRequest(fetcher, connection, r));
    const drafts = new DraftsClient(r => authenticatedDraftsRequest(fetcher, connection, r)), sending = new SendingClient(r => authenticatedSendingRequest(fetcher, connection, r));
    const collaboration = new CollaborationClient(r => authenticatedCollaborationRequest(fetcher, connection, r));
    const games = new GameClient(r => authenticatedGameRequest(fetcher, connection, r)), library = new LibraryClient((r, q) => authenticatedGet(fetcher, connection, r, q));
    const creators = new CreatorClient(r => authenticatedCreatorRequest(fetcher, connection, r)), savedSets = new SavedSetClient(r => authenticatedSavedSetRequest(fetcher, connection, r)), settings = new SettingsClient(r => authenticatedSettingsRequest(fetcher, connection, r));
    const scope = { activityId: ACTIVITY, selectionId: SELECTION }, activity = await match.activity(ACTIVITY), original = await collaboration.detail(scope);
    safe(activity.name.startsWith('C desktop ') && original.creator_id === CREATOR && original.invitation_state === 'accepted', 'own_api_fixture'); expectedRevision = original.revision;
    const scoped = (v: any) => { safe(v.activityId === ACTIVITY, 'activity_scope'); return v; };
    const actions: Record<string, (input?: any) => Promise<unknown>> = {
      'connection.status': async () => ({ serviceUrl: ORIGIN, hasKey: true, storageAvailable: true }), 'connection.test': async () => { await library.session(); return { authenticated: true, proxy: 'system', route: 'direct' }; },
      'preferences.read': async () => ({ appearance: 'system', fontSize: 'default', automaticUpdates: false }), 'updates.status': async () => ({ phase: 'development', installedVersion: '0.2.0-alpha.1', lastCheckedAt: null, lastAttemptAt: null, release: null, error: null }),
      'library.list': v => library.list(v), 'library.detail': v => library.detail(v), 'games.list': v => games.list(v), 'games.detail': v => games.detail(v), 'creators.list': v => creators.list(v),
      'creators.detail': v => { safe(v === CREATOR, 'creator_scope'); return creators.detail(v); }, 'creators.works': v => { safe(v.creatorId === CREATOR, 'creator_scope'); return creators.works(v); },
      'settings.collection': () => settings.collection(), 'settings.smtp': () => settings.smtp(), 'match.activities': v => match.activities(v), 'match.activity': v => { safe(v === ACTIVITY, 'activity_scope'); return match.activity(v); },
      'match.plans': v => match.plans(scoped(v)), 'match.plan': v => match.plan(v), 'match.query': v => match.query(v), 'match.candidates': v => match.candidates(v), 'match.evaluations': v => match.evaluations(v), 'savedSets.list': v => savedSets.list(v),
      'outreach.selections': v => outreach.selections(scoped(v)), 'outreach.batches': v => outreach.batches(scoped(v)), 'drafts.compositions': v => drafts.compositions(scoped(v)), 'sending.batches': v => sending.batches(scoped(v)),
      'collaboration.list': v => collaboration.list(scoped(v)), 'collaboration.detail': v => { scoped(v); safe(v.selectionId === SELECTION, 'selection_scope'); return collaboration.detail(v); },
      'collaboration.creatorHistory': v => { safe(v.creatorId === CREATOR, 'creator_scope'); return collaboration.creatorHistory(v); },
      'collaboration.update': v => { scoped(v); safe(v.selectionId === SELECTION, 'selection_scope'); return collaboration.update(v); },
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
    await checkpoint('open_activity'); await page.goto(origin); await expect(page.getByText('Workspace connected', { exact: true })).toBeVisible(); await page.getByRole('button', { name: globalReadOnly ? 'Outreach' : 'Match', exact: true }).click();
    let located = false; for (let n = 0; n < 10; n++) { const button = page.getByRole('button', { name: `Open ${activity.name}`, exact: true }); await expect(page.getByRole('button', { name: /^Open / }).first()).toBeVisible(); if (await button.count()) { await button.click(); located = true; break; } await page.getByRole('button', { name: 'Next page', exact: true }).click(); } safe(located, 'activity_found');
    await page.getByRole('tab', { name: 'Invitations', exact: true }).click();
    const workspace = page.getByRole('region', { name: 'Invitations', exact: true }), editor = workspace.getByRole('region', { name: 'Invitation relationship', exact: true });
    await expect(editor).toBeVisible(); await checkpoint('response_filter'); const responseFilter = workspace.locator('.collaboration-filters').getByRole('combobox', { name:'Response', exact: true }); await responseFilter.selectOption('accepted'); await expect(editor).toBeVisible();
    if(globalReadOnly){
      await checkpoint('global_outreach_read_only');
      await editor.getByRole('button',{name:'Open creator',exact:true}).click();
      await expect(page.getByRole('button',{name:'All activities',exact:true})).toBeVisible();
      await expect(page.locator('.creator-invitation-history').getByRole('button').filter({hasText:activity.name})).toBeVisible();
      await page.getByRole('button',{name:'Back to activity',exact:true}).click();
      await expect(responseFilter).toHaveValue('accepted');
      const reads=bridge['match.activity'];
      await page.getByRole('button',{name:'Continue in Match',exact:true}).click();
      await expect(page.getByRole('tab',{name:'Find & prepare',exact:true})).toHaveAttribute('aria-selected','true');
      await expect(page.getByRole('button',{name:'Adjust conditions',exact:true})).toBeVisible();
      const resultsShot=testInfo.outputPath('P4-results-wide.png');await page.screenshot({path:resultsShot});(report.screenshots as string[]).push(resultsShot);
      await page.getByRole('button',{name:'Adjust conditions',exact:true}).click();
      await expect(page.getByRole('form',{name:'Discovery conditions'})).toBeVisible();
      const conditionsShot=testInfo.outputPath('P3-conditions-wide.png');await page.screenshot({path:conditionsShot});(report.screenshots as string[]).push(conditionsShot);
      await page.getByRole('form',{name:'Discovery conditions'}).getByRole('button',{name:'Cancel',exact:true}).click();
      await page.getByRole('button',{name:'Outreach',exact:true}).click();
      await expect(responseFilter).toHaveValue('accepted');
      await expect(editor.getByRole('button',{name:'Open creator',exact:true})).toBeEnabled();
      safe(bridge['match.activity']===reads,'shared_activity_retained');
      await page.setViewportSize({width:760,height:920});
      await page.evaluate(()=>{document.documentElement.style.fontSize='135%';});
      safe(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'outreach_narrow_layout');
      const shot=testInfo.outputPath('global-outreach-narrow.png');await page.screenshot({path:shot});(report.screenshots as string[]).push(shot);
      safe(JSON.stringify(await collaboration.detail(scope))===JSON.stringify(original)&&posts===0,'global_outreach_zero_writes');
      safe(pageErrors===0&&forbiddenHTTP===0&&unexpectedBridge===0,'global_outreach_runtime');
      report.status='passed';await checkpoint('global_outreach_complete');
    }else{
    await checkpoint('explicit_notes_update'); await editor.getByRole('button', { name: 'Edit progress', exact: true }).click(); await editor.getByRole('textbox', { name:'Notes', exact: true }).fill(marker); await editor.getByRole('button', { name: 'Save progress', exact: true }).click(); await expect(editor.getByRole('button', { name: 'Edit progress', exact: true })).toBeVisible();
    const saved = await collaboration.detail(scope); safe(saved.revision === original.revision + 1 && saved.notes === marker && JSON.stringify(saved.responses) === JSON.stringify(original.responses) && saved.cooperation_state === original.cooperation_state && saved.follow_up_state === original.follow_up_state && saved.sending_state === original.sending_state && posts === 1, 'one_real_ui_notes_write');
    report.saved_revision = saved.revision; report.notes_hash = sha(marker);
    await checkpoint('retained_tab_and_creator_detour'); await editor.getByRole('button', { name: 'Edit progress', exact: true }).click(); const notes = editor.getByRole('textbox', { name:'Notes', exact: true }), unsaved = 'Synthetic local-only notes retained through Creator detour; never submitted.'; await notes.fill(unsaved);
    await page.getByRole('tab', { name: 'Find & prepare', exact: true }).click(); await page.getByRole('tab', { name: 'Invitations', exact: true }).click(); await expect(notes).toHaveValue(unsaved); await expect(responseFilter).toHaveValue('accepted');
    await editor.getByRole('button', { name: 'Open creator', exact: true }).click(); await expect(page.getByRole('button', { name: 'Back to activity', exact: true })).toBeVisible(); await page.getByText('Invitation history', { exact: true }).click(); await expect(page.locator('.creator-invitation-history').getByRole('button').filter({ hasText: activity.name })).toBeVisible();
    const activePage=page;
    await page.getByRole('button', { name: 'Back to activity', exact: true }).click(); await expect(notes).toHaveValue(unsaved); await expect(responseFilter).toHaveValue('accepted');await expect.poll(()=>activePage.evaluate(()=>document.activeElement?.textContent)).toMatch(/^(Open creator|Invitations)$/);await expect(notes).toBeEnabled();
    await checkpoint('narrow_keyboard'); await page.setViewportSize({ width: 760, height: 920 }); await page.evaluate(() => { document.documentElement.style.fontSize = '135%'; }); await notes.focus(); await expect(notes).toBeFocused(); await page.keyboard.press('Tab');
    safe(await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement !== document.body), 'keyboard_focus');
    const layout = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth, reduced: matchMedia('(prefers-reduced-motion: reduce)').matches })); safe(layout.width <= layout.viewport + 1 && layout.reduced, 'narrow_reduced_no_overflow');
    const narrow = testInfo.outputPath('collaboration-narrow-135.png'); await page.screenshot({ path: narrow }); (report.screenshots as string[]).push(narrow);
    await editor.getByRole('button', { name: 'Cancel', exact: true }).click(); await editor.getByRole('button', { name: 'Edit progress', exact: true }).click(); await expect(notes).toHaveValue(marker); await editor.getByRole('button', { name: 'Cancel', exact: true }).click();
    await checkpoint('response_gate_no_write'); await editor.getByRole('button', { name: 'Record response', exact: true }).click(); await expect(editor.getByRole('combobox', { name:'Response', exact: true })).toHaveValue(''); await expect(editor.getByRole('textbox', { name:'Source note', exact: true })).toBeVisible(); await expect(editor.getByLabel(/Responded at/)).toHaveValue(''); await expect(editor.getByRole('button', { name: 'Save response', exact: true })).toBeDisabled();
    const responseShot = testInfo.outputPath('collaboration-response-gate.png'); await page.screenshot({ path: responseShot }); (report.screenshots as string[]).push(responseShot); await editor.getByRole('button', { name: 'Cancel', exact: true }).click();
    safe(JSON.stringify(await collaboration.detail(scope)) === JSON.stringify(saved) && posts === 1 && !bridge['collaboration.respond'], 'cancel_detour_response_no_extra_write');
    safe(pageErrors === 0 && consoleProblems === 0 && forbiddenHTTP === 0 && unexpectedBridge === 0 && blockedBrowser === 0, 'runtime_errors'); report.status = 'passed'; await checkpoint('complete');
    }
  } catch (error) {
    report.status = 'failed'; report.error = error instanceof Error && /^[a-z0-9_]+$/.test(error.message) ? error.message : 'ui_assertion_failed';
    if(error instanceof Error)report.locator_failure=error.message.match(/waiting for ([^\n]+)/)?.[1]??null;
    await checkpoint(String(report.stage));
    try { if (page) { const failed = testInfo.outputPath('collaboration-failure.png'); await page.screenshot({ path: failed }); (report.screenshots as string[]).push(failed); } } catch { report.failure_screenshot = 'unavailable'; }
  } finally {
    try { await context?.close(); if (server) await new Promise<void>(resolve => server!.close(() => resolve())); } catch { report.status = 'failed'; report.cleanup_error = 'close_failed'; }
    try {
      if (baselineEffects) { report.fixture_effects_unchanged = JSON.stringify(await effects()) === JSON.stringify(baselineEffects); if (!report.fixture_effects_unchanged) { report.status = 'failed'; report.error = 'fixture_effects_changed'; } }
      if (sourceHash && bundleHash) { report.source_hash_after = await treeHash(ROOT + '/src'); report.bundle_hash_after = await treeHash(ROOT + '/out/renderer'); if (sourceHash !== report.source_hash_after || bundleHash !== report.bundle_hash_after) { report.status = 'failed'; report.error = 'source_freeze_changed'; } }
    } catch { report.status = 'failed'; report.final_check_error = 'physical_evidence_unavailable'; }
    report.http_counts = http; report.bridge_counts = bridge; report.get_requests = Object.entries(http).filter(([key]) => key.startsWith('GET ')).reduce((sum, [, value]) => sum + value, 0); report.post_requests = posts; report.errors = { pageErrors, consoleProblems, forbiddenHTTP, unexpectedBridge, blockedBrowser };
    await writeFile(ledger, JSON.stringify(report, null, 2), { mode: 0o600 }); console.log(JSON.stringify({ status: report.status, stage: report.stage, ledger }));
  }
  safe(report.status === 'passed', `c_renderer_failed_${String(report.stage)}`);
});
