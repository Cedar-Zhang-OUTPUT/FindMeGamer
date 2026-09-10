import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { previewDocument } from '../src/shared/mail-preview';
import { gameFixture } from '../tests/game-fixtures';
import { creatorFixture, contactFixture, workFixture } from '../tests/creator-fixtures';
import { isolatedPreferences } from './preferences';

const gameId = '11111111-1111-4111-8111-111111111111';
const creatorId = '22222222-2222-4222-8222-222222222222';
const testKey = 'local-fixture-only-not-a-production-key';
const creator = {
  ...creatorFixture('Test Fixture — Pixel Harbor', creatorId),
  public_name: 'Pixel Harbor', public_name_confirmed: true, handle: '@pixelharbor',
  description: 'Cozy games, thoughtful reviews, and community livestreams.', languages: ['English'],
  profile_url: 'https://example.invalid/pixel-harbor',
  source_identity: { platform: 'youtube' as const, account_id: 'UC_local_test_fixture', canonical_url: 'https://www.youtube.com/channel/UC_local_test_fixture', revision: 1 },
  contacts: [{ ...contactFixture(), email: 'fixture@example.invalid', purpose: 'Business inquiries', source_url: 'https://example.invalid/pixel-harbor/contact' }],
};
const work = {
  ...workFixture(), creator_id: creatorId, content_title: 'Forest Signal — First impressions',
  content_type: 'review' as const, game_id: gameId, metrics: [{ name: 'views', value: 0 }],
  evidence_excerpt: 'A relaxing exploration game with a hand-painted forest.',
  source_url: 'https://www.youtube.com/watch?v=local_fixture',
};

