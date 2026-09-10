import { test, expect, type BrowserContext } from '@playwright/test';
import { readFile, writeFile, readdir, stat } from 'node:fs/promises';
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
import { GameClient } from '../src/main/game-client';
import { LibraryClient } from '../src/main/library-client';
import { SavedSetClient } from '../src/main/saved-set-client';
import { authenticatedSavedSetRequest } from '../src/main/saved-set-transport';
import { SettingsClient } from '../src/main/settings-client';
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';
import { authenticatedGet, authenticatedGameRequest, publicResult, type Fetcher } from '../src/main/transport';

// Explicitly requested test-file harness. Headless built App evidence, not Electron.
// Root must first run the P7 API fixture, freeze src/build and grant the62611 lease.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
const PRIVATE = '/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-ixcaiiq1/private';
const ORIGIN = 'http://127.0.0.1:62611';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const safe = (condition: unknown, code: string): void => { if (!condition) throw new Error(code); };
const sha = (bytes: Buffer | string) => createHash('sha256').update(bytes).digest('hex');
async function treeHash(directory: string): Promise<string> {
  const hash = createHash('sha256');
  async function walk(dir: string) { for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) { const full = path.join(dir, entry.name); if (entry.isDirectory()) await walk(full); else if (entry.isFile()) { hash.update(path.relative(directory, full)); hash.update(await readFile(full)); } } }
  await walk(directory); return hash.digest('hex');
}
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);

