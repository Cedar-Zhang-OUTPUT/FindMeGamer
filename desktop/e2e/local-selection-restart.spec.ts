import {test,expect,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {isolatedPreferences} from './preferences';
import {launchElectronTarget,electronTargetEvidence} from './electron-target';
test.use({trace:'off',screenshot:'off',video:'off'});
test('normal full-process quit and relaunch preserve query-local choices',async({},info)=>{
 test.skip(process.env.FMG_LOCAL_RESTART!=='18093','Exclusive synthetic fixture, no HTTP writes.');test.setTimeout(60000);
 const origin='http://127.0.0.1:18093',config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin)throw Error('fixture_origin');const userData=await mkdtemp('/tmp/fmg-selection-restart-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
 let app:ElectronApplication|undefined;const targets:unknown[]=[],traffic:unknown[]=[];let errors=0;
 async function launch(){
  app=await launchElectronTarget(userData,env);await app.firstWindow();targets.push(await electronTargetEvidence(app));
  await app.evaluate(({session,BrowserWindow},origin)=>{BrowserWindow.getAllWindows()[0].setSize(1440,1000);(globalThis as any).__restartWrites=[];for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{if(!/^https?:/.test(details.url)){callback({cancel:false});return;}const write=details.method!=='GET';if(write)(globalThis as any).__restartWrites.push(details.method+' '+new URL(details.url).pathname);callback({cancel:write||new URL(details.url).origin!==origin});});},origin);
  const page=await app.firstWindow();page.setDefaultTimeout(10000);page.on('pageerror',()=>errors++);await page.emulateMedia({reducedMotion:'reduce'});return page;
 }
 async function openActivity(page:Awaited<ReturnType<typeof launch>>){await page.getByRole('button',{name:'Match',exact:true}).click();await page.getByRole('list',{name:'Activities'}).getByRole('button').first().click();const checks=page.getByRole('table',{name:'Creator matches'}).getByRole('checkbox');await expect(checks).toHaveCount(6);await expect(checks.first()).toBeEnabled();return checks;}
 try{
  let page=await launch();await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry');}await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
  let checks=await openActivity(page);await expect(checks.first()).toBeChecked();await expect(checks.nth(1)).toBeChecked();await checks.first().click();await expect(page.getByRole('button',{name:'Review selected · 5'})).toBeEnabled();
  const context=await page.evaluate(async()=>{const activities=await window.desktop.match.activities({offset:0,limit:50});if(!activities.ok)throw Error('activities');const activityId=activities.data.items[0].id;const searches=await window.desktop.match.creatorSearches({activityId,offset:0,limit:50});if(!searches.ok)throw Error('searches');return {activityId,queryId:searches.data.items[0].query_id};});
  await expect.poll(()=>page.evaluate(async context=>{const value=await window.desktop.localSelections!.read(context);return value.ok?value.data.state?.draft.desired.length:null;},context)).toBe(5);
  await checks.nth(1).click();await expect(checks.nth(1)).not.toBeChecked();
  traffic.push(await app!.evaluate(()=>(globalThis as any).__restartWrites));const firstProcess=app!.process();const firstPid=firstProcess.pid;
  // app.close performs normal app.quit, including the local-journal drain hook.
  // No explicit persistence wait is inserted after the second toggle.
  await app!.close();expect(firstProcess.exitCode).toBe(0);app=undefined;
  page=await launch();expect(app!.process().pid).not.toBe(firstPid);await expect(page.getByText('Workspace linked',{exact:true})).toBeVisible();checks=await openActivity(page);
  await expect(page.getByRole('button',{name:'Review selected · 4'})).toBeEnabled();await expect(checks.first()).not.toBeChecked();await expect(checks.nth(1)).not.toBeChecked();
  const saved=await page.evaluate(context=>window.desktop.localSelections!.read(context),context);expect(saved).toMatchObject({ok:true,data:{state:{stage:'ready',draft:{desired:expect.any(Array)}}}});if(saved.ok)expect(saved.data.state!.draft.desired).toHaveLength(4);
  traffic.push(await app!.evaluate(()=>(globalThis as any).__restartWrites));expect(traffic).toEqual([[],[]]);expect(errors).toBe(0);await page.screenshot({path:info.outputPath('restored-after-process-restart.png')});
  await writeFile(info.outputPath('verification.json'),JSON.stringify({status:'passed',fullProcessRestart:true,normalQuit:true,sameUserData:userData,targets,desiredAfterRestart:4,pendingSecondToggleDrained:true,httpWrites:traffic,pageErrors:errors,syntheticFixture:true,mockedPreparationIPC:false},null,2));
 }catch(error){if(app)await app.firstWindow().then(page=>page.screenshot({path:info.outputPath('failure.png')})).catch(()=>{});throw error;}finally{if(app)await app.close();}
});