test('desktop Library HTTP path, credentials, navigation, narrow layout and isolation', async ({}, testInfo) => {
  const requests: { method: string; path: string; query: string }[] = [];
  let failCreators = false;
  const server = createServer((request, response) => {
    const url = new URL(request.url!, 'http://localhost');
    requests.push({ method: request.method!, path: url.pathname, query: url.search });
    response.setHeader('Content-Type', 'application/json');
    if (request.method !== 'GET' || request.headers.authorization !== `Bearer ${testKey}`) { response.writeHead(401).end('{}'); return; }
    if (url.pathname === '/api/v1/session') response.end(JSON.stringify({ workspace_name: 'LOCAL TEST FIXTURE', api_version: 'v1', service_connections: {} }));
    else if (url.pathname === '/api/v2/activities') response.end(JSON.stringify({items:[],total:0,offset:0,limit:50}));
    else if (url.pathname === '/api/v2/library/creators' && failCreators) response.writeHead(503).end('{}');
    else if (url.pathname === '/api/v2/library/creators') response.end(JSON.stringify({ items: [creator], total: 1, offset: 0, limit: 50 }));
    else if (url.pathname === '/api/v2/library/games') response.end(JSON.stringify({ items: [gameFixture('Test Fixture — Forest Signal', gameId)], total:1,offset:0,limit:24 }));
    else if (url.pathname === `/api/v2/library/creators/${creatorId}`) response.end(JSON.stringify(creator));
    else if (url.pathname === `/api/v2/library/creators/${creatorId}/works`) response.end(JSON.stringify({ items: [work], total: 1, offset: 0, limit: 50 }));
    else if (url.pathname === `/api/v2/library/games/${gameId}`) response.end(JSON.stringify(gameFixture('Test Fixture — Forest Signal', gameId)));
    else response.writeHead(404).end('{}');
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address() as {port: number};
  const userData = await mkdtemp(path.join(tmpdir(), 'fmg-desktop-e2e-'));
  await isolatedPreferences(userData);
  const environment = Object.fromEntries(Object.entries(process.env).filter(([name, value]) => value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(name))) as Record<string, string>;
  let app: ElectronApplication | undefined;
  try {
    const executablePath = process.env.FMG_PACKAGED_EXECUTABLE;
    app = await electron.launch({ args: [...(executablePath ? [] : ['.']), `--user-data-dir=${userData}`], ...(executablePath ? {executablePath} : {}), cwd: process.cwd(), env: environment, chromiumSandbox: true });
    if (executablePath) expect(await app.evaluate(({app}) => app.isPackaged)).toBe(true);
    const page = await app.firstWindow();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await expect(page.getByRole('heading', { name: 'Connect your workspace' })).toBeVisible();
    await page.getByRole('button', { name: 'Open Settings', exact: true }).click();
    await page.getByLabel('Service URL').fill(`http://127.0.0.1:${address.port}`);
    await page.getByLabel('Workspace key', {exact: true}).fill(testKey);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.getByText('Connection verified', {exact: true})).toBeVisible();
    await expect(page.getByLabel('Workspace key', {exact: true})).toHaveValue('');
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1320, 920));
    const connectionDetails = page.locator('summary').filter({ hasText: 'Connection details' });
    await expect(page.getByText('System proxy · Direct route', {exact: true})).not.toBeVisible();
    await page.screenshot({path:testInfo.outputPath('settings-workspace-default.png')});
    await connectionDetails.focus();
    await connectionDetails.press('Enter');
    await expect(page.getByText('System proxy · Direct route', {exact: true})).toBeVisible();
    await page.screenshot({path:testInfo.outputPath('settings-workspace-connection-details.png')});
    await connectionDetails.press('Enter');
    await page.getByRole('button', {name: 'Library', exact: true}).click();
    await expect(page.getByRole('button', {name: 'Open Test Fixture — Pixel Harbor', exact: true})).toBeVisible();
    await page.getByRole('button', {name: 'Open Test Fixture — Pixel Harbor', exact: true}).click();
    await expect(page.getByRole('heading', {name: 'Test Fixture — Pixel Harbor', exact: true})).toBeVisible();
    await expect(page.getByRole('tab', {name:'Profile',exact:true})).toHaveAttribute('aria-selected','true');
    await expect(page.getByRole('article').getByText('Followers unknown',{exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'Change identity',exact:true})).not.toBeVisible();
    await expect(page.getByText('UC_local_test_fixture',{exact:true})).not.toBeVisible();
    await expect(page.getByRole('heading',{name:'fixture@example.invalid',exact:true})).not.toBeVisible();
    await page.screenshot({path:testInfo.outputPath('creator-profile-default.png')});
    const accountIdentity = page.locator('summary').filter({hasText:'Account identity'});
    await accountIdentity.focus();
    await accountIdentity.press('Enter');
    await expect(page.getByRole('button',{name:'Change identity',exact:true})).toBeVisible();
    await expect(page.getByText('UC_local_test_fixture',{exact:true})).toBeVisible();
    await page.screenshot({path:testInfo.outputPath('creator-account-identity-expanded.png')});
    await accountIdentity.press('Enter');
    await page.getByRole('button',{name:'Emails',exact:true}).focus();
    await page.getByRole('button',{name:'Emails',exact:true}).press('Enter');
    await expect(page.getByRole('button', { name: 'Emails',exact:true})).toBeFocused();
    await expect(page.getByRole('heading',{name:'fixture@example.invalid',exact:true})).toBeVisible();
    await page.screenshot({path:testInfo.outputPath('creator-emails.png')});
    await page.getByRole('button',{name:'Known works',exact:true}).focus();
    await page.getByRole('button',{name:'Known works',exact:true}).press('Enter');
    await expect(page.getByRole('button', { name: 'Known works',exact:true})).toBeFocused();
    await expect(page.getByRole('heading',{name:'Forest Signal — First impressions',exact:true})).toBeVisible();
    await expect(page.getByRole('region',{name:'Known works',exact:true}).getByText('Test Fixture — Forest Signal',{exact:true})).toBeVisible();
    await page.screenshot({path:testInfo.outputPath('creator-known-works.png')});
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(760, 820));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('creator-known-works-narrow.png')});
    await page.getByRole('button', { name: 'Known works',exact:true}).press('Enter');
    await page.getByRole('tab',{name:'Profile',exact:true}).focus();
    await expect(page.getByRole('tab',{name:'Profile',exact:true})).toBeFocused();
    await expect(page.getByRole('button',{name:'Edit profile',exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'Change identity',exact:true})).not.toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('creator-profile-narrow.png')});
    await page.getByRole('button', {name:'Settings',exact:true}).click();
    await page.getByRole('tab', {name:'Appearance',exact:true}).click();
    await page.getByRole('radio', {name:'Dark',exact:true}).check();
    await page.getByLabel('Text size', {exact:true}).selectOption('extra-large');
    await page.getByRole('button', {name:'Library',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Test Fixture — Pixel Harbor',exact:true})).toBeVisible();
    await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).fontSize)).toBe('20px');
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('creator-profile-dark-large.png')});
    await page.getByRole('button', { name: 'Known works',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Forest Signal — First impressions',exact:true})).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('creator-known-works-dark-large.png')});
    await page.getByRole('button', {name:'Settings',exact:true}).click();
    await page.getByRole('button', {name:'Restore appearance defaults',exact:true}).click();
    await page.getByRole('button', {name:'Library',exact:true}).click();
    await page.getByRole('button', {name: 'Back to creators', exact: true}).click();
    await page.getByRole('tab', {name: 'Games', exact: true}).click();
    await expect(page.getByRole('button', {name: 'Open Test Fixture — Forest Signal', exact: true})).toBeVisible();
    await page.getByRole('button', {name: 'Open Test Fixture — Forest Signal', exact: true}).click();
    await expect(page.getByRole('heading',{name:'Test Fixture — Forest Signal',exact:true})).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('game-detail-narrow.png')});
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1320, 920));
    await page.screenshot({path:testInfo.outputPath('game-detail.png')});
    await page.getByRole('button',{name:'Back to games',exact:true}).click();
    await page.getByRole('button',{name:'Match',exact:true}).click();
    await expect(page.getByRole('button',{name:'New activity',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Outreach',exact:true}).click();
    await expect(page.getByRole('region',{name:'outreach page',exact:true}).getByText('Not connected yet',{exact:true})).toBeVisible();
    await page.getByRole('button', {name: 'Library', exact: true}).click();
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(760, 660));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('library-narrow.png')});
    const boundary = await page.evaluate(() => ({node: typeof (window as any).require, process: typeof (window as any).process, keyInDOM: document.body.innerText.includes('local-fixture-only-not-a-production-key'), methods: Object.keys(window.desktop).sort(), storage: localStorage.length}));
    expect(boundary).toEqual({node:'undefined',process:'undefined',keyInDOM:false,methods:['connection','creators','games','library','match','openExternal','preferences','settings','updates'],storage:0});
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
    await expect(page.getByRole('alert')).toContainText('The service could not complete this Creator request.');
    failCreators = false;
    await page.getByRole('button', {name:'Try again',exact:true}).click();
    await expect(page.getByRole('button', {name:'Open Test Fixture — Pixel Harbor',exact:true})).toBeVisible();
    expect(requests.every(request => request.method === 'GET')).toBe(true);
    expect(requests.some(request => request.path.startsWith('/api/v1/profiles/creators'))).toBe(false);
    expect(requests.some(request => request.path === `/api/v2/library/creators/${creatorId}`)).toBe(true);
    expect(requests.some(request => request.path === `/api/v2/library/creators/${creatorId}/works` && new URLSearchParams(request.query).get('limit') === '50')).toBe(true);
    expect(requests.filter(request => request.path === '/api/v2/library/creators').every(request => new URLSearchParams(request.query).get('limit') === '50' && new URLSearchParams(request.query).get('offset') === '0')).toBe(true);
  } finally {
    await app?.close();
    await new Promise<void>(resolve => server.close(() => resolve()));
    await rm(userData, {recursive:true,force:true});
  }
});
