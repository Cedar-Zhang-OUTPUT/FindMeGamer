import {launchElectronTarget,electronTargetEvidence} from './electron-target';
import {test,expect,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {isolatedPreferences} from './preferences';
test.use({trace:'off',screenshot:'off',video:'off'});
test('PRD P4 P9 P12 tables preserve direct actions in native Electron',async({},info)=>{
 test.skip(process.env.FMG_TABLES_NATIVE!=='18093','Requires exclusive read-only synthetic fixture.');test.setTimeout(90000);
 const origin='http://127.0.0.1:18093',config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin)throw Error('fixture_origin');const userData=await mkdtemp('/tmp/fmg-table-audit-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;let app:ElectronApplication|undefined;
 try{
  app=await launchElectronTarget(userData,env);const target=await electronTargetEvidence(app);const page=await app.firstWindow();page.setDefaultTimeout(12000);
  await app.evaluate(({session,BrowserWindow},origin)=>{BrowserWindow.getAllWindows()[0].setSize(1440,1000);(globalThis as any).__tableWrites=[];for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
   if(!/^https?:/.test(details.url)){callback({cancel:false});return;}const write=details.method!=='GET';if(write)(globalThis as any).__tableWrites.push(details.method+' '+new URL(details.url).pathname);callback({cancel:write||new URL(details.url).origin!==origin});
  });},origin);
  let errors=0;page.on('pageerror',()=>errors++);await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
  const shots:string[]=[];
  async function shot(name:string){expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:info.outputPath(name+'.png')});shots.push(name);}
  async function narrow(name:string){await app!.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(760,920));await shot(name+'-narrow');await app!.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1440,1000));}
  await page.getByRole('button',{name:'Library',exact:true}).click();const creators=page.getByRole('table',{name:'Creators',exact:true});await expect(creators).toBeVisible();await shot('P12.1-creators');await narrow('P12.1-creators');
  await creators.getByRole('button',{name:/^Edit /}).first().click();await expect(page.getByRole('button',{name:'Save changes',exact:true})).toBeVisible();await page.getByRole('button',{name:'Cancel',exact:true}).click();await expect(creators).toBeVisible();
  await creators.getByRole('button',{name:/^View works for/}).first().click();await expect(page.getByRole('button',{name:'Known works',exact:true})).toHaveAttribute('aria-expanded','true');await page.getByRole('button',{name:'Back to creators',exact:true}).click();
  await page.getByRole('tab',{name:'Games',exact:true}).click();const games=page.getByRole('table',{name:'Games',exact:true});await expect(games).toBeVisible();await shot('P12.2-games');await narrow('P12.2-games');
  await games.getByRole('button',{name:/^Edit /}).first().click();await expect(page.getByRole('button',{name:'Save changes',exact:true})).toBeVisible();await page.getByRole('button',{name:'Cancel',exact:true}).click();await expect(games).toBeVisible();
  await games.getByRole('button',{name:/^Use .* for Match$/}).first().click();await expect(page.getByRole('button',{name:'Continue to matching',exact:true})).toBeVisible();await page.getByRole('button',{name:'Cancel',exact:true}).click();await page.getByRole('button',{name:'Activities',exact:true}).click();await page.getByRole('dialog',{name:'Unsaved Match changes',exact:true}).getByRole('button',{name:'Discard changes',exact:true}).click();
  await page.getByRole('button',{name:'Match',exact:true}).click();await page.getByRole('list',{name:'Activities',exact:true}).getByRole('button').first().click();const matches=page.getByRole('table',{name:'Creator matches',exact:true});await expect(matches.locator('tbody > tr')).toHaveCount(6);await expect(matches.getByRole('checkbox').first()).toBeEnabled();await shot('P4-matches');await narrow('P4-matches');
  await matches.locator('summary').first().focus();await matches.locator('summary').first().press('Enter');await expect(matches.locator('details').first()).toHaveAttribute('open','');await matches.locator('summary').first().press('Enter');
  await page.getByRole('button',{name:'Outreach',exact:true}).click();const invitations=page.getByRole('table',{name:'Invitation relationships'});await expect(invitations.locator('tbody > tr')).toHaveCount(6);await expect(page.getByRole('button',{name:'Refresh invitations',exact:true})).toBeEnabled();await expect(page.getByRole('region',{name:'Current invitation'})).toHaveCount(0);await shot('P9-invitations');await narrow('P9-invitations');
  await invitations.getByRole('rowheader').first().getByRole('button').click();await expect(page.getByRole('tab',{name:'Invitations',exact:true})).toHaveAttribute('aria-selected','true');await page.getByRole('button',{name:'Back to activity',exact:true}).click();
  const update=invitations.getByRole('button',{name:/^Update relationship/}).first();await update.focus();await update.press('Enter');const editor=page.getByRole('region',{name:'Current invitation'});await expect(editor).toBeFocused();await expect(editor.getByRole('button',{name:'Edit progress',exact:true})).toBeEnabled();
  await editor.getByRole('button',{name:'Edit progress',exact:true}).click();const notes=editor.getByRole('textbox',{name:'Notes',exact:true});const original=await notes.inputValue();await notes.fill(original+' Local unsaved table audit');await expect(page.getByRole('button',{name:'Close relationship'})).toBeDisabled();
  await editor.getByRole('button',{name:'Open creator',exact:true}).click();await page.getByRole('button',{name:'Back to activity',exact:true}).click();await expect(notes).toHaveValue(original+' Local unsaved table audit');await expect(notes).toBeEnabled();await editor.getByRole('button',{name:'Cancel',exact:true}).click();await page.getByRole('button',{name:'Close relationship'}).click();await expect(update).toBeFocused();
  const writes=await app.evaluate(()=>(globalThis as any).__tableWrites);expect(writes).toEqual([]);expect(errors).toBe(0);await writeFile(info.outputPath('verification.json'),JSON.stringify({status:'passed',native:true,packaged:target.packaged,target,userData,shots,writes,pageErrors:errors},null,2));
 }catch(error){if(app){await app.firstWindow().then(page=>page.screenshot({path:info.outputPath('failure.png')})).catch(()=>{});}throw error;
 }finally{if(app){await app.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();}).catch(()=>{});await app.close();}}
});
