import {test,expect,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {launchElectronTarget,electronTargetEvidence} from './electron-target';
import {isolatedPreferences} from './preferences';
test.use({trace:'off',video:'off',screenshot:'off'});
test('local bulk actions, review restoration and reload do not write HTTP',async({},info)=>{
 test.skip(process.env.FMG_BULK_SELECTION!=='18093','Isolated GET-only fixture required.');test.setTimeout(60000);
 const origin='http://127.0.0.1:18093',config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin)throw Error('fixture_origin');const userData=await mkdtemp('/tmp/fmg-bulk-selection-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;let app:ElectronApplication|undefined;
 try{
  app=await launchElectronTarget(userData,env);const target=await electronTargetEvidence(app),page=await app.firstWindow();page.setDefaultTimeout(10000);
  await app.evaluate(({session,BrowserWindow},origin)=>{BrowserWindow.getAllWindows()[0].setSize(1440,1000);(globalThis as any).__bulkTraffic=[];for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
   if(!/^https?:/.test(details.url)){callback({cancel:false});return;}(globalThis as any).__bulkTraffic.push({method:details.method,path:new URL(details.url).pathname});callback({cancel:details.method!=='GET'||new URL(details.url).origin!==origin});
  });},origin);
  let errors=0;page.on('pageerror',()=>errors++);await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
  async function open(){await page.getByRole('button',{name:'Match',exact:true}).click();await page.getByRole('list',{name:'Activities',exact:true}).getByRole('button').first().click();await expect(page.getByRole('table',{name:'Creator matches',exact:true}).getByRole('checkbox')).toHaveCount(6);}
  await open();const checks=page.getByRole('table',{name:'Creator matches',exact:true}).getByRole('checkbox'),actions=page.getByRole('group',{name:'Loaded creators selection',exact:true});
  await expect(actions.getByRole('button',{name:'Deselect all'})).toBeEnabled();
  const context=await page.evaluate(async()=>{const acts=await window.desktop.match.activities({offset:0,limit:50});if(!acts.ok)throw Error('fixture');const activityId=acts.data.items[0].id;const searches=await window.desktop.match.creatorSearches({activityId,offset:0,limit:50});if(!searches.ok)throw Error('fixture');return {activityId,queryId:searches.data.items[0].query_id};});
  const readsBefore=await app.evaluate(()=>(globalThis as any).__bulkTraffic.filter((row:any)=>row.path.endsWith('/selections')).length);
  await actions.getByRole('button',{name:'Deselect all'}).focus();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'Review selected · 0'})).toBeEnabled();for(let i=0;i<6;i++)await expect(checks.nth(i)).not.toBeChecked();
  await actions.getByRole('button',{name:'Select all',exact:true}).click();for(let i=0;i<6;i++)await expect(checks.nth(i)).toBeChecked();
  expect(await app.evaluate(()=>(globalThis as any).__bulkTraffic.filter((row:any)=>row.path.endsWith('/selections')).length)).toBe(readsBefore);
  await page.screenshot({path:info.outputPath('all-loaded-selected.png')});
  await page.getByRole('button',{name:'Review selected · 6'}).click();const review=page.getByRole('group',{name:'Listed review creators selection'}),rows=page.getByRole('list',{name:'Selected creators'});
  await review.getByRole('button',{name:'Deselect all'}).click();await expect(rows.getByRole('checkbox')).toHaveCount(6);for(let i=0;i<6;i++)await expect(rows.getByRole('checkbox').nth(i)).not.toBeChecked();
  await expect(page.getByRole('button',{name:'Prepare 0',exact:true})).toBeDisabled();
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(760,720));await expect(review.getByRole('button',{name:'Select all',exact:true})).toBeInViewport();
  await page.screenshot({path:info.outputPath('review-cleared-narrow.png')});await review.getByRole('button',{name:'Select all',exact:true}).click();await expect(page.getByRole('button',{name:'Prepare 6'})).toBeEnabled();
  await expect.poll(()=>page.evaluate(async context=>{const saved=await window.desktop.localSelections!.read(context);return saved.ok?saved.data.state?.draft.desired.length:null;},context)).toBe(6);
  await page.reload();await open();for(let i=0;i<6;i++)await expect(checks.nth(i)).toBeChecked();
  const traffic=await app.evaluate(()=>(globalThis as any).__bulkTraffic);expect(traffic.filter((row:any)=>row.method!=='GET')).toEqual([]);expect(errors).toBe(0);
  await writeFile(info.outputPath('verification.json'),JSON.stringify({target,rows:6,native:true,userData,keyboard:true,narrow:true,reviewRestore:true,reload:true,httpWrites:0,perBulkSelectionReads:0,pageErrors:errors},null,2));
 }catch(error){if(app)await (await app.firstWindow()).screenshot({path:info.outputPath('failure.png')}).catch(()=>{});throw error;}finally{await app?.close();}
});
