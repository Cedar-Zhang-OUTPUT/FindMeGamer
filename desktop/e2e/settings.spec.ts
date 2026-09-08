import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { isolatedPreferences } from './preferences';

test.use({trace:'off',screenshot:'off',video:'off'});
test('complete Settings against accepted API, closed provider fixtures and capture-only SMTP',async()=>{
  test.setTimeout(120_000);
  const file=process.env.FMG_BACKEND_FIXTURE_FILE;
  const capture=process.env.FMG_SETTINGS_CAPTURE_DIR;
  test.skip(!file||!capture,'Requires the authorized isolated Settings API and capture directory.');
  if(!file||!capture)return;
  expect((await stat(file)).mode&0o077).toBe(0);
  const fixture=JSON.parse(await readFile(file,'utf8')) as {base_url:string;workspace_key:string};
  expect(fixture.base_url).toBe('http://127.0.0.1:18090');
  const request=async(route:string)=>{
    const response=await fetch(fixture.base_url+route,{headers:{Authorization:`Bearer ${fixture.workspace_key}`}});
    if(!response.ok)throw Error(`Isolated Settings read failed (HTTP ${response.status}).`);
    return response.json();
  };
  const countMail=async()=>(await readdir(capture)).filter(name=>/^smtp-.*\.eml$/.test(name)).length;
  const before=await countMail();
  const userData=await mkdtemp(path.join(tmpdir(),'fmg-settings-e2e-'));await isolatedPreferences(userData);
  let app:ElectronApplication|undefined;
  try {
    const environment=Object.fromEntries(Object.entries(process.env).filter(([name,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(name))) as Record<string,string>;
    const executablePath=process.env.FMG_PACKAGED_EXECUTABLE;
    app=await electron.launch({args:[...(executablePath?[]:['.']),`--user-data-dir=${userData}`],...(executablePath?{executablePath}:{}),cwd:process.cwd(),env:environment,chromiumSandbox:true});
    const page=await app.firstWindow();page.setDefaultTimeout(12_000);let pageErrors=0;page.on('pageerror',()=>pageErrors++);
    // The public update URL remains fixed. Intercept only its separate test session;
    // no production override, workspace header, real download or external navigation.
    await app.evaluate(async({session,shell})=>{
      (globalThis as any).updateFixtureCalls=[];(globalThis as any).openedReleaseLinks=[];
      await session.fromPartition('updates-network').protocol.handle('https',request=>{
        (globalThis as any).updateFixtureCalls.push({url:request.url,authorization:request.headers.has('authorization'),cookie:request.headers.has('cookie')});
        if(request.url!=='https://44.233.174.193/updates/macos.json')return new Response('{}',{status:403});
        return new Response(JSON.stringify({schema_version:1,version:'9.9.9',release_page_url:'https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v9.9.9'}),{headers:{'Content-Type':'application/json'}});
      });
      shell.openExternal=async(url:string)=>{(globalThis as any).openedReleaseLinks.push(url);};
    });
    await page.getByRole('button',{name:'Open Settings',exact:true}).click();
    await page.getByLabel('Service URL').fill(fixture.base_url);
    try {await page.getByLabel('Workspace key',{exact:true}).fill(fixture.workspace_key);}catch{throw Error('Sensitive fixture input failed; details suppressed.');}
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
    await expect(page.getByLabel('Workspace key',{exact:true})).toHaveValue('');
    await page.getByRole('tab',{name:'Appearance',exact:true}).click();
    await page.getByRole('radio',{name:'Dark',exact:true}).check();
    await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
    await page.getByLabel('Text size').selectOption('extra-large');
    await expect.poll(()=>page.evaluate(()=>getComputedStyle(document.documentElement).fontSize)).toBe('20px');
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(720,740));
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:'/tmp/fmg-settings-appearance-dark-narrow.png'});
    await page.getByRole('button',{name:'Library',exact:true}).click();
    await page.getByRole('button',{name:'Open Fixture Cozy Gamer',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Fixture Cozy Gamer',exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'Emails',exact:true}).click();
    await expect(page.getByText('fixture@example.com',{exact:true}).first()).toBeVisible();
    await expect(page.getByText('Loading creator…',{exact:true})).not.toBeVisible();
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:'/tmp/fmg-settings-creator-dark-narrow.png'});
    await page.getByRole('button',{name:'Back to creators',exact:true}).click();
    await page.getByRole('tab',{name:'Games',exact:true}).click();
    await page.getByRole('button',{name:'Open Fixture Star Garden',exact:true}).click();
    await page.getByRole('button',{name:'Edit game',exact:true}).click();
    await expect(page.getByRole('textbox',{name:'Name',exact:true})).toHaveValue('Fixture Star Garden');
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:'/tmp/fmg-settings-game-dark-narrow.png'});
    await page.getByRole('button',{name:'Cancel',exact:true}).click();
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.getByRole('radio',{name:'System',exact:true}).check();
    await page.emulateMedia({colorScheme:'dark',reducedMotion:'reduce'});
    await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
    await page.emulateMedia({colorScheme:'light',reducedMotion:'reduce'});
    await expect(page.locator('html')).toHaveAttribute('data-theme','light');
    await page.getByRole('button',{name:'Restore appearance defaults'}).click();
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1320,920));

    await page.getByRole('tab',{name:'Services',exact:true}).click();
    const services=[['steam','Steam','synthetic-steam-key'],['youtube','YouTube','synthetic-youtube-key'],['deepseek','DeepSeek','synthetic-deepseek-key'],['google_ai','Google AI','synthetic-google-ai-key'],['x','X','synthetic-x-key']] as const;
    for(const [service,label,key] of services){
      const row=page.locator('.cloud-provider').filter({has:page.getByRole('heading',{name:label,exact:true})});
      await row.getByRole('button',{name:`Replace ${label} credential`,exact:true}).click();
      await row.getByLabel(`${label} replacement credential`).fill(key);
      await row.getByRole('button',{name:`Save ${label} credential`,exact:true}).click();
      await expect(page.getByRole('dialog',{name:'Confirm change'})).toContainText('everyone');
      await page.getByRole('button',{name:'Confirm',exact:true}).click();
      await expect(row.getByText('Configured',{exact:true})).toBeVisible();
      const saved=await request(`/api/v1/settings/connections/${service}`);
      expect(Object.keys(saved).sort()).toEqual(['configured','last_test_status','last_tested_at']);
      if(service==='steam'){await expect(row.getByText('Credential testing unavailable',{exact:true})).toBeVisible();continue;}
      await row.getByRole('button',{name:service==='x'?'Test usage access':`Test ${label}`,exact:true}).click();
      await expect(row.getByText('Last test: success',{exact:true})).toBeVisible();
    }
    const x=page.locator('.cloud-provider').filter({has:page.getByRole('heading',{name:'X',exact:true})});
    const xCaveat=x.getByText('Search & analysis not verified',{exact:true});
    await expect(xCaveat).toHaveCount(1);await expect(xCaveat).toBeHidden();
    const xScope=x.locator('summary').filter({hasText:/^X test scope$/});
    await xScope.focus();await xScope.press('Enter');
    await expect(xCaveat).toBeVisible();
    await expect(x.locator('details')).toContainText('Checks usage access only. Account balance and recent search access are not verified.');
    await x.getByRole('button',{name:'Replace X credential',exact:true}).click();
    await x.getByLabel('X replacement credential').fill('synthetic-rejected-key');
    await x.getByRole('button',{name:'Save X credential',exact:true}).click();await page.getByRole('button',{name:'Confirm',exact:true}).click();
    await x.getByRole('button',{name:'Test usage access',exact:true}).click();await expect(x.getByText('Last test: failure',{exact:true})).toBeVisible();
    await expect(xCaveat).toBeVisible();
    await expect(x.locator('details')).toContainText('Checks usage access only. Account balance and recent search access are not verified.');
    await page.screenshot({path:'/tmp/fmg-settings-services.png'});

    console.log('Settings: provider probes complete; checking intervals.');
    await page.getByRole('tab',{name:'Auto-refresh',exact:true}).click();
    const interval=page.getByLabel('Games interval (days)');const current=await interval.inputValue();const changed=current==='45'?'46':'45';
    await interval.fill(changed);await page.getByRole('tab',{name:'Appearance',exact:true}).click();await page.getByRole('tab',{name:'Auto-refresh',exact:true}).click();await expect(interval).toHaveValue(changed);
    await page.getByRole('tab',{name:'Workspace',exact:true}).click();await expect(page.getByRole('button',{name:'Disconnect',exact:true})).toBeDisabled();
    await page.getByRole('tab',{name:'Auto-refresh',exact:true}).click();await page.getByRole('button',{name:'Save intervals',exact:true}).click();await page.getByRole('button',{name:'Confirm',exact:true}).click();
    await expect(page.getByText('Intervals saved',{exact:true})).toBeVisible();expect((await request('/api/v1/settings/reanalysis')).game_interval_days).toBe(Number(changed));
    await page.getByText('Refresh activity',{exact:true}).click();
    const gameActivity=page.locator('.refresh-activity').getByRole('region',{name:'Steam-linked games',exact:true});
    await expect(gameActivity.getByRole('heading',{name:'Steam-linked games',exact:true})).toBeVisible();
    await expect(gameActivity.getByText('Loaded records',{exact:true})).toBeVisible();
    await expect(gameActivity.getByText('1 records',{exact:true})).toBeVisible();

    console.log('Settings: intervals saved; checking SMTP.');
    await page.getByRole('tab',{name:'Email',exact:true}).click();
    const edit=page.getByRole('button',{name:'Edit email settings',exact:true});if(await edit.isVisible())await edit.click();
    await page.getByLabel('SMTP host',{exact:true}).fill('smtp.integration.invalid');await page.getByLabel('Port',{exact:true}).fill('587');await page.getByRole('combobox',{name:'Encryption',exact:true}).selectOption('starttls');
    await page.getByLabel('Username email',{exact:true}).fill('sender@example.com');await page.getByLabel(/^(Password|Replacement password \(optional\))$/).fill('synthetic-smtp-integration-key');
    await page.getByLabel('From name',{exact:true}).fill('Settings Fixture');await page.getByLabel('Reply-To email',{exact:true}).fill('sender@example.com');
    await page.getByRole('button',{name:'Save email settings',exact:true}).click();await page.getByRole('button',{name:'Confirm',exact:true}).click();
    await expect(page.getByText('Email settings saved',{exact:true})).toBeVisible();expect(await countMail()).toBe(before);
    const smtp=await request('/api/v1/outreach/smtp');expect(smtp).toMatchObject({host:'smtp.integration.invalid',port:587,encryption:'starttls',username:'sender@example.com'});expect(smtp).not.toHaveProperty('password');
    await page.getByRole('button',{name:'Test connection',exact:true}).click();await expect(page.getByText('Connection test succeeded',{exact:true})).toBeVisible();expect(await countMail()).toBe(before);
    await page.getByRole('button',{name:'Send test email…',exact:true}).click();await page.getByLabel('Test recipient email',{exact:true}).fill('company@example.com');
    await page.getByRole('button',{name:'Send test email',exact:true}).click();await expect(page.getByRole('dialog',{name:'Confirm change'})).toContainText('company@example.com');
    await page.getByRole('button',{name:'Cancel',exact:true}).click();expect(await countMail()).toBe(before);
    await page.getByRole('button',{name:'Send test email',exact:true}).click();await page.getByRole('button',{name:'Confirm',exact:true}).click();await expect(page.getByText('Test email accepted',{exact:true})).toBeVisible();
    expect(await countMail()).toBe(before+1);
    await page.screenshot({path:'/tmp/fmg-settings-email.png'});

    await page.getByRole('tab',{name:'Updates',exact:true}).click();await page.getByRole('button',{name:'Check for updates',exact:true}).click();
    await expect(page.getByRole('button',{name:'Download 9.9.9',exact:true})).toBeVisible();await page.getByRole('button',{name:'Download 9.9.9',exact:true}).click();
    const updateEvidence=await app.evaluate(()=>({calls:(globalThis as any).updateFixtureCalls,links:(globalThis as any).openedReleaseLinks}));
    expect(updateEvidence.calls).toEqual([{url:'https://44.233.174.193/updates/macos.json',authorization:false,cookie:false}]);expect(updateEvidence.links).toEqual(['https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v9.9.9']);
    await page.getByRole('button',{name:'Library',exact:true}).click();await page.getByRole('tab',{name:'Creators',exact:true}).click();await expect(page.getByRole('button',{name:'Open Fixture Cozy Gamer',exact:true})).toBeVisible();
    await page.getByRole('tab',{name:'Games',exact:true}).click();await expect(page.getByRole('button',{name:'Open Fixture Star Garden',exact:true})).toBeVisible();
    const leaked=await page.evaluate(()=>({text:document.body.innerText,inputs:Array.from(document.querySelectorAll<HTMLInputElement>('input[type=password]')).map(input=>input.value)}));
    expect(leaked.text.includes(fixture.workspace_key)).toBe(false);expect(leaked.inputs.every(value=>value==='')).toBe(true);
    const local=await readFile(path.join(userData,'preferences.json'),'utf8');expect(local.includes(fixture.workspace_key)).toBe(false);expect(local).not.toContain('synthetic-smtp-integration-key');expect(pageErrors).toBe(0);
  } finally {if(app){await app.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();}).catch(()=>{});await app.close().catch(()=>{});}await rm(userData,{recursive:true,force:true});}
});
