import {test,expect,_electron as electron,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {isolatedPreferences} from './preferences';

test.use({trace:'off',screenshot:'off',video:'off'});
test('read-only current-task visual audit',async({},info)=>{
 test.skip(process.env.FMG_UIUX_AUDIT!=='18093','Exclusive synthetic fixture, read-only audit.');test.setTimeout(90000);
 const origin='http://127.0.0.1:18093';
 const config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin)throw Error('fixture_origin');
 const userData=await mkdtemp('/tmp/fmg-uiux-audit-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
 let app:ElectronApplication|undefined;
 try{
  app=await electron.launch({args:['.',`--user-data-dir=${userData}`],cwd:process.cwd(),env,chromiumSandbox:true});const page=await app.firstWindow();page.setDefaultTimeout(10000);
  await app.evaluate(({session,BrowserWindow},origin)=>{
   BrowserWindow.getAllWindows()[0].setSize(1440,1000);(globalThis as any).__auditWrites=[];
   for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
    if(!/^https?:/.test(details.url)){callback({cancel:false});return;}
    const url=new URL(details.url),write=details.method!=='GET';if(write)(globalThis as any).__auditWrites.push(details.method+' '+url.pathname);
    const failDetail=(globalThis as any).__failInvitationDetail&&/\/activities\/[^/]+\/invitations\/[^/]+$/.test(url.pathname);
    callback({cancel:write||url.origin!==origin||Boolean(failDetail)});
   });
  },origin);
  await page.emulateMedia({reducedMotion:'reduce'});let errors=0;page.on('pageerror',()=>errors++);
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);
  try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();await expect(page.getByLabel('Workspace key',{exact:true})).toHaveValue('');
  const shots:Record<string,unknown>[]=[];
  async function shot(name:string){await page.screenshot({path:info.outputPath(name+'.png')});shots.push({name,headings:await page.getByRole('heading').allTextContents(),buttons:await page.getByRole('button').allTextContents(),tabs:await page.getByRole('tab').allTextContents(),overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)});}
  await page.getByRole('button',{name:'Library',exact:true}).click();await expect(page.getByRole('table',{name:'Creators',exact:true}).getByRole('button').first()).toBeVisible();await shot('library');
  await page.getByRole('table',{name:'Creators',exact:true}).getByRole('button').first().click();await expect(page.getByRole('article').filter({has:page.getByRole('button',{name:'Back to creators',exact:true})})).toBeVisible();await shot('creator');
  const emails=page.getByRole('button',{name:'Emails',exact:true});await emails.focus();await emails.press('Enter');await expect(emails).toHaveAttribute('aria-expanded','true');await emails.press('Enter');
  const works=page.getByRole('button',{name:'Known works',exact:true});await works.focus();await works.press('Space');await expect(works).toHaveAttribute('aria-expanded','true');await expect(page.locator('.creator-work-list > li')).toHaveCount(1);await shot('creator-works');
  await page.getByRole('button',{name:'Match',exact:true}).click();await expect(page.getByRole('list',{name:'Activities',exact:true}).getByRole('button').first()).toBeVisible();await shot('match-list');
  await page.getByRole('list',{name:'Activities',exact:true}).getByRole('button').first().click();await expect(page.getByRole('region',{name:'Creator matches',exact:true}).locator('tbody > tr')).toHaveCount(6);await shot('match-results');
  await page.getByRole('region',{name:'Creator matches',exact:true}).getByRole('button',{name:/^View Synthetic/}).first().click();await expect(page.getByRole('button',{name:'Edit profile',exact:true})).toBeVisible();await shot('match-creator');
  await page.getByRole('button',{name:'Outreach',exact:true}).click();await expect(page.getByRole('table',{name:'Invitation relationships',exact:true}).getByRole('button').first()).toBeVisible();await shot('outreach-activity');
  const roster=page.getByRole('table',{name:'Invitation relationships'}),current=page.getByRole('region',{name:'Current invitation'});
  await expect(current).toHaveCount(0);
  const secondInvitation=roster.getByRole('button',{name:/^Update relationship/}).nth(1);await secondInvitation.focus();await secondInvitation.press('Enter');await expect(secondInvitation).toHaveAttribute('aria-expanded','true');await expect(current.getByRole('button',{name:'Edit progress',exact:true})).toBeEnabled();
  await current.getByRole('button',{name:'Edit progress',exact:true}).click();const notes=current.getByRole('textbox',{name:'Notes',exact:true}),priorNotes=await notes.inputValue();await notes.fill(priorNotes+' Local unsaved audit');await shot('outreach-editing');
  await test.step('Creator detour preserves invitation notes',async()=>{
   await current.getByRole('button',{name:'Open creator',exact:true}).click();
   await expect(page.getByRole('tab',{name:'Invitations',exact:true})).toHaveAttribute('aria-selected','true');
   await shot('outreach-creator-detour');
   await page.getByRole('button',{name:'Back to activity',exact:true}).click();
   await expect(notes).toBeEnabled();await expect(notes).toHaveValue(priorNotes+' Local unsaved audit');
   await shot('outreach-return-editing');
   await current.getByRole('button',{name:'Cancel',exact:true}).click();
  });
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(760,920));await shot('outreach-narrow');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await app.evaluate(()=>(globalThis as any).__failInvitationDetail=true);await secondInvitation.click();await expect(current.getByRole('button',{name:'Edit progress',exact:true})).toBeDisabled();await expect(page.getByRole('alert')).toBeVisible();await shot('outreach-read-failure-narrow');
  await app.evaluate(()=>(globalThis as any).__failInvitationDetail=false);await page.getByRole('button',{name:'Refresh invitations',exact:true}).click();await expect(current.getByRole('button',{name:'Edit progress',exact:true})).toBeEnabled();await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByRole('combobox',{name:'Response',exact:true}).selectOption('accepted');await expect(page.getByText('No matching invitations',{exact:true})).toBeVisible();await expect(current.getByRole('button',{name:'Edit progress',exact:true})).toBeEnabled();await shot('outreach-empty-filter-narrow');
  await page.getByRole('combobox',{name:'Response',exact:true}).selectOption('');await expect(roster.getByRole('button',{name:/^Update relationship/})).toHaveCount(6);
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1440,1000));
  await page.getByRole('button',{name:'Activities',exact:true}).click();await expect(page.getByRole('heading',{name:'Outreach',exact:true})).toBeVisible();await shot('outreach');
  await page.getByRole('button',{name:'Settings',exact:true}).click();await expect(page.getByRole('tab',{name:'Workspace',exact:true})).toBeVisible();await shot('settings');
  await page.getByRole('tab',{name:'Workspace',exact:true}).focus();await page.getByRole('tab',{name:'Workspace',exact:true}).press('ArrowDown');await expect(page.getByRole('tab',{name:'Services',exact:true})).toHaveAttribute('aria-selected','true');await expect(page.getByRole('button',{name:'Replace YouTube credential',exact:true})).toBeEnabled();await shot('settings-services');
  await page.getByRole('button',{name:'Replace YouTube credential',exact:true}).click();await expect(page.getByLabel('YouTube replacement credential',{exact:true})).toBeVisible();await shot('settings-service-editor');await page.getByRole('button',{name:'Replace YouTube credential',exact:true}).click();
  await page.getByRole('tab',{name:'Auto-refresh',exact:true}).click();const interval=page.getByRole('spinbutton',{name:'Games interval (days)',exact:true});await expect(interval).toBeEnabled();const originalInterval=await interval.inputValue(),draftInterval=String(Number(originalInterval)===90?89:Number(originalInterval)+1);await interval.fill(draftInterval);
  await page.getByRole('tab',{name:'Appearance',exact:true}).click();await page.getByRole('tab',{name:'Auto-refresh',exact:true}).click();await expect(interval).toHaveValue(draftInterval);
  await page.getByRole('button',{name:'Save intervals',exact:true}).click();const sharedConfirmation=page.getByRole('dialog',{name:'Confirm change',exact:true});await expect(sharedConfirmation).toContainText('everyone using this workspace');await shot('settings-shared-confirmation');await sharedConfirmation.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('button',{name:'Library',exact:true}).click();const settingsLeave=page.getByRole('dialog',{name:'Unsaved settings',exact:true});await expect(settingsLeave).toBeVisible();await shot('settings-unsaved-guard');await settingsLeave.getByRole('button',{name:'Keep editing',exact:true}).click();await expect(interval).toHaveValue(draftInterval);await interval.fill(originalInterval);await expect(page.getByRole('button',{name:'Save intervals',exact:true})).toBeDisabled();
  await page.getByRole('tab',{name:'Workspace',exact:true}).click();
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(760,920));await shot('settings-narrow');
  const categoriesBox=await page.getByRole('tablist',{name:'Settings categories',exact:true}).boundingBox(),connectionBox=await page.getByRole('region',{name:'Workspace connection',exact:true}).boundingBox();expect(connectionBox!.x).toBeGreaterThan(categoriesBox!.x+categoriesBox!.width);expect(Math.abs(connectionBox!.y-categoriesBox!.y)).toBeLessThan(2);
  for(const category of ['Services','Collection','Auto-refresh','Email','Updates','Appearance']){
   await page.getByRole('tab',{name:category,exact:true}).click();await expect(page.getByRole('tab',{name:category,exact:true})).toHaveAttribute('aria-selected','true');
   if(category==='Services')await expect(page.getByRole('button',{name:'Replace YouTube credential',exact:true})).toBeEnabled();
   if(category==='Collection')await expect(page.getByRole('switch',{name:'Collect from YouTube',exact:true})).toBeVisible();
   if(category==='Auto-refresh')await expect(interval).toBeEnabled();
   if(category==='Email')await expect(page.getByLabel('SMTP host',{exact:true})).toBeEnabled();
   if(category==='Updates')await expect(page.getByRole('button',{name:'Check for updates',exact:true})).toBeEnabled();
   if(category==='Appearance')await expect(page.getByLabel('Text size',{exact:true})).toBeEnabled();
   await shot('settings-'+category.toLowerCase()+'-narrow');
  }
  await page.getByRole('button',{name:'Library',exact:true}).click();await expect(page.getByRole('button',{name:'Known works',exact:true})).toHaveAttribute('aria-expanded','true');await shot('creator-narrow');
  await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('tab',{name:'Appearance',exact:true}).click();await page.getByRole('radio',{name:'Dark',exact:true}).check();
  await expect(page.locator('html')).toHaveAttribute('data-theme','dark');await page.getByRole('button',{name:'Library',exact:true}).click();await shot('creator-dark-narrow');
  await page.getByRole('button',{name:'Back to creators',exact:true}).click();await expect(page.getByRole('heading',{name:'Library',exact:true})).toBeVisible();await shot('library-dark-narrow');
  await page.getByRole('button',{name:'Match',exact:true}).click();await expect(page.getByRole('heading',{name:'Match',exact:true})).toBeVisible();await shot('match-list-dark-narrow');
  await page.getByRole('list',{name:'Activities',exact:true}).getByRole('button').first().click();await expect(page.getByRole('region',{name:'Creator matches',exact:true}).locator('tbody > tr')).toHaveCount(6);await shot('match-results-dark-narrow');
  await expect(page.getByRole('button',{name:'Analysis tasks',exact:true})).toHaveCount(1);
  await page.getByRole('button',{name:'Outreach',exact:true}).click();await roster.getByRole('button',{name:/^Update relationship/}).first().click();await expect(current.getByRole('button',{name:'Edit progress',exact:true})).toBeEnabled();await shot('outreach-dark-narrow');
  await page.getByRole('button',{name:'Settings',exact:true}).click();await page.getByRole('tab',{name:'Services',exact:true}).click();await shot('settings-services-dark-narrow');
  await page.getByRole('tab',{name:'Appearance',exact:true}).click();await page.getByLabel('Text size',{exact:true}).selectOption('extra-large');await expect(page.locator('html')).toHaveCSS('font-size','20px');await page.getByRole('tab',{name:'Services',exact:true}).click();await shot('settings-services-large-text');
  await page.getByRole('tab',{name:'Appearance',exact:true}).click();await page.getByLabel('Text size',{exact:true}).selectOption('default');
  const writes=await app.evaluate(()=>(globalThis as any).__auditWrites);expect(writes).toEqual([]);expect(errors).toBe(0);
  expect(shots.every(shot=>shot.overflow===false)).toBe(true);
  await writeFile(info.outputPath('audit.json'),JSON.stringify({native:true,readOnly:true,writes,errors,shots},null,2));
 }catch(error){app?.process().kill('SIGKILL');throw error;}finally{if(app&&!app.process().killed)await app.close();}
});
