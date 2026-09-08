import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { previewDocument } from '../src/shared/mail-preview';

const gameId = '11111111-1111-4111-8111-111111111111';
const creatorId = '22222222-2222-4222-8222-222222222222';
const testKey = 'local-fixture-only-not-a-production-key';
const timestamp = '2026-09-08T01:00:00Z';
function profile(kind: 'game' | 'creator') {
  return {
    type: kind, id: kind === 'game' ? gameId : creatorId,
    name: kind === 'game' ? 'Test Fixture — Forest Signal' : 'Test Fixture — Pixel Harbor',
    steam_app_id: '123456', youtube_channel_id: 'UC_local_test_fixture',
    canonical_url: kind === 'game' ? 'https://store.steampowered.com/app/123456/' : 'https://www.youtube.com/channel/UC_local_test_fixture',
    favorite: false, current_facts: { description: 'Explicit local test data, not a real creator or production game.', subscriber_count: null },
    brief: {}, source_status: {}, last_analyzed_at: timestamp, next_analysis_at: null,
    contact: null, contacts: [], analysis: {}, model_metadata: {}, prompt_metadata: {}, manual_notes: null,
  };
}

test('desktop Library HTTP path, credentials, navigation, narrow layout and isolation', async () => {
  const requests: { method: string; path: string }[] = [];
  let failCreators = false;
  const server = createServer((request, response) => {
    const url = new URL(request.url!, 'http://localhost');
    requests.push({ method: request.method!, path: url.pathname });
    response.setHeader('Content-Type', 'application/json');
    if (request.method !== 'GET' || request.headers.authorization !== `Bearer ${testKey}`) { response.writeHead(401).end('{}'); return; }
    if (url.pathname === '/api/v1/session') response.end(JSON.stringify({ workspace_name: 'LOCAL TEST FIXTURE', api_version: 'v1', service_connections: {} }));
    else if (url.pathname === '/api/v1/profiles/creators' && failCreators) response.writeHead(503).end('{}');
    else if (url.pathname === '/api/v1/profiles/creators') response.end(JSON.stringify({ items: [profile('creator')], next_cursor: null }));
    else if (url.pathname === '/api/v1/profiles/games') response.end(JSON.stringify({ items: [profile('game')], next_cursor: null }));
    else if (url.pathname === `/api/v1/profiles/creators/${creatorId}`) response.end(JSON.stringify(profile('creator')));
    else if (url.pathname === `/api/v1/profiles/games/${gameId}`) response.end(JSON.stringify(profile('game')));
    else response.writeHead(404).end('{}');
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address() as {port: number};
  const userData = await mkdtemp(path.join(tmpdir(), 'fmg-desktop-e2e-'));
  const environment = Object.fromEntries(Object.entries(process.env).filter(([name, value]) => value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(name))) as Record<string, string>;
  let app: ElectronApplication | undefined;
  try {
    app = await electron.launch({ args: ['.', `--user-data-dir=${userData}`], cwd: process.cwd(), env: environment, chromiumSandbox: true });
    const page = await app.firstWindow();
    await expect(page.getByRole('heading', { name: 'Connect your workspace' })).toBeVisible();
    await page.getByRole('button', { name: 'Open Settings', exact: true }).click();
    await page.getByLabel('Service URL').fill(`http://127.0.0.1:${address.port}`);
    await page.getByLabel('Workspace key', {exact: true}).fill(testKey);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.getByText('Connection verified', {exact: true})).toBeVisible();
    await expect(page.getByLabel('Workspace key', {exact: true})).toHaveValue('');
    await page.getByRole('button', {name: 'Library', exact: true}).click();
    await expect(page.getByRole('button', {name: 'Open Test Fixture — Pixel Harbor', exact: true})).toBeVisible();
    await page.getByRole('button', {name: 'Open Test Fixture — Pixel Harbor', exact: true}).click();
    await expect(page.getByRole('heading', {name: 'Test Fixture — Pixel Harbor', exact: true})).toBeVisible();
    await page.getByRole('button', {name: 'Back to creators', exact: true}).click();
    await page.getByRole('tab', {name: 'Games', exact: true}).click();
    await expect(page.getByRole('button', {name: 'Open Test Fixture — Forest Signal', exact: true})).toBeVisible();
    for (const name of ['Match', 'Outreach']) {
      await page.getByRole('button', {name, exact: true}).click();
      await expect(page.getByRole('region', {name:`${name.toLowerCase()} page`,exact:true}).getByText('Not connected yet', {exact: true})).toBeVisible();
    }
    await page.getByRole('button', {name: 'Library', exact: true}).click();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(760, 660));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:'output/playwright/library-narrow.png'});
    const boundary = await page.evaluate(() => ({node: typeof (window as any).require, process: typeof (window as any).process, keyInDOM: document.body.innerText.includes('local-fixture-only-not-a-production-key'), methods: Object.keys(window.desktop).sort(), storage: localStorage.length}));
    expect(boundary).toEqual({node:'undefined',process:'undefined',keyInDOM:false,methods:['connection','library','openExternal'],storage:0});
    const stored = await readFile(path.join(userData, 'credentials.json'), 'utf8');
    expect(stored).not.toContain(testKey);
    const denied = await page.evaluate(() => window.desktop.openExternal('file:///etc/passwd'));
    expect(denied.ok).toBe(false);
    await page.evaluate(html => { const frame = document.createElement('iframe'); frame.title='Isolated email preview'; frame.setAttribute('sandbox',''); frame.srcdoc=html; document.body.append(frame); }, previewDocument('<script>window.attacked=true</script><p>Preview test</p>'));
    const preview = page.frameLocator('iframe[title="Isolated email preview"]');
    await expect(preview.getByText('Preview test')).toBeVisible();
    const isolated = await preview.locator('body').evaluate(() => ({bridge:typeof (window as any).desktop,node:typeof (window as any).require,script:(window as any).attacked===true}));
    expect(isolated).toEqual({bridge:'undefined',node:'undefined',script:false});
    await page.locator('iframe[title="Isolated email preview"]').evaluate(frame => frame.remove());
    // Re-open the persisted connection; no key is passed through the renderer on reload.
    await page.reload();
    await expect(page.getByRole('button', {name: 'Open Test Fixture — Pixel Harbor', exact: true})).toBeVisible();
    failCreators = true;
    await page.getByRole('searchbox').fill('failure');
    await page.getByRole('searchbox').press('Enter');
    await expect(page.getByRole('alert')).toContainText('HTTP 503');
    failCreators = false;
    await page.getByRole('button', {name:'Try again',exact:true}).click();
    await expect(page.getByRole('button', {name:'Open Test Fixture — Pixel Harbor',exact:true})).toBeVisible();
    expect(requests.every(request => request.method === 'GET')).toBe(true);
    expect(requests.some(request => request.path === `/api/v1/profiles/creators/${creatorId}`)).toBe(true);
  } finally {
    await app?.close();
    await new Promise<void>(resolve => server.close(() => resolve()));
    await rm(userData, {recursive:true,force:true});
  }
});
