import { test, expect } from '@playwright/test';
import { readFile, writeFile, readdir, stat } from 'node:fs/promises';
import { createServer } from 'node:http';
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
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import { GameClient } from '../src/main/game-client';
import { LibraryClient } from '../src/main/library-client';
import { SavedSetClient } from '../src/main/saved-set-client';
import { authenticatedSavedSetRequest } from '../src/main/saved-set-transport';
import { SettingsClient } from '../src/main/settings-client';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';
import { authenticatedGet, authenticatedGameRequest, publicResult, type Fetcher } from '../src/main/transport';

// Separate headless production-renderer evidence, never native Electron evidence.
// Requires root's frozen built source and exclusive62611 lease; deliberately GET-only.
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
const PRIVATE = '/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-ixcaiiq1/private';
const ORIGIN = 'http://127.0.0.1:62611';
const ACTIVITY = '3d1eba1d-224e-4f2a-916f-ac4cbc7350e7';
const COMPOSITION = '525574b6-039e-4a4c-a1bf-15f9e2f3af48';
const BATCH = '5da18793-25a7-446e-ab70-17991d2d6cae';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const requireSafe = (condition: unknown, code: string): void => { if (!condition) throw new Error(code); };
async function treeHash(directory: string): Promise<string> {
  const hash = createHash('sha256');
  async function walk(dir: string) { for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) { const full = path.join(dir, entry.name); if (entry.isDirectory()) await walk(full); else if (entry.isFile()) { hash.update(path.relative(directory, full)); hash.update(await readFile(full)); } } }
  await walk(directory); return hash.digest('hex');
}