test('P7 built renderer reads frozen deliveries and retains exclusion through SMTP detour without sending', async ({ browser }, testInfo) => {
  test.skip(process.env.FMG_P7_RENDERER_FROZEN !== '62611', 'Requires root source freeze, API fixture ledger and exclusive lease.');
  test.setTimeout(120_000);
  const ledgerPath = path.join(PRIVATE, `p7-renderer-${randomUUID()}.json`);
  const report: Record<string, unknown> = { status: 'running', stage: 'bootstrap', evidence: 'headless-built-renderer', mutation_requests: 0 };
  const http: Record<string, number> = {}, bridge: Record<string, number> = {};
  let pageErrors = 0, consoleProblems = 0, unexpectedBridge = 0, blockedBrowser = 0, forbiddenHTTP = 0;
  let context: BrowserContext | undefined, server: Server | undefined;
  let before: { controls: Buffer; model: Buffer; smtp: Buffer } | undefined;
  let sourceHash: string | undefined, bundleHash: string | undefined;
  try {
    safe(((await stat(PRIVATE + '/client.json')).mode & 0o777) === 0o600, 'fixture_permissions');
    const fixture = JSON.parse(await readFile(PRIVATE + '/client.json', 'utf8'));
    safe(fixture.base_url === ORIGIN && fixture.backend_revision === 'ece2e9d9558dfe057dc40ad58bd98a86e3149dd5' && fixture.migration === '20260908_0017', 'fixture_pin');
    // Input is an explicit private, sanitized API ledger; never discover arbitrary baselines.
    const apiLedgerPath = path.resolve(process.env.FMG_P7_API_LEDGER ?? '');
    safe(apiLedgerPath.startsWith(PRIVATE + '/') && ((await stat(apiLedgerPath)).mode & 0o777) === 0o600, 'api_ledger_permissions');
    const apiLedger = JSON.parse(await readFile(apiLedgerPath, 'utf8'));
    const ids = apiLedger.renderer_fixture;
    safe(apiLedger.status === 'passed' && ids && uuid(ids.activity_id) && uuid(ids.composition_id) && uuid(ids.recipient_batch_id) && uuid(ids.send_batch_id), 'api_fixture_not_ready');
    const ACTIVITY: string = ids.activity_id, COMPOSITION: string = ids.composition_id, PREPARATION: string = ids.recipient_batch_id, SEND_BATCH: string = ids.send_batch_id;
    sourceHash = await treeHash(ROOT + '/src'); bundleHash = await treeHash(ROOT + '/out/renderer');
    before = { controls: await readFile(PRIVATE + '/state/control.json'), model: await readFile(PRIVATE + '/state/events.jsonl'), smtp: await readFile(PRIVATE + '/state/smtp-events.jsonl') };
    Object.assign(report, { source_hash: sourceHash, bundle_hash: bundleHash, backend_revision: fixture.backend_revision, migration: fixture.migration, fixture: { activity_id: ACTIVITY, composition_id: COMPOSITION, recipient_batch_id: PREPARATION, send_batch_id: SEND_BATCH }, api_ledger: apiLedgerPath, screenshots: [] });
    const fetcher: Fetcher = async (url, init) => {
      const u = new URL(url), qualify = init.method === 'POST' && u.pathname === `/api/v2/outreach/compositions/${COMPOSITION}/qualification`;
      const allowedGet = init.method === 'GET' && /^\/api\/(v1\/(session$|settings\/|outreach\/smtp$)|v2\/(library\/(games|creators)|activities|discovery|saved-sets|outreach\/))/.test(u.pathname);
      if (u.origin !== ORIGIN || !(qualify || allowedGet)) { forbiddenHTTP++; throw new Error('http_read_only_scope'); }
      const key = `${init.method} ${u.pathname.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi, ':id')}`; http[key] = (http[key] ?? 0) + 1;
      return fetch(u, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
    };
    const connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
    const match = new MatchClient(r => authenticatedMatchRequest(fetcher, connection, r));
    const outreach = new OutreachClient(r => authenticatedOutreachRequest(fetcher, connection, r));
    const drafts = new DraftsClient(r => authenticatedDraftsRequest(fetcher, connection, r));
    const sending = new SendingClient(r => authenticatedSendingRequest(fetcher, connection, r));
    const games = new GameClient(r => authenticatedGameRequest(fetcher, connection, r));
    const library = new LibraryClient((r, q) => authenticatedGet(fetcher, connection, r, q));
    const savedSets = new SavedSetClient(r => authenticatedSavedSetRequest(fetcher, connection, r));
    const settings = new SettingsClient(r => authenticatedSettingsRequest(fetcher, connection, r));
    const creators = new CreatorClient(r => authenticatedCreatorRequest(fetcher, connection, r));
    report.stage = 'baseline_reads';
    const composition = await drafts.composition(COMPOSITION), activity = await match.activity(ACTIVITY), frozen = await sending.batch(SEND_BATCH);
    safe(composition.activity_id === ACTIVITY && composition.recipient_batch_id === PREPARATION && frozen.activity_id === ACTIVITY && frozen.composition_id === COMPOSITION, 'baseline_scope');
    safe(activity.name.startsWith('P7 ') && composition.recipient_count === composition.drafts.length && composition.drafts.length > 0 && frozen.deliveries.length > 0, 'own_labeled_fixture');
    safe(frozen.qualification.total_count === composition.recipient_count && frozen.qualification.members.every((m, i) => m.draft_id === composition.drafts[i]?.id), 'full_n_order');
    safe(frozen.deliveries.every(row => row.state !== 'queued' && row.state !== 'sending'), 'fixture_worker_not_settled');
    Object.assign(report, { recipient_count: composition.recipient_count, delivery_count: frozen.deliveries.length, delivery_states: frozen.deliveries.map(r => r.state), frozen_html_hashes: frozen.deliveries.map(r => sha(r.snapshot.html ?? '')) });
    const scoped = (v: any) => { safe(v.activityId === ACTIVITY, 'activity_scope'); return v; };
    const actions: Record<string, (input?: any) => Promise<unknown>> = {
      'connection.status': async () => ({ serviceUrl: ORIGIN, hasKey: true, storageAvailable: true }),
      'connection.test': async () => { await library.session(); return { authenticated: true, proxy: 'system', route: 'direct' }; },
      'preferences.read': async () => ({ appearance: 'system', fontSize: 'default', automaticUpdates: false }),
      'updates.status': async () => ({ phase: 'development', installedVersion: '0.2.0-alpha.1', lastCheckedAt: null, lastAttemptAt: null, release: null, error: null }),
      'library.list': v => library.list(v), 'library.detail': v => library.detail(v), 'games.list': v => games.list(v), 'games.detail': v => games.detail(v),
      'creators.list': v => creators.list(v),
      'settings.collection': () => settings.collection(), 'settings.smtp': () => settings.smtp(),
      'match.activities': v => match.activities(v), 'match.activity': v => { safe(v === ACTIVITY, 'activity_scope'); return match.activity(v); },
      'match.plans': v => match.plans(v), 'match.plan': v => match.plan(v), 'match.query': v => match.query(v), 'match.candidates': v => match.candidates(v), 'match.evaluations': v => match.evaluations(v),
      'savedSets.list': v => savedSets.list(v), 'outreach.selections': v => outreach.selections(v), 'outreach.selection': v => outreach.selection(v), 'outreach.batches': v => outreach.batches(scoped(v)),
      'outreach.batch': v => { scoped(v); safe(v.id === PREPARATION, 'preparation_scope'); return outreach.batch(v); },
      'drafts.templates': v => drafts.templates(v), 'drafts.template': v => drafts.template(v), 'drafts.compositions': v => drafts.compositions(scoped(v)),
      'drafts.composition': v => { safe(v === COMPOSITION, 'composition_scope'); return drafts.composition(v); },
      'sending.batches': v => sending.batches(scoped(v)), 'sending.batch': v => { safe(v === SEND_BATCH, 'send_batch_scope'); return sending.batch(v); },
      'sending.qualify': v => { safe(v.compositionId === COMPOSITION, 'qualification_scope'); return sending.qualify(v); },
    };
    server = createServer(async (req, res) => {
      const renderer = ROOT + '/out/renderer', relative = req.url === '/' ? 'index.html' : String(req.url).split('?')[0].replace(/^\/+/, ''), file = path.resolve(renderer, relative);
      if (req.method !== 'GET' || !file.startsWith(renderer + '/')) { res.writeHead(403).end(); return; }
      try { const mime: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }; res.writeHead(200, { 'Content-Type': mime[path.extname(file)] ?? 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(await readFile(file)); } catch { res.writeHead(404).end(); }
    });
    await new Promise<void>(r => server!.listen(0, '127.0.0.1', r)); const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    context = await browser.newContext({ viewport: { width: 1320, height: 920 }, reducedMotion: 'reduce' });
    await context.route('**/*', route => { const url = route.request().url(); if (url.startsWith(origin + '/') || url.startsWith('data:') || url.startsWith('about:')) return route.continue(); blockedBrowser++; return route.abort(); });
    const page = await context.newPage(); page.on('pageerror', () => pageErrors++); page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleProblems++; });
    await page.exposeBinding('__fmgInvoke', async (_source, name: string, input: unknown) => { bridge[name] = (bridge[name] ?? 0) + 1; const action = actions[name]; if (!action) { unexpectedBridge++; return { ok: false, error: { code: 'fixture_read_only', message: 'This verification permits reads only.', retryable: false } }; } return publicResult(() => action(input)); });
    await page.addInitScript(() => {
      const group = (name: string, methods: string[]) => Object.fromEntries(methods.map(method => [method, (input?: unknown) => (window as any).__fmgInvoke(`${name}.${method}`, input)]));
      Object.defineProperty(window, 'desktop', { configurable: false, value: {
        connection: group('connection', ['status', 'test', 'save', 'clear']), preferences: group('preferences', ['read', 'update', 'restoreAppearance']), updates: group('updates', ['status', 'check']), library: group('library', ['list', 'detail']), games: group('games', ['list', 'detail', 'create', 'update']),
        creators: group('creators', ['list', 'detail', 'create', 'update', 'rebind', 'works', 'createWork', 'updateWork', 'createContact', 'updateContact']), settings: group('settings', ['collection', 'connection', 'setCollection', 'replaceConnection', 'testConnection', 'reanalysis', 'saveReanalysis', 'smtp', 'saveSMTP', 'testSMTP', 'sendTestEmail']),
        match: group('match', ['activities', 'activity', 'createActivity', 'plans', 'plan', 'createPlan', 'retryPlan', 'query', 'candidates', 'stop', 'continueDiscovery', 'evaluations', 'evaluate', 'evaluation', 'evaluationResults', 'retryEvaluation']), savedSets: group('savedSets', ['list', 'detail', 'results', 'create']), outreach: group('outreach', ['selections', 'selection', 'add', 'bulk', 'update', 'cancel', 'batches', 'batch', 'freeze']),
        drafts: group('drafts', ['templates', 'template', 'registerCanonical', 'createTemplate', 'compositions', 'composition', 'createComposition', 'edit', 'refresh', 'retry', 'senderFacts']), sending: group('sending', ['qualify', 'send', 'batches', 'batch', 'retry', 'resolve']), openExternal: (v: string) => (window as any).__fmgInvoke('openExternal', v),
      } });
    });
    report.stage = 'sending_history'; await page.goto(origin); await expect(page.getByText('Workspace linked', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Match', exact: true }).click(); await expect(page.getByRole('button', { name: /^Open / }).first()).toBeVisible();
    let located = false; for (let i = 0; i < 10; i++) { const open = page.getByRole('button', { name: `Open ${activity.name}`, exact: true }); if (await open.count()) { await open.click(); located = true; break; } const next = page.getByRole('button', { name: 'Next page', exact: true }); await expect(next).toBeEnabled(); await next.click(); }
    safe(located, 'own_activity_visible');
    await page.getByRole('button', { name: 'Sending history', exact: true }).click(); await page.getByRole('button', { name: 'View deliveries', exact: true }).click();
    const delivery = page.getByRole('region', { name: 'Frozen deliveries', exact: true }), deliveryRoster = delivery.getByRole('navigation', { name: 'Deliveries', exact: true });
    await expect(deliveryRoster.getByRole('button')).toHaveCount(frozen.deliveries.length);
    const labels: string[] = [];
    for (const [index, row] of frozen.deliveries.entries()) {
      await deliveryRoster.getByRole('button').nth(index).click(); const preview = delivery.getByTitle('Frozen email preview');
      await expect(preview).toHaveAttribute('sandbox', ''); safe((await preview.getAttribute('srcdoc'))?.includes(row.snapshot.html!), 'exact_frozen_html');
      const label = row.state === 'sent' ? row.resolution.outcome === 'sent' && row.resolution.attempt === row.attempt ? 'Recorded as sent' : 'Accepted by SMTP' : row.state === 'unknown' ? 'Outcome unknown' : 'Failed';
      await expect(delivery.locator('.delivery-person-heading').getByRole('status')).toHaveText(label); labels.push(label);
      if (row.state === 'unknown') await expect(delivery.getByRole('button', { name: /Retry delivery|Dispatch queued/ })).toHaveCount(0);
    }
    report.status_labels = labels;
    await delivery.getByText(`Original qualification and exclusions (${composition.recipient_count} people)`, { exact: true }).click();
    await expect(delivery.locator('.delivery-qualification li')).toHaveCount(composition.recipient_count);
    await page.screenshot({ path: testInfo.outputPath('sending-wide.png') });
    report.screenshots = [testInfo.outputPath('sending-wide.png')];
    report.stage = 'qualification_detour'; await page.getByRole('button', { name: 'Draft history', exact: true }).click(); await page.getByRole('button', { name: 'Open draft set', exact: true }).click();
    await page.getByRole('button', { name: 'Review sending', exact: true }).click();
    const review = page.getByRole('region', { name: 'Review recipients', exact: true }), roster = review.getByRole('navigation', { name: 'Recipients', exact: true });
    await expect(roster.getByRole('button')).toHaveCount(composition.recipient_count); await expect(review.getByRole('button', { name: 'Check recipients', exact: true })).toBeEnabled();
    await review.getByRole('checkbox').check(); const reason = review.getByRole('textbox', { name: /^Exclusion reason/ }), local = 'P7 headless local exclusion retained; not submitted.';
    await reason.fill(local); await expect(review.getByRole('button', { name: /^Send \d+ emails?$/ })).toHaveCount(0);
    await review.getByRole('button', { name: 'SMTP settings', exact: true }).click(); await expect(page.getByRole('heading', { name: 'Email delivery', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Return to Match', exact: true }).click(); await expect(reason).toHaveValue(local); await expect(review.getByRole('status')).toHaveText('Recheck required');
    report.stage = 'narrow_keyboard'; await page.setViewportSize({ width: 760, height: 920 }); await page.evaluate(() => { document.documentElement.style.fontSize = '135%'; });
    await expect(roster.getByRole('button')).toHaveCount(composition.recipient_count); await reason.focus(); await expect(reason).toBeFocused(); await page.keyboard.press('Tab');
    safe(await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement !== document.body), 'keyboard_focus');
    const layout = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth, reduced: matchMedia('(prefers-reduced-motion: reduce)').matches }));
    safe(layout.width <= layout.viewport + 1 && layout.reduced, 'narrow_reduced_motion'); await expect(reason).toHaveValue(local);
    await page.screenshot({ path: testInfo.outputPath('sending-narrow-135.png') });
    report.screenshots = ['sending-wide.png', 'sending-narrow-135.png'].map(name => testInfo.outputPath(name));
    report.stage = 'durable_unchanged'; safe(JSON.stringify(await drafts.composition(COMPOSITION)) === JSON.stringify(composition), 'composition_changed'); safe(JSON.stringify(await sending.batch(SEND_BATCH)) === JSON.stringify(frozen), 'frozen_batch_changed');
    safe(JSON.stringify((await match.activity(ACTIVITY)).source_snapshot) === JSON.stringify(activity.source_snapshot), 'activity_source_changed');
    safe(pageErrors === 0 && consoleProblems === 0 && unexpectedBridge === 0 && forbiddenHTTP === 0 && blockedBrowser === 0, 'runtime_errors');
    report.status = 'passed'; report.stage = 'complete';
  } catch (error) { report.status = 'failed'; report.error = error instanceof Error && /^[a-z0-9_]+$/.test(error.message) ? error.message : 'ui_assertion_failed'; }
  finally {
    try { await context?.close(); } catch { report.status = 'failed'; report.cleanup_error = 'browser_close_failed'; }
    try { if (server) await new Promise<void>(r => server!.close(() => r())); } catch { report.status = 'failed'; report.cleanup_error = 'server_close_failed'; }
    try {
      if (before) { const after = { controls: await readFile(PRIVATE + '/state/control.json'), model: await readFile(PRIVATE + '/state/events.jsonl'), smtp: await readFile(PRIVATE + '/state/smtp-events.jsonl') }; const unchanged = before.controls.equals(after.controls) && before.model.equals(after.model) && before.smtp.equals(after.smtp); report.fixture_effects = { unchanged, controls_before: sha(before.controls), controls_after: sha(after.controls), model_before: sha(before.model), model_after: sha(after.model), smtp_before: sha(before.smtp), smtp_after: sha(after.smtp) }; if (!unchanged) { report.status = 'failed'; report.error = 'fixture_effects_changed'; } }
      if (sourceHash && bundleHash) { report.source_hash_after = await treeHash(ROOT + '/src'); report.bundle_hash_after = await treeHash(ROOT + '/out/renderer'); if (sourceHash !== report.source_hash_after || bundleHash !== report.bundle_hash_after) { report.status = 'failed'; report.error = 'source_freeze_changed'; } }
    } catch { report.status = 'failed'; report.final_check_error = 'physical_evidence_unavailable'; }
    report.http_counts = http; report.bridge_counts = bridge; report.errors = { pageErrors, consoleProblems, unexpectedBridge, forbiddenHTTP, blockedBrowser };
    report.get_requests = Object.entries(http).filter(([key]) => key.startsWith('GET ')).reduce((n, [, v]) => n + v, 0); report.qualification_requests = Object.entries(http).filter(([key]) => key.startsWith('POST ')).reduce((n, [, v]) => n + v, 0);
    await writeFile(ledgerPath, JSON.stringify(report, null, 2), { mode: 0o600 });
    console.log(JSON.stringify({ status: report.status, stage: report.stage, ledger: ledgerPath }));
  }
  safe(report.status === 'passed', `p7_renderer_failed_${String(report.stage)}`);
});
