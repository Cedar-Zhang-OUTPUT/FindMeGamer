import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { isolatedPreferences } from './preferences';

// Optional coordinator-provided isolated API, never a production credential import.
// No trace/video/screenshot: the key is a test secret even though this DB is synthetic.
test.use({trace:'off', screenshot:'off', video:'off'});
test('isolated backend through the real desktop Settings and Library', async () => {
  const file = process.env.FMG_BACKEND_FIXTURE_FILE;
  test.skip(!file, 'Set FMG_BACKEND_FIXTURE_FILE to the authorized isolated test credential file.');
  if (!file) return;
  expect((await stat(file)).mode & 0o077).toBe(0);
  const fixture = JSON.parse(await readFile(file, 'utf8')) as {base_url:string;workspace_key:string};
  expect(new URL(fixture.base_url).hostname).toBe('127.0.0.1');
  const userData = await mkdtemp(path.join(tmpdir(), 'fmg-backend-e2e-'));
  await isolatedPreferences(userData);
  let app: ElectronApplication | undefined;
  try {
    const env = Object.fromEntries(Object.entries(process.env).filter(([name, value]) => value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(name))) as Record<string,string>;
    const executablePath = process.env.FMG_PACKAGED_EXECUTABLE;
    app = await electron.launch({args:[...(executablePath ? [] : ['.']),`--user-data-dir=${userData}`],...(executablePath ? {executablePath} : {}),cwd:process.cwd(),env,chromiumSandbox:true});
    const page = await app.firstWindow();
    if (executablePath) {
      expect(await app.evaluate(({app}) => ({packaged:app.isPackaged,path:app.getAppPath()}))).toMatchObject({packaged:true,path:expect.stringContaining('app.asar')});
    }
    await page.getByRole('button',{name:'Open Settings',exact:true}).click();
    await page.getByLabel('Service URL').fill(fixture.base_url);
    const keyInput = page.getByLabel('Workspace key',{exact:true});
    await expect(keyInput).toBeEditable();
    try { await keyInput.fill(fixture.workspace_key); }
    catch { throw Error('Could not enter the test credential; sensitive action details are suppressed.'); }
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
    await expect(keyInput).toHaveValue('');
    await page.getByRole('button',{name:'Library',exact:true}).click();
    await expect(page.getByRole('button',{name:'Open Fixture Cozy Gamer',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Open Fixture Cozy Gamer',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Fixture Cozy Gamer',exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'Emails',exact:true}).click();
    await expect(page.getByText('fixture@example.com',{exact:true}).first()).toBeVisible();
    await page.getByRole('button',{name:'Back to creators',exact:true}).click();
    await page.getByRole('tab',{name:'Games',exact:true}).click();
    await page.getByRole('button',{name:'Open Fixture Star Garden',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Fixture Star Garden',exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.getByRole('button',{name:'Test connection',exact:true}).click();
    await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Library',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Fixture Star Garden',exact:true})).toBeVisible();
    const stored = await readFile(path.join(userData,'credentials.json'),'utf8');
    expect(stored.includes(fixture.workspace_key)).toBe(false);
    const visuals = await page.evaluate(async () => {
      const paths = ['./assets/seaside-sunset.png','./assets/sidebar-night.png','./assets/fox-mark.svg'];
      const loaded = await Promise.all(paths.map(src => new Promise<boolean>(resolve => {const image = new Image(); image.onload=()=>resolve(image.naturalWidth>0); image.onerror=()=>resolve(false); image.src=src;})));
      return {loaded,preload:typeof window.desktop?.connection?.status,url:location.href};
    });
    expect(visuals).toEqual({loaded:[true,true,true],preload:'function',url:'fmg://app/index.html'});
  } finally {
    await app?.close();
    await rm(userData,{recursive:true,force:true});
  }
});