test('F8 built renderer retains full N and local edits through source and people detours', async ({ browser }, testInfo) => {
  test.skip(process.env.FMG_F8_RENDERER_FROZEN !== '62611', 'Requires root source freeze and exclusive fixture lease.');
  test.setTimeout(120_000);
  requireSafe(((await stat(PRIVATE + '/client.json')).mode & 0o777) === 0o600, 'fixture_permissions');
  const fixture = JSON.parse(await readFile(PRIVATE + '/client.json', 'utf8'));
  requireSafe(fixture.base_url === ORIGIN && fixture.backend_revision === 'ece2e9d9558dfe057dc40ad58bd98a86e3149dd5' && fixture.migration === '20260908_0017', 'fixture_pin');
  const sourceHash = await treeHash(ROOT + '/src'), bundleHash = await treeHash(ROOT + '/out/renderer');
  const controls = await readFile(PRIVATE + '/state/control.json'), events = await readFile(PRIVATE + '/state/events.jsonl'), smtpEvents = await readFile(PRIVATE + '/state/smtp-events.jsonl');
  const report: Record<string, unknown> = { status: 'running', source_hash: sourceHash, bundle_hash: bundleHash, stage: 'bootstrap', backend_revision: fixture.backend_revision, migration: fixture.migration, write_requests: 0 };
  const reportPath = PRIVATE + `/f8-renderer-${randomUUID()}.json`;
  const records: Record<string, number> = {}, bridgeCalls: Record<string, number> = {}; let pageErrors = 0, consoleProblems = 0, unexpectedBridge = 0, blockedBrowser = 0, unsafeNetwork = 0;
  const fetcher: Fetcher = async (url, init) => {
    const u = new URL(url); if (u.origin !== ORIGIN || init.method !== 'GET' || !/^\/api\/(v1\/(session|settings\/collection)$|v2\/(library\/(games|creators)|activities|discovery|saved-sets|outreach\/(template-versions|compositions)))/.test(u.pathname)) { unsafeNetwork++; throw new Error('http_read_only_scope'); }
    const family = u.pathname.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi, ':id'); records[family] = (records[family] ?? 0) + 1;
    return fetch(u, { ...init, signal: AbortSignal.any([AbortSignal.timeout(20_000), ...(init.signal ? [init.signal] : [])]) });
  };
  const connection = { serviceUrl: ORIGIN, key: fixture.workspace_key };
  const match = new MatchClient(r => authenticatedMatchRequest(fetcher, connection, r));
  const outreach = new OutreachClient(r => authenticatedOutreachRequest(fetcher, connection, r));
  const drafts = new DraftsClient(r => authenticatedDraftsRequest(fetcher, connection, r));
  const creators = new CreatorClient(r => authenticatedCreatorRequest(fetcher, connection, r));
  const games = new GameClient(r => authenticatedGameRequest(fetcher, connection, r));
  const library = new LibraryClient((r, q) => authenticatedGet(fetcher, connection, r, q));
  const savedSets = new SavedSetClient(r => authenticatedSavedSetRequest(fetcher, connection, r));
  const settings = new SettingsClient(r => authenticatedSettingsRequest(fetcher, connection, r));
  const baseline = await drafts.composition(COMPOSITION), activity = await match.activity(ACTIVITY), batch = await outreach.batch({ activityId: ACTIVITY, id: BATCH });
  requireSafe(baseline.activity_id === ACTIVITY && baseline.recipient_batch_id === BATCH && baseline.drafts.length === 3 && baseline.drafts[1].status === 'succeeded', 'baseline_scope');
  const completed = baseline.drafts[1], completedName = String(completed.input.channel_name), creatorIds = new Set(batch.recipients.map(v => v.snapshot.creator_id));
  const actions: Record<string, (input?: any) => Promise<unknown>> = {
    'connection.status': async () => ({ serviceUrl: ORIGIN, hasKey: true, storageAvailable: true }),
    'connection.test': async () => { await library.session(); return { authenticated: true, proxy: 'system', route: 'direct' }; },
    'preferences.read': async () => ({ appearance: 'system', fontSize: 'default', automaticUpdates: false }),
    'updates.status': async () => ({ phase: 'development', installedVersion: '0.2.0-alpha.1', lastCheckedAt: null, lastAttemptAt: null, release: null, error: null }),
    'library.list': v => library.list(v), 'library.detail': v => library.detail(v),
    'games.list': v => games.list(v), 'games.detail': v => games.detail(v),
    'creators.list': v => creators.list(v), 'creators.detail': v => { requireSafe(creatorIds.has(v), 'creator_scope'); return creators.detail(v); },
    'creators.works': v => { requireSafe(creatorIds.has(v.creatorId), 'creator_scope'); return creators.works(v); },
    'settings.collection': () => settings.collection(),
    'match.activities': v => match.activities(v), 'match.activity': v => { requireSafe(v === ACTIVITY, 'activity_scope'); return match.activity(v); },
    'match.plans': v => match.plans(v), 'match.plan': v => match.plan(v), 'match.query': v => match.query(v), 'match.candidates': v => match.candidates(v), 'match.evaluations': v => match.evaluations(v),
    'savedSets.list': v => savedSets.list(v),
    'outreach.selections': v => outreach.selections(v), 'outreach.selection': v => outreach.selection(v), 'outreach.batches': v => outreach.batches(v), 'outreach.batch': v => { requireSafe(v.activityId === ACTIVITY && v.id === BATCH, 'batch_scope'); return outreach.batch(v); },
    'drafts.templates': v => drafts.templates(v), 'drafts.template': v => drafts.template(v), 'drafts.compositions': v => { requireSafe(v.activityId === ACTIVITY, 'draft_activity_scope'); return drafts.compositions(v); },
    'drafts.composition': v => { requireSafe(v === COMPOSITION, 'composition_scope'); return drafts.composition(v); },
  };
  const server = createServer(async (req, res) => {
    const renderer = ROOT + '/out/renderer'; const relative = req.url === '/' ? 'index.html' : String(req.url).split('?')[0].replace(/^\/+/, ''); const file = path.resolve(renderer, relative);
    if (req.method !== 'GET' || !file.startsWith(renderer + '/')) { res.writeHead(403).end(); return; }
    try { const mime: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }; res.writeHead(200, { 'Content-Type': mime[path.extname(file)] ?? 'application/octet-stream', 'Cache-Control': 'no-store' }); res.end(await readFile(file)); } catch { res.writeHead(404).end(); }
  });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r)); const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const context = await browser.newContext({ viewport: { width: 1320, height: 920 }, reducedMotion: 'reduce' });
  await context.route('**/*', route => { const url = route.request().url(); if (url.startsWith(origin + '/') || url.startsWith('data:') || url.startsWith('about:')) return route.continue(); blockedBrowser++; return route.abort(); });
  const page = await context.newPage(); page.on('pageerror', () => pageErrors++); page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleProblems++; });
  try {
    await page.exposeBinding('__fmgInvoke', async (_source, name: string, input: unknown) => { bridgeCalls[name] = (bridgeCalls[name] ?? 0) + 1; const action = actions[name]; if (!action) { unexpectedBridge++; return { ok: false, error: { code: 'fixture_read_only', message: 'This verification permits reads only.', retryable: false } }; } return publicResult(() => action(input)); });
    await page.addInitScript(() => {
      const group = (name: string, methods: string[]) => Object.fromEntries(methods.map(method => [method, (input?: unknown) => (window as any).__fmgInvoke(`${name}.${method}`, input)]));
      Object.defineProperty(window, 'desktop', { configurable: false, value: {
        connection: group('connection', ['status', 'test', 'save', 'clear']), preferences: group('preferences', ['read', 'update', 'restoreAppearance']), updates: group('updates', ['status', 'check']), library: group('library', ['list', 'detail']), games: group('games', ['list', 'detail', 'create', 'update']),
        creators: group('creators', ['list', 'detail', 'create', 'update', 'rebind', 'works', 'createWork', 'updateWork', 'createContact', 'updateContact']), settings: group('settings', ['collection', 'connection', 'setCollection', 'replaceConnection', 'testConnection', 'reanalysis', 'saveReanalysis', 'smtp', 'saveSMTP', 'testSMTP', 'sendTestEmail']),
        match: group('match', ['activities', 'activity', 'createActivity', 'plans', 'plan', 'createPlan', 'retryPlan', 'query', 'candidates', 'stop', 'continueDiscovery', 'evaluations', 'evaluate', 'evaluation', 'evaluationResults', 'retryEvaluation']), savedSets: group('savedSets', ['list', 'detail', 'results', 'create']), outreach: group('outreach', ['selections', 'selection', 'add', 'bulk', 'update', 'cancel', 'batches', 'batch', 'freeze']),
        drafts: group('drafts', ['templates', 'template', 'registerCanonical', 'createTemplate', 'compositions', 'composition', 'createComposition', 'edit', 'refresh', 'retry', 'senderFacts']), openExternal: (v: string) => (window as any).__fmgInvoke('openExternal', v),
      } });
    });
    report.stage = 'open_history'; await page.goto(origin); await expect(page.getByText('Workspace linked', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Match', exact: true }).click();
    await expect(page.getByRole('button', { name: /^Open / }).first()).toBeVisible();
    let located = false; for (let i = 0; i < 10; i++) { const open = page.getByRole('button', { name: `Open ${activity.name}`, exact: true }); if (await open.count()) { await open.click(); located = true; break; } const next = page.getByRole('button', { name: 'Next page', exact: true }); await expect(next).toBeEnabled(); await next.click(); }
    requireSafe(located, 'own_activity_visible');
    await page.getByRole('button', { name: 'Draft history', exact: true }).click(); await page.getByRole('button', { name: 'Open draft set', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Draft history', exact: true })).toHaveAttribute('aria-expanded', 'false');
    const workspace = page.getByRole('region', { name: 'Outreach drafts', exact: true }); const roster = workspace.getByRole('navigation', { name: 'Draft people' });
    await expect(roster.getByRole('button')).toHaveCount(3); await roster.getByRole('button').nth(1).click();
    await workspace.getByRole('button', { name: 'Edit personalization', exact: true }).click();
    const observation = workspace.getByRole('textbox', { name: 'Observation', exact: true }); await expect(observation).toHaveValue(completed.values!.observation);
    const preview = workspace.getByTitle('Saved email preview'); await expect(preview).toHaveAttribute('sandbox', '');
    requireSafe((await preview.getAttribute('srcdoc'))?.includes(completed.rendered!.html), 'exact_server_html');
    await expect(page.frameLocator('iframe[title="Saved email preview"]').getByText('Toki', { exact: true })).toBeVisible();
    await expect(workspace.getByRole('button', { name: /^Send$/i })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('drafts-wide.png') });
    report.stage = 'local_dirty_detours'; const local = 'retained this unsaved synthetic observation.'; await observation.fill(local);
    await roster.getByRole('button').nth(0).click(); await roster.getByRole('button').nth(1).click(); await expect(observation).toHaveValue(local);
    await workspace.getByRole('button', { name: 'Back to people', exact: true }).click(); await page.getByRole('button', { name: 'Back to drafts', exact: true }).click(); await expect(observation).toHaveValue(local);
    await workspace.getByRole('button', { name: 'Edit observation source', exact: true }).click();
    await page.getByRole('button', { name: 'View creator', exact: true }).click(); await expect(page.getByRole('button', { name: 'Back to activity', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Back to activity', exact: true }).click(); await page.getByRole('button', { name: 'Back to drafts', exact: true }).click(); await expect(observation).toHaveValue(local);
    report.stage = 'narrow_keyboard'; await page.setViewportSize({ width: 760, height: 920 }); await page.evaluate(() => { document.documentElement.style.fontSize = '135%'; });
    await expect(roster.getByRole('button')).toHaveCount(3); await expect(observation).toHaveValue(local);
    await expect(observation).toBeEnabled(); await observation.focus(); await expect(observation).toBeFocused(); await page.keyboard.press('Tab'); requireSafe(await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement !== document.body), 'keyboard_focus');
    const width = await page.evaluate(() => ({ actual: document.documentElement.scrollWidth, visible: window.innerWidth, reduced: matchMedia('(prefers-reduced-motion: reduce)').matches })); requireSafe(width.actual <= width.visible + 1 && width.reduced, 'narrow_reduced_motion');
    await page.screenshot({ path: testInfo.outputPath('drafts-narrow-135.png') });
    report.stage = 'durable_unchanged'; requireSafe(JSON.stringify(await drafts.composition(COMPOSITION)) === JSON.stringify(baseline), 'local_edits_did_not_write');
    requireSafe(JSON.stringify((await match.activity(ACTIVITY)).source_snapshot) === JSON.stringify(activity.source_snapshot), 'activity_source_unchanged');
    requireSafe(controls.equals(await readFile(PRIVATE + '/state/control.json')) && events.equals(await readFile(PRIVATE + '/state/events.jsonl')) && smtpEvents.equals(await readFile(PRIVATE + '/state/smtp-events.jsonl')), 'no_fixture_effects');
    requireSafe(sourceHash === await treeHash(ROOT + '/src') && bundleHash === await treeHash(ROOT + '/out/renderer'), 'source_freeze_changed');
    requireSafe(pageErrors === 0 && consoleProblems === 0 && unexpectedBridge === 0 && unsafeNetwork === 0, 'runtime_errors');
    report.status = 'passed'; report.stage = 'complete'; report.checks = ['full_N_history_GET', 'exact_fixed_iframe', 'local_person_people_creator_detours', 'wide_narrow_135_reduced_keyboard', 'durable_no_writes'];
  } catch (error) { report.status = 'failed'; report.error = error instanceof Error && /^[a-z0-9_]+$/.test(error.message) ? error.message : 'ui_assertion_failed'; throw new Error(`F8 headless verification failed at ${report.stage}; sanitized ledger retained.`); }
  finally { report.http_counts = records; report.bridge_counts = bridgeCalls; report.errors = { pageErrors, consoleProblems, unexpectedBridge, unsafeNetwork, blockedBrowser }; await writeFile(reportPath, JSON.stringify(report, null, 2), { mode: 0o600 }); await context.close(); await new Promise<void>(r => server.close(() => r())); console.log(JSON.stringify({ status: report.status, stage: report.stage, ledger: reportPath })); }
});
