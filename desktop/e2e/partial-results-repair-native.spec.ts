import {test,expect,_electron as electron,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {isolatedPreferences} from './preferences';
import {compositionFixture,draftFixture,draftIds,templateVersion} from '../tests/drafts-fixtures';
import {recipientBatchFixture} from '../tests/outreach-fixtures';

test.use({trace:'off',screenshot:'off',video:'off'});
test('native partial results and needs-repair mail stay visible without writes',async({},info)=>{
 test.skip(process.env.FMG_PARTIAL_REPAIR_NATIVE!=='18093','Read-only exclusive synthetic fixture.');test.setTimeout(90000);
 const origin='http://127.0.0.1:18093',config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin)throw Error('fixture_origin');
 const userData=await mkdtemp('/tmp/fmg-partial-repair-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
 let app:ElectronApplication|undefined;
 try{
  app=await electron.launch({args:['.',`--user-data-dir=${userData}`],cwd:process.cwd(),env,chromiumSandbox:true});const page=await app.firstWindow();page.setDefaultTimeout(12000);
  await app.evaluate(({session,BrowserWindow},origin)=>{
   BrowserWindow.getAllWindows()[0].setSize(1440,1000);
   (globalThis as any).__repair={fail:'candidates',writes:[],reads:[]};
   for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
    if(!/^https?:/.test(details.url)){callback({cancel:false});return;}
    const state=(globalThis as any).__repair,url=new URL(details.url),write=details.method!=='GET';
    if(write)state.writes.push(details.method+' '+url.pathname);else state.reads.push(url.pathname);
    const fail=state.fail==='candidates'&&/\/discovery\/queries\/[^/]+\/results$/.test(url.pathname);
    callback({cancel:write||url.origin!==origin||Boolean(fail)});
   });
  },origin);
  let pageErrors=0;page.on('pageerror',()=>pageErrors++);await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);
  try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Match',exact:true}).click();await page.getByRole('list',{name:'Activities',exact:true}).getByRole('button').first().click();
  const matches=page.getByRole('region',{name:'Creator matches',exact:true});
  await expect(matches.getByRole('article')).toHaveCount(6);await expect(page.getByRole('region',{name:'Result loading issues'})).toContainText('Selection data');
  await expect(page.getByRole('button',{name:'Find more creators'})).toBeDisabled();await page.screenshot({path:info.outputPath('partial-results.png')});
  await app.evaluate(()=>(globalThis as any).__repair.fail=null);
  await page.getByRole('button',{name:'Reload results',exact:true}).click();await expect(page.getByRole('region',{name:'Result loading issues'})).toHaveCount(0);
  await expect(matches.getByRole('checkbox').first()).toBeEnabled();
  const activity=await page.evaluate(async()=>{const result=await window.desktop.match.activities({offset:0,limit:50});if(!result.ok)throw Error('fixture_activity');const row=result.data.items[0];return {id:row.id,game_id:row.game_id};});
  const repair=draftFixture({status:'needs_repair',missing_fields:['public_name_unconfirmed','reference_missing','observation_evidence_missing']});
  repair.input={...repair.input,public_name:null,public_name_confirmed:false,channel_name:'Hot Tea (synthetic)',reference:null,work:null};
  const rows=Array.from({length:50},(_,index)=>({...repair,id:`66666666-6666-4666-8666-${String(index+1).padStart(12,'0')}`,input_order:index,
   selection_id:`77777777-7777-4777-8777-${String(index+1).padStart(12,'0')}`,recipient_snapshot_id:`88888888-8888-4888-8888-${String(index+1).padStart(12,'0')}`,
   input:{...repair.input,channel_name:index?'Synthetic creator '+(index+1):'Hot Tea (synthetic)'}}));
  const composition=compositionFixture({activity_id:activity.id,drafts:rows,recipient_count:50});
  const batch=recipientBatchFixture({id:draftIds.batch,activity_id:activity.id,recipient_count:50});
  batch.recipients=rows.map(row=>({...batch.recipients[0],id:row.recipient_snapshot_id,selection_id:row.selection_id}));
  // Synthetic IPC responses test real Electron rendering, not production draft DTOs.
  await app.evaluate(({ipcMain},serialized)=>{
   (globalThis as any).__draftRepair=JSON.parse(serialized);
   for(const channel of ['drafts:compositions','drafts:composition','drafts:template','outreach:batch']){
    ipcMain.removeHandler(channel);ipcMain.handle(channel,()=>{const state=(globalThis as any).__draftRepair;(globalThis as any).__repair.reads.push(channel);return {ok:true,data:channel==='drafts:compositions'?{items:[state.composition],total:1,offset:0,limit:50}:channel==='drafts:composition'?state.composition:channel==='drafts:template'?state.template:state.batch};});
   }
  },JSON.stringify({composition,batch,template:{...templateVersion,game_id:activity.game_id}}));
  await page.getByText('History & saved lists',{exact:true}).click();await page.getByRole('button',{name:'Draft history',exact:true}).click();await page.getByRole('button',{name:'Open draft set',exact:true}).click();
  await page.getByText('History & saved lists',{exact:true}).click();
  await expect(page.getByRole('region',{name:'Draft email editor'})).toBeVisible();
  const preview=page.frameLocator('iframe[title="Template preview — not ready to send"]');
  await expect(preview.locator('body')).toContainText('LIMINAL: Within');await expect(preview.locator('body')).toContainText('Hot Tea (synthetic)');
  await expect(page.locator('.draft-preview-empty')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Edit personalization',exact:true})).toHaveAttribute('aria-expanded','false');
  const roster=page.getByRole('navigation',{name:'Draft people'});await expect(roster.getByRole('button')).toHaveCount(50);
  await roster.getByRole('button').nth(1).click();await expect(preview.locator('body')).toContainText('Synthetic creator 2');
  await roster.getByRole('button').first().click();await expect(preview.locator('body')).toContainText('Hot Tea (synthetic)');
  await page.getByRole('region',{name:'Draft email editor'}).scrollIntoViewIfNeeded();
  await page.screenshot({path:info.outputPath('needs-repair-template.png')});
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(760,920));
  await page.getByRole('region',{name:'Draft email editor'}).scrollIntoViewIfNeeded();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:info.outputPath('needs-repair-narrow.png')});
  await page.getByRole('button',{name:'Edit personalization',exact:true}).click();await expect(page.getByRole('button',{name:'Save changes',exact:true})).toBeDisabled();
  const evidence=await app.evaluate(()=>(globalThis as any).__repair);expect(evidence.writes).toEqual([]);expect(evidence.reads.filter((path:string)=>path==='drafts:template')).toHaveLength(1);expect(pageErrors).toBe(0);
  await writeFile(info.outputPath('verification.json'),JSON.stringify({status:'passed',native:true,packaged:false,syntheticDraftIPC:true,realProviders:false,userData,evidence,pageErrors},null,2));
 }finally{await app?.close();}
});
