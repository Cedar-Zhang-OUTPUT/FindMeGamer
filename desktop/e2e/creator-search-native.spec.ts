import {test,expect,_electron as electron,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {isolatedPreferences} from './preferences';

test.use({trace:'off',screenshot:'off',video:'off'});
for(const stopEarly of [false,true])test(`automatic search through native IPC and isolated HTTP ${stopEarly?'stops and retries':'preserves email-independent matches'}`,async({},info)=>{
 test.skip(process.env.FMG_CREATOR_SEARCH_NATIVE!=='18093','Requires the exclusive synthetic HTTP fixture.');
 test.setTimeout(150_000);
 const origin='http://127.0.0.1:18093',gameId='10000000-0000-4000-8000-000000000022';
 const config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin||typeof config.workspace_key!=='string')throw Error('fixture_configuration');
 const userData=await mkdtemp('/tmp/fmg-creator-search-native-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
 let app:ElectronApplication|undefined;
 try{
  app=await electron.launch({args:['.',`--user-data-dir=${userData}`],cwd:process.cwd(),env,chromiumSandbox:true,timeout:20000});
  const page=await app.firstWindow();
  await app.evaluate(({session,BrowserWindow},origin)=>{
   BrowserWindow.getAllWindows()[0].setSize(1440,1000);
   const state={activity:'',search:'',posts:[] as string[],blocked:[] as string[]};(globalThis as any).__searchNative=state;
   for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
    if(!/^https?:/.test(details.url)){callback({cancel:false});return;}
    const url=new URL(details.url),write=details.method!=='GET';
    const allowed=url.origin===origin&&(!write||details.method==='POST'&&(url.pathname==='/api/v2/activities'||state.activity&&url.pathname===`/api/v2/activities/${state.activity}/creator-searches`||state.search&&['stop','retry'].some(action=>url.pathname===`/api/v2/creator-searches/${state.search}/${action}`)));
    if(write&&allowed)state.posts.push(url.pathname);
    if(!allowed)state.blocked.push(details.method+' '+url.origin+url.pathname);
    callback({cancel:!allowed});
   });
  },origin);
  let pageErrors=0;page.on('pageerror',()=>pageErrors++);await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);
  try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry_failed');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Workspace key',{exact:true})).toHaveValue('');
  await page.getByRole('button',{name:'Match',exact:true}).click();await page.getByRole('button',{name:'New activity',exact:true}).click();
  await page.getByRole('searchbox',{name:'Search games'}).fill('Synthetic Star Garden');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByRole('button',{name:'Use game Synthetic Star Garden',exact:true}).click();
  const name='Automatic UI '+randomUUID().slice(0,8);
  await page.getByText('Activity name · Optional',{exact:true}).click();await page.getByLabel('Activity name',{exact:true}).fill(name);
  await page.getByRole('button',{name:'Continue to matching',exact:true}).click();await expect(page.getByRole('form',{name:'Discovery conditions'})).toBeVisible();
  const owned=await page.evaluate(async name=>{const r=await window.desktop.match.activities({limit:50,offset:0});return r.ok?r.data.items.find(item=>item.name===name)?.id:null;},name);
  if(!owned)throw Error('owned_activity_not_found');
  await app.evaluate((_electron,id)=>{(globalThis as any).__searchNative.activity=id;},owned);
  for(const platform of ['YouTube','X'])await page.getByRole('checkbox',{name:platform,exact:true}).check();
  for(const platform of ['Twitch','Instagram'])await page.getByRole('checkbox',{name:platform,exact:true}).uncheck();
  await page.screenshot({path:info.outputPath('conditions.png')});
  await page.getByRole('button',{name:'Find creators',exact:true}).click();
  const search=page.getByRole('region',{name:'Creator search',exact:true});await expect(search).toBeVisible();
  await expect(search.getByRole('button',{name:'Stop search',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:/^Draft \d+ emails$/})).toHaveCount(0);
  await page.screenshot({path:info.outputPath('processing.png')});
  let stoppedId:string|null=null;
  if(stopEarly){
   const task=await page.evaluate(async activityId=>{const r=await window.desktop.match.creatorSearches({activityId,limit:50,offset:0});return r.ok?r.data.items[0]:null;},owned);
   if(!task)throw Error('owned_search_not_found');stoppedId=task.id;
   await app.evaluate((_electron,id)=>{(globalThis as any).__searchNative.search=id;},task.id);
   await search.getByRole('button',{name:'Stop search',exact:true}).click();
   await expect(search.getByRole('heading',{name:'Search stopped',exact:true})).toBeVisible({timeout:20000});
   await page.screenshot({path:info.outputPath('stopped.png')});
   await expect(search.getByRole('button',{name:'Retry unfinished work',exact:true})).toBeEnabled();
   await search.getByRole('button',{name:'Retry unfinished work',exact:true}).click();
  }
  await expect(search.getByRole('heading',{name:'Complete',exact:true})).toBeVisible({timeout:90000});
  const results=search.getByRole('region',{name:'Creator matches',exact:true});await expect(results.locator('tbody > tr')).toHaveCount(6,{timeout:20000});
  await expect(results.getByText('Email available',{exact:true})).toHaveCount(4);await expect(results.getByText('Email not found',{exact:true})).toHaveCount(2);
  await expect(results.locator('.match-badge.fit')).toHaveCount(6);await expect(results.getByText('Not evaluated',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:/Evaluate.*loaded/})).toHaveCount(0);
  await expect(page.getByRole('button',{name:/Review selected/})).toBeEnabled();
  await page.screenshot({path:info.outputPath('complete.png')});
  await page.getByRole('button',{name:'Activities',exact:true}).click();await page.getByRole('button',{name:'Open '+name,exact:true}).click();await expect(page.getByRole('region',{name:'Creator matches'}).locator('tbody > tr')).toHaveCount(6);
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(760,920));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:info.outputPath('narrow.png')});
  const evidence=await app.evaluate(()=>(globalThis as any).__searchNative);expect(evidence.posts).toEqual(['/api/v2/activities',`/api/v2/activities/${owned}/creator-searches`,...(stoppedId?[`/api/v2/creator-searches/${stoppedId}/stop`,`/api/v2/creator-searches/${stoppedId}/retry`]:[])]);expect(pageErrors).toBe(0);
  await writeFile(info.outputPath('verification.json'),JSON.stringify({status:'passed',native:true,packaged:false,backendPin:'755cc4827bbefa174e7e673f526692bcef458d65',syntheticProviders:true,realBroker:false,gameId,activityId:owned,userData,evidence,pageErrors},null,2));
 }finally{await app?.close();}
});
