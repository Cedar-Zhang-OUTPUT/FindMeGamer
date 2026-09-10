import {test,expect,_electron as electron,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {isolatedPreferences} from './preferences';
test.use({trace:'off',video:'off',screenshot:'off'});
test('native rapid local toggles survive reload and Prepare replays only the unknown freeze',async({},info)=>{
 test.skip(process.env.FMG_LOCAL_SELECTION_NATIVE!=='18093','Isolated read-only HTTP fixture plus synthetic preparation IPC.');test.setTimeout(60000);
 const origin='http://127.0.0.1:18093',config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin)throw Error('fixture_origin');const userData=await mkdtemp('/tmp/fmg-local-selection-native-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;let app:ElectronApplication|undefined;
 try{
  app=await electron.launch({args:['.',`--user-data-dir=${userData}`],cwd:process.cwd(),env,chromiumSandbox:true});const page=await app.firstWindow();page.setDefaultTimeout(10000);
  await app.evaluate(({session,BrowserWindow},origin)=>{BrowserWindow.getAllWindows()[0].setSize(1440,1000);(globalThis as any).__localHTTPWrites=[];for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{if(!/^https?:/.test(details.url)){callback({cancel:false});return;}const write=details.method!=='GET';if(write)(globalThis as any).__localHTTPWrites.push(details.method+' '+new URL(details.url).pathname);callback({cancel:write||new URL(details.url).origin!==origin});});},origin);
  await page.emulateMedia({reducedMotion:'reduce'});let errors=0;page.on('pageerror',()=>errors++);
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
  async function openActivity(){await page.getByRole('button',{name:'Match',exact:true}).click();await page.getByRole('list',{name:'Activities'}).getByRole('button').first().click();await expect(page.getByRole('table',{name:'Creator matches'}).getByRole('checkbox').first()).toBeEnabled();}
  await openActivity();
  const context=await page.evaluate(async()=>{const acts=await window.desktop.match.activities({offset:0,limit:50});if(!acts.ok)throw Error('activities');const activityId=acts.data.items[0].id;const selections=await window.desktop.outreach.selections({activityId,includeCancelled:true,offset:0,limit:200});if(!selections.ok)throw Error('selections');return {activityId,rows:selections.data.items};});
  // Only synthetic preparation IPC is replaced. All real HTTP business writes
  // remain blocked. Each read is delayed to expose accidental per-click refreshes.
  await app.evaluate(({ipcMain},serialized)=>{
   const context=JSON.parse(serialized);
   const globals=globalThis as any;globals.__localCalls=[];globals.__localRows=context.rows;globals.__freezeAttempts=[];
   for(const channel of ['outreach:selections','outreach:bulk','outreach:freeze'])ipcMain.removeHandler(channel);
   ipcMain.handle('outreach:selections',async(_event,input)=>{globals.__localCalls.push('read');await new Promise(r=>setTimeout(r,500));const rows=globals.__localRows.filter((p:any)=>input.includeCancelled||p.active);return {ok:true,data:{items:rows.slice(input.offset??0,(input.offset??0)+(input.limit??200)),total:rows.length,offset:input.offset??0,limit:input.limit??200}};});
   ipcMain.handle('outreach:bulk',async(_event,input)=>{globals.__localCalls.push('bulk');globals.__bulkInput=input;await new Promise(r=>setTimeout(r,500));const cancelled=input.data.cancel_selections??[];globals.__localRows=globals.__localRows.map((p:any)=>cancelled.some((c:any)=>c.selection_id===p.id)?{...p,active:false,revision:p.revision+1}:p);return {ok:true,data:{added_selection_ids:[],cancelled_selection_ids:cancelled.map((c:any)=>c.selection_id)}};});
   ipcMain.handle('outreach:freeze',async(_event,input)=>{globals.__localCalls.push('freeze');globals.__freezeAttempts.push(input);if(globals.__freezeAttempts.length===1)return {ok:false,error:{code:'outreach_outcome_unknown',message:'Synthetic lost freeze acknowledgement',retryable:false}};
    const recipients=input.data.recipients.map((c:any,index:number)=>{const p=globals.__localRows.find((p:any)=>p.id===c.selection_id);return {id:`00000000-0000-4000-8000-${String(index+1).padStart(12,'0')}`,selection_id:p.id,snapshot:p,preparation:p,source_changed:false,current_missing_fields:p.missing_fields};});
    return {ok:true,data:{id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',activity_id:context.activityId,request_id:input.data.request_id,status:'frozen',send_ready:false,recipient_count:recipients.length,send_ready_count:0,needs_repair_count:recipients.length,created_at:'2026-09-10T00:00:00Z',source_snapshot:{},recipients}};
   });
  },JSON.stringify(context));
  const first=page.getByRole('table',{name:'Creator matches'}).getByRole('checkbox').first();const initial=await first.isChecked();const timings:number[]=[];
  for(let i=0;i<31;i++){const before=Date.now();await first.click();await expect(first).toBeChecked({checked:i%2===0?!initial:initial});await expect(first).toBeEnabled();timings.push(Date.now()-before);}
  expect(await app.evaluate(()=>(globalThis as any).__localCalls)).toEqual([]);await expect(page.getByRole('button',{name:'Review selected · 5',exact:true})).toBeEnabled();await page.screenshot({path:info.outputPath('local-toggles.png')});
  // Wait for durable local journal completion using its public read port, not a sleep.
  await expect.poll(()=>page.evaluate(async(activityId)=>{const searches=await window.desktop.match.creatorSearches({activityId,offset:0,limit:50});if(!searches.ok)return null;const queryId=searches.data.items[0].query_id;const saved=await window.desktop.localSelections!.read({activityId,queryId});return saved.ok?saved.data.state?.draft.desired.length:null;},context.activityId)).toBe(5);
  await page.reload();await openActivity();await expect(first).toBeChecked({checked:!initial});await expect(page.getByRole('button',{name:'Review selected · 5',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Review selected · 5',exact:true}).click();await page.getByRole('button',{name:'Prepare 5',exact:true}).click();await expect(page.getByText('Synthetic lost freeze acknowledgement',{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath('unknown-freeze-preserved.png')});await page.getByRole('button',{name:'Retry original preparation',exact:true}).click();await expect(page.getByRole('button',{name:'Retry original preparation',exact:true})).toHaveCount(0);
  const evidence=await app.evaluate(()=>{const g=globalThis as any;return {calls:g.__localCalls,bulk:g.__bulkInput,freezeAttempts:g.__freezeAttempts,httpWrites:g.__localHTTPWrites};});
  expect(evidence.calls.filter((v:string)=>v==='bulk')).toHaveLength(1);expect(evidence.freezeAttempts).toHaveLength(2);expect(evidence.freezeAttempts[0]).toEqual(evidence.freezeAttempts[1]);expect(evidence.bulk.data.cancel_selections).toHaveLength(1);expect(evidence.httpWrites).toEqual([]);expect(errors).toBe(0);
  await writeFile(info.outputPath('verification.json'),JSON.stringify({status:'passed',native:true,packaged:false,syntheticPreparationIPC:true,perClickHTTPWrites:0,perClickSelectionReads:0,toggleCount:31,toggleDurationsMs:timings,reloadedLocalDraft:true,bulkCalls:1,identicalFreezeReplays:true,pageErrors:errors,userData,evidence},null,2));
 }catch(error){if(app)await app.firstWindow().then(page=>page.screenshot({path:info.outputPath('failure.png')})).catch(()=>{});throw error;}finally{if(app){await app.evaluate(({BrowserWindow})=>{for(const window of BrowserWindow.getAllWindows())window.destroy();}).catch(()=>{});await app.close();}}
});
