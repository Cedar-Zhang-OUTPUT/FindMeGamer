import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { GameDetail, GamePage } from '../src/shared/games';

// Opt-in writes only to the coordinator-owned isolated API. No production key,
// mail, provider tasks, trace, video or credential screenshots are permitted.
test.use({trace:'off',screenshot:'off',video:'off'});
test('Game v2 persists edits, deduplicates retries, resolves conflicts and repairs authentication without replay', async () => {
  test.setTimeout(120_000);
  const file = process.env.FMG_BACKEND_FIXTURE_FILE;
  test.skip(!file, 'Requires the authorized isolated Game v2 API.');
  if (!file) return;
  expect((await stat(file)).mode & 0o077).toBe(0);
  const fixture = JSON.parse(await readFile(file,'utf8')) as {base_url:string;workspace_key:string};
  expect(new URL(fixture.base_url).origin).toBe('http://127.0.0.1:18090');
  const api = async <T,>(route:string, method = 'GET', data?: unknown): Promise<T> => {
    const response = await fetch(`${fixture.base_url}${route}`, {method,headers:{Authorization:`Bearer ${fixture.workspace_key}`,'Content-Type':'application/json'},...(data ? {body:JSON.stringify(data)} : {})});
    if (!response.ok) throw Error(`Isolated API check failed (HTTP ${response.status}).`);
    return response.json() as Promise<T>;
  };
  let dropFirstCreate = true;
  let recoveryFault: 'idle' | 'commit-then-drop' | 'reject-retry' = 'idle';
  let recoveryCommittedCreates = 0;
  let recoveryRejectedRetries = 0;
  let repairStarted = false;
  let createPostsAfterRepair = 0;
  let verifiedSessions = 0;
  let relayFailures = 0;
  const expectedHttpFailures = new Set<number>();
  const createAttempts: {key:string;body:string}[] = [];
  // A test-only loopback relay replaces one successful POST response with 502, after the real
  // database has committed. The second identical request must not create a duplicate.
  const relay = createServer(async (request,response) => {
    const route = new URL(request.url!, 'http://localhost');
    if (!/^\/api\/(v1\/(session|profiles\/creators(?:\/[0-9a-f-]+)?)|v2\/library\/games(?:\/[0-9a-f-]+)?)$/.test(route.pathname)) { response.writeHead(404).end(); return; }
    try {
      const chunks:Buffer[] = []; for await (const chunk of request) chunks.push(Buffer.from(chunk));
      const body = Buffer.concat(chunks).toString('utf8');
      const headers: Record<string,string> = {Authorization:request.headers.authorization ?? '', 'Content-Type':'application/json'};
      if (typeof request.headers['idempotency-key'] === 'string') headers['Idempotency-Key'] = request.headers['idempotency-key'];
      const creating = request.method === 'POST' && route.pathname === '/api/v2/library/games';
      if (creating) {
        createAttempts.push({key:headers['Idempotency-Key'],body});
        if (repairStarted) createPostsAfterRepair++;
        // Reject the recovery retry before it reaches the API. The original request
        // has already committed, so this 401 cannot settle its unknown outcome.
        if (recoveryFault === 'reject-retry') {
          recoveryRejectedRetries++;
          expectedHttpFailures.add(401);
          response.writeHead(401,{'Content-Type':'application/json'}).end('{}');
          return;
        }
      }
      const upstream = await fetch(`${fixture.base_url}${route.pathname}${route.search}`, {method:request.method,headers,...(body ? {body} : {})});
      const output = await upstream.text();
      if (route.pathname === '/api/v1/session' && upstream.ok) verifiedSessions++;
      if (request.method === 'PATCH' && upstream.status === 409) expectedHttpFailures.add(409);
      if (creating && upstream.status === 201) {
        if (dropFirstCreate) {
          dropFirstCreate=false; expectedHttpFailures.add(502);
          response.writeHead(502,{'Content-Type':'application/json'}).end('{}'); return;
        }
        if (recoveryFault === 'commit-then-drop') {
          recoveryCommittedCreates++; recoveryFault='reject-retry'; expectedHttpFailures.add(502);
          response.writeHead(502,{'Content-Type':'application/json'}).end('{}'); return;
        }
      }
      response.writeHead(upstream.status, {'Content-Type':'application/json'}).end(output);
    } catch { relayFailures++; response.writeHead(502).end('{}'); }
  });
  await new Promise<void>(resolve => relay.listen(0,'127.0.0.1',resolve));
  const port = (relay.address() as {port:number}).port;
  const relayOrigin = `http://127.0.0.1:${port}`;
  const userData = await mkdtemp(path.join(tmpdir(),'fmg-game-v2-e2e-'));
  const suffix = randomUUID().slice(0,8);
  const name = `Desktop Test ${suffix}`;
  let app: ElectronApplication | undefined;
  try {
    const env = Object.fromEntries(Object.entries(process.env).filter(([key,value]) => value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
    const executablePath = process.env.FMG_PACKAGED_EXECUTABLE;
    app = await electron.launch({args:[...(executablePath ? [] : ['.']),`--user-data-dir=${userData}`],...(executablePath ? {executablePath} : {}),cwd:process.cwd(),env,chromiumSandbox:true});
    const page = await app.firstWindow();
    // Keep diagnostic counts only: console text and exception messages can contain
    // credentials. Known injected HTTP failures are not renderer regressions.
    const diagnostics = {pageErrors:0,unexpectedConsoleMessages:0,expectedTransportErrors:0};
    page.on('pageerror', () => diagnostics.pageErrors++);
    page.on('console', message => {
      if (message.type() !== 'error' && message.type() !== 'warning') return;
      const failure = /^Failed to load resource: the server responded with a status of (401|409|502)\b/.exec(message.text());
      if (failure && expectedHttpFailures.has(Number(failure[1])) && message.location().url.startsWith(`${relayOrigin}/api/`)) diagnostics.expectedTransportErrors++;
      else diagnostics.unexpectedConsoleMessages++;
    });
    await page.emulateMedia({reducedMotion:'reduce'});
    await expect(page).toHaveURL('fmg://app/index.html');
    await expect(page).toHaveTitle('FindMeGamer');
    await expect(page.getByRole('heading',{name:'Library',exact:true})).toBeVisible();
    await expect(page.locator('vite-error-overlay, webpack-dev-server-client-overlay')).toHaveCount(0);
    await page.getByRole('button',{name:'Open Settings',exact:true}).click();
    await page.getByLabel('Service URL').fill(relayOrigin);
    const key = page.getByLabel('Workspace key',{exact:true});
    try { await key.fill(fixture.workspace_key); } catch { throw Error('Test credential entry failed; sensitive details suppressed.'); }
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
    expect(await key.inputValue() === '').toBe(true);
    await page.getByRole('button',{name:'Library',exact:true}).click();
    await expect(page.getByRole('button',{name:'Open Fixture Cozy Gamer',exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'Games',exact:true}).click();
    await page.getByRole('button',{name:'New game',exact:true}).click();
    await page.getByRole('textbox',{name:'Name',exact:true}).fill(name);
    await page.getByRole('button',{name:'Create game',exact:true}).click();
    await expect(page.getByRole('button',{name:'Retry creation',exact:true})).toBeVisible();
    await expect(page.getByRole('textbox',{name:'Name',exact:true})).toBeDisabled();
    await page.getByRole('button',{name:'Retry creation',exact:true}).click();
    await expect(page.getByRole('heading',{name,exact:true})).toBeVisible();
    expect(createAttempts).toHaveLength(2);
    expect(createAttempts[1]).toEqual(createAttempts[0]);
    const list = await api<GamePage>(`/api/v2/library/games?query=${encodeURIComponent(name)}`);
    expect(list.items.filter(game => game.name === name)).toHaveLength(1);
    const created = list.items.find(game => game.name === name)!;
    expect(created.steam_app_id).toBeNull();
    expect(created.source_identity.steam_app_id).toBeNull();
    expect(created.last_analyzed_at).toBeNull();

    await page.getByRole('button',{name:'Edit game',exact:true}).click();
    await page.getByRole('textbox',{name:'Developer',exact:true}).fill('My studio');
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    const leave = page.getByRole('dialog',{name:'Unsaved game changes',exact:true});
    await expect(leave).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('textbox',{name:'Developer',exact:true})).toHaveValue('My studio');

    // An explicit second editor writes to the same disposable record to cause 409.
    const remote = await api<GameDetail>(`/api/v2/library/games/${created.id}`, 'PATCH', {expected_revision:created.revision,developer:'Other studio',description:'New remote description'});
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Resolve changes',exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'Apply choices',exact:true})).toBeDisabled();
    await page.getByRole('radio',{name:'Keep mine: Developer',exact:true}).check();
    await page.getByRole('button',{name:'Apply choices',exact:true}).click();
    await expect(page.getByRole('textbox',{name:'Description',exact:true})).toHaveValue('New remote description');
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('button',{name:'Edit game',exact:true})).toBeVisible();
    const saved = await api<GameDetail>(`/api/v2/library/games/${created.id}`);
    expect(saved.revision).toBeGreaterThan(remote.revision);
    expect(saved.developer).toBe('My studio');
    expect(saved.description).toBe('New remote description');

    await page.getByRole('button',{name:'Edit game',exact:true}).click();
    await page.getByRole('textbox',{name:'Developer',exact:true}).fill('');
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('button',{name:'Edit game',exact:true})).toBeVisible();
    expect((await api<GameDetail>(`/api/v2/library/games/${created.id}`)).developer).toBeNull();
    await page.getByRole('button',{name:'Edit game',exact:true}).click();
    await page.getByText('Source comparison',{exact:true}).click();
    await page.getByRole('button',{name:'Use source Developer',exact:true}).click();
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('button',{name:'Edit game',exact:true})).toBeVisible();
    const restored = await api<GameDetail>(`/api/v2/library/games/${created.id}`);
    expect(restored.overridden_fields).not.toContain('developer');
    expect(restored.manual_overrides).not.toHaveProperty('developer');

    await page.getByRole('button',{name:'Edit game',exact:true}).click();
    await page.getByRole('checkbox',{name:'Saved',exact:true}).check();
    const referenceName = `Beacon ${suffix}`;
    for (const [index, reference] of [referenceName,referenceName.toLowerCase()].entries()) {
      await page.getByRole('button',{name:'Add reference',exact:true}).click();
      const group = page.getByRole('group',{name:`Reference ${index+1}`,exact:true});
      await group.getByRole('textbox',{name:'Reference name',exact:true}).fill(reference);
      await group.getByRole('textbox',{name:'Reason',exact:true}).fill('Atmosphere');
      await group.getByRole('textbox',{name:'Similarities',exact:true}).fill('Mood');
    }
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('button',{name:'Edit game',exact:true})).toBeVisible();
    const withReferences = await api<GameDetail>(`/api/v2/library/games/${created.id}`);
    expect(withReferences.favorite).toBe(true);
    expect(withReferences.reference_works).toHaveLength(1);
    const reference = withReferences.reference_works[0];
    expect(reference.id).toMatch(/^[0-9a-f-]{36}$/);
    await page.getByRole('button',{name:'Edit game',exact:true}).click();
    await page.getByRole('button',{name:`Edit reference ${reference.name}`,exact:true}).click();
    await page.getByRole('group',{name:'Reference 1',exact:true}).getByRole('textbox',{name:'Reason',exact:true}).fill('Updated comparison');
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('button',{name:'Edit game',exact:true})).toBeVisible();
    const editedReferences = await api<GameDetail>(`/api/v2/library/games/${created.id}`);
    expect(editedReferences.reference_works[0]).toMatchObject({id:reference.id,reason:'Updated comparison',similarities:['Mood']});
    await app.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].setSize(1320,920));
    await expect(page.getByRole('heading',{name,exact:true})).toBeVisible();
    await expect(page.getByText('Updated comparison',{exact:true})).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // Screenshots contain disposable fixture records only, never credential entry.
    await page.screenshot({path:'/tmp/fmg-game-v2-wide-detail.png'});
    await page.getByRole('button',{name:'Edit game',exact:true}).click();
    await page.getByRole('button',{name:`Remove reference ${reference.name}`,exact:true}).click();
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('button',{name:'Edit game',exact:true})).toBeVisible();
    expect((await api<GameDetail>(`/api/v2/library/games/${created.id}`)).reference_works).toEqual([]);
    await page.getByRole('button',{name:'Back to games',exact:true}).click();
    await page.getByRole('searchbox',{name:'Search games',exact:true}).fill(name);
    await page.getByRole('searchbox',{name:'Search games',exact:true}).press('Enter');
    await expect(page.getByRole('button',{name:`Open ${name}`,exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'Creators',exact:true}).click();
    await expect(page.getByRole('button',{name:'Open Fixture Cozy Gamer',exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'Games',exact:true}).click();
    await expect(page.getByRole('searchbox',{name:'Search games',exact:true})).toHaveValue(name);

    // A separate disposable creation exercises credential repair after a committed
    // response is lost. Re-entering even the same key conservatively forbids replay.
    const recoveryName = `Desktop Recovery ${suffix}`;
    const attemptsBeforeRecovery = createAttempts.length;
    await page.getByRole('button',{name:'New game',exact:true}).click();
    await page.getByRole('textbox',{name:'Name',exact:true}).fill(recoveryName);
    await page.getByRole('textbox',{name:'Developer',exact:true}).fill('Recovery fixture studio');
    await page.getByRole('textbox',{name:'Description',exact:true}).fill('Retain this draft during workspace key repair.');
    await app.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].setSize(760,900));
    await expect(page.getByRole('heading',{name:'New game',exact:true})).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({path:'/tmp/fmg-game-v2-narrow-editor.png'});
    await app.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].setSize(1320,920));
    recoveryFault = 'commit-then-drop';
    await page.getByRole('button',{name:'Create game',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Creation result unknown',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Retry creation',exact:true}).click();
    await expect(page.getByRole('alert')).toContainText('The workspace key was not accepted. Update it in Settings.');
    await expect(page.getByRole('textbox',{name:'Name',exact:true})).toHaveValue(recoveryName);
    await expect(page.getByRole('textbox',{name:'Name',exact:true})).toBeDisabled();
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Settings',exact:true})).toBeVisible();
    await expect(page.getByRole('dialog',{name:'Unsaved game changes',exact:true})).toHaveCount(0);
    await expect(page.getByLabel('Service URL')).toHaveValue(relayOrigin);
    await expect(page.getByLabel('Service URL')).toBeDisabled();
    await expect(page.getByRole('button',{name:'Disconnect',exact:true})).toBeDisabled();
    await expect(key).toBeEnabled();
    try { await key.fill(fixture.workspace_key); } catch { throw Error('Test credential repair failed; sensitive details suppressed.'); }
    const sessionsBeforeRepair = verifiedSessions;
    repairStarted = true;
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await expect.poll(() => verifiedSessions).toBe(sessionsBeforeRepair + 1);
    await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
    expect(await key.inputValue() === '').toBe(true);
    await page.getByRole('button',{name:'Open Library',exact:true}).click();
    await expect(page.getByRole('heading',{name:'New game',exact:true})).toBeVisible();
    await expect(page.getByRole('textbox',{name:'Name',exact:true})).toHaveValue(recoveryName);
    await expect(page.getByRole('textbox',{name:'Developer',exact:true})).toHaveValue('Recovery fixture studio');
    await expect(page.getByRole('textbox',{name:'Description',exact:true})).toHaveValue('Retain this draft during workspace key repair.');
    await expect(page.getByRole('button',{name:'Retry creation',exact:true})).toBeDisabled();
    await expect(page.getByRole('button',{name:'Create game',exact:true})).toBeDisabled();
    await expect(page.getByRole('button',{name:'Check Library',exact:true})).toBeEnabled();
    await page.getByRole('button',{name:'Check Library',exact:true}).click();
    const recoveryList = await api<GamePage>(`/api/v2/library/games?query=${encodeURIComponent(recoveryName)}`);
    expect(recoveryList.items.filter(game => game.name === recoveryName)).toHaveLength(1);
    const recoveryGame = recoveryList.items.find(game => game.name === recoveryName)!;
    const recoveredRecord = page.locator('.game-creation-lookup > div').filter({has:page.getByText(recoveryName,{exact:true})});
    await expect(recoveredRecord.getByText(recoveryGame.id,{exact:true})).toBeVisible();
    await recoveredRecord.getByRole('button',{name:'Use this record',exact:true}).click();
    await expect(page.getByRole('heading',{name:recoveryName,exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:'Edit game',exact:true})).toBeVisible();
    await expect(page.locator('.game-description-text')).toHaveText('Retain this draft during workspace key repair.');
    const recovered = await api<GameDetail>(`/api/v2/library/games/${recoveryGame.id}`);
    expect(recovered).toMatchObject({id:recoveryGame.id,name:recoveryName,developer:'Recovery fixture studio'});
    const finalRecoveryList = await api<GamePage>(`/api/v2/library/games?query=${encodeURIComponent(recoveryName)}`);
    expect(finalRecoveryList.items.filter(game => game.name === recoveryName)).toHaveLength(1);
    const recoveryAttempts = createAttempts.slice(attemptsBeforeRecovery);
    expect(recoveryAttempts).toHaveLength(2);
    expect(recoveryAttempts[1]).toEqual(recoveryAttempts[0]);
    expect(recoveryAttempts[0].key).not.toBe(createAttempts[0].key);
    expect(recoveryCommittedCreates).toBe(1);
    expect(recoveryRejectedRetries).toBe(1);
    expect(createPostsAfterRepair).toBe(0);
    expect(relayFailures).toBe(0);
    await expect(page).toHaveURL('fmg://app/index.html');
    await expect(page).toHaveTitle('FindMeGamer');
    await expect(page.locator('vite-error-overlay, webpack-dev-server-client-overlay')).toHaveCount(0);
    expect({pageErrors:diagnostics.pageErrors,unexpectedConsoleMessages:diagnostics.unexpectedConsoleMessages}).toEqual({pageErrors:0,unexpectedConsoleMessages:0});
  } finally {
    // Failed tests may have a disposable draft. Destroy only this test window
    // before closing its process; do not grant or dismiss OS security prompts.
    if (app) { await app.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows().forEach(window => window.destroy())); await app.close(); }
    await new Promise<void>(resolve => relay.close(() => resolve()));
    await rm(userData,{recursive:true,force:true});
  }
});
