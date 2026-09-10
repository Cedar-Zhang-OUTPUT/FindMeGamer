import {test,expect,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {launchElectronTarget,electronTargetEvidence} from './electron-target';
import {isolatedPreferences} from './preferences';

test.use({trace:'off',screenshot:'off',video:'off'});
for(const kind of ['creators','games','matches','invitations'] as const) test(`50-row ${kind}: wheel and keyboard reach bottom in short wide/narrow windows`,async({},info)=>{
 test.skip(process.env.FMG_TABLE_SCROLL!=='18093','Isolated GET fixture required; no online operations.');test.setTimeout(90000);
 const origin='http://127.0.0.1:18093';
 const config=JSON.parse(await readFile('/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/creator-search-http/client.json','utf8'));
 if(config.base_url!==origin)throw Error('fixture_origin');
 const userData=await mkdtemp('/tmp/fmg-table-scroll-');await isolatedPreferences(userData);
 const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
 let app:ElectronApplication|undefined;
 try{
  app=await launchElectronTarget(userData,env);const target=await electronTargetEvidence(app);const page=await app.firstWindow();page.setDefaultTimeout(10000);
  await app.evaluate(({session,BrowserWindow},origin)=>{
   BrowserWindow.getAllWindows()[0].setSize(1440,680);(globalThis as any).__scrollWrites=[];
   for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
    if(!/^https?:/.test(details.url)){callback({cancel:false});return;}
    if(details.method!=='GET')(globalThis as any).__scrollWrites.push(details.method+' '+new URL(details.url).pathname);
    callback({cancel:details.method!=='GET'||new URL(details.url).origin!==origin});
   });
  },origin);
  let pageErrors=0;page.on('pageerror',()=>pageErrors++);await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);
  try{await page.getByLabel('Workspace key',{exact:true}).fill(config.workspace_key);}catch{throw Error('credential_entry');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
  // Read existing isolated data; expand DTOs through synthetic IPC, never create server records.
  const seed=await page.evaluate(async()=>{
   const api=window.desktop;
   const unwrap=(r:any)=>{if(!r.ok)throw Error('fixture_read');return r.data;};
   const activity=unwrap(await api.match.activities({offset:0,limit:50})).items[0];
   const search=unwrap(await api.match.creatorSearches({activityId:activity.id,offset:0,limit:50})).items[0];
   return {activity,creators:unwrap(await api.creators.list({offset:0,limit:50})).items,
    games:unwrap(await api.games.list({offset:0,limit:24})).items,
    candidates:unwrap(await api.match.candidates({queryId:search.query_id,offset:0,limit:100})).items,
    people:unwrap(await api.match.creatorSearchPeople({id:search.id,offset:0,limit:100})).items,
    results:unwrap(await api.match.evaluationResults({id:search.evaluation_id,offset:0,limit:100})).items,
    invitations:unwrap(await api.collaboration.list({activityId:activity.id,offset:0,limit:50})).items};
  });
  await app.evaluate(({ipcMain},seed)=>{
   const uuid=(prefix:number,i:number)=>`${prefix}0000000-0000-4000-8000-${String(i+1).padStart(12,'0')}`;
   const rows=(source:any[],type:string)=>Array.from({length:51},(_,i)=>{
    const row=structuredClone(source[i%source.length]),creator=uuid(1,i),candidate=uuid(2,i),name=`Scroll ${type} ${String(i+1).padStart(2,'0')}`;
    if(type==='creators'||type==='games'){row.id=creator;row.name=name;}
    else{row.creator_id=creator;row.candidate_id=candidate;row.name=name;row.display_name=name;
     if(type==='candidates'){row.id=candidate;row.creator={...row.creator,id:creator,name};row.account_id=`UCscroll${i}`;row.account={...row.account,account_id:row.account_id,display_name:name};}
     if(type==='invitations')row.selection_id=uuid(3,i);
    }return row;
   });
   for(const [channel,type] of [['creators:list','creators'],['games:list','games'],['match:candidates','candidates'],['match:creator-search-people','people'],['match:evaluation-results','results'],['collaboration:list','invitations']]){
    const data=rows((seed as any)[type],type),total=['creators','games','invitations'].includes(type)?51:50;
    ipcMain.removeHandler(channel);ipcMain.handle(channel,(_event,input)=>{
     const offset=input?.offset??0;
     // Force a 50-row stress page even for Games' normally smaller page size.
     return {ok:true,data:{items:data.slice(offset,Math.min(offset+50,total)),total,offset,limit:50}};
    });
   }
  },seed);
  await page.getByRole('button',{name:'Library',exact:true}).click();
  if(kind==='creators')await page.getByRole('button',{name:'Refresh Library',exact:true}).click();
  if(kind==='games')await page.getByRole('tab',{name:'Games',exact:true}).click();
  if(kind==='matches'||kind==='invitations'){
   await page.getByRole('button',{name:'Match',exact:true}).click();await page.getByRole('list',{name:'Activities',exact:true}).getByRole('button').first().click();
   await expect(page.getByRole('table',{name:'Creator matches',exact:true}).locator('tbody > tr')).toHaveCount(50);
   if(kind==='invitations')await page.getByRole('button',{name:'Outreach',exact:true}).click();
  }
  const table=page.getByRole('table',{name:{creators:'Creators',games:'Games',matches:'Creator matches',invitations:'Invitation relationships'}[kind],exact:true});
  const region=table.locator('..'),main=page.locator('.main-scroll'),last=table.locator('tbody > tr').last();
  await expect(table.locator('tbody > tr')).toHaveCount(50);
  const measurements=[];
  for(const width of [1440,760]){
   await app.evaluate(({BrowserWindow},width)=>BrowserWindow.getAllWindows()[0].setSize(width,680),width);
   // Reset is setup only. All progression assertions use actual wheel/key events, no scrollIntoView.
   await main.evaluate(el=>el.scrollTop=0);await region.evaluate(el=>el.scrollLeft=0);
   const bounds=await main.boundingBox();if(!bounds)throw Error('main_bounds');
   // Wheel outside the table only to expose a row when a tall header fills a short window.
   for(let i=0;i<8;i++){
    const first=await table.locator('tbody > tr').first().boundingBox();
    if(first&&first.y<bounds.y+bounds.height-70)break;
    await page.mouse.move(bounds.x+3,bounds.y+70);await page.mouse.wheel(0,150);await page.waitForTimeout(80);
   }
   const cell=await table.locator('tbody > tr').first().boundingBox();if(!cell)throw Error('row_bounds');
   const pointer={x:bounds.x+Math.min(180,bounds.width/2),y:Math.min(bounds.y+bounds.height-60,Math.max(bounds.y+50,cell.y+25))};
   await page.mouse.move(pointer.x,pointer.y);
   expect(await page.evaluate(({x,y})=>Boolean(document.elementFromPoint(x,y)?.closest('tbody')),pointer)).toBe(true);
   const before=await main.evaluate(el=>el.scrollTop);await page.mouse.wheel(0,320);
   await expect.poll(()=>main.evaluate(el=>el.scrollTop),{timeout:3000,message:'Vertical wheel over tbody must reach main scroll'}).toBeGreaterThan(before+100);
   if(width===760){
    await page.mouse.wheel(650,0);await expect.poll(()=>region.evaluate(el=>el.scrollLeft)).toBeGreaterThan(100);
   }
   for(let i=0;i<24;i++){
    if(await last.evaluate(el=>{const r=el.getBoundingClientRect(),m=document.querySelector('.main-scroll')!.getBoundingClientRect();return r.bottom<=m.bottom&&r.top>=m.top;}))break;
    await page.mouse.move(pointer.x,bounds.y+bounds.height/2);await page.mouse.wheel(0,700);await page.waitForTimeout(50);
   }
   const lastVerticallyVisible=()=>last.evaluate(el=>{const r=el.getBoundingClientRect(),m=document.querySelector('.main-scroll')!.getBoundingClientRect();return r.top>=m.top-1&&r.bottom<=m.bottom+1;});
   await expect.poll(lastVerticallyVisible).toBe(true);
   const footer=kind==='matches'?page.locator('.match-workspace-footer'):page.locator({creators:'.creator-library-pagination',games:'.game-pagination',invitations:'.collaboration-pagination'}[kind]);
   if(kind!=='matches'){
    await expect(footer).toHaveCount(1);
    await page.mouse.move(pointer.x,bounds.y+bounds.height-90);await page.mouse.wheel(0,1000);
    await expect(footer).toBeInViewport({ratio:1});
    await expect(footer.getByRole('button').last()).toBeInViewport({ratio:1});
   }
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
   await page.screenshot({path:info.outputPath(`${kind}-${width}-bottom.png`)});
   const bottom=await main.evaluate(el=>el.scrollTop);
   // Upward wheel over the table must also chain, even after horizontal scrolling.
   await page.mouse.move(pointer.x,bounds.y+90);await page.mouse.wheel(0,-500);
   await expect.poll(()=>main.evaluate(el=>el.scrollTop)).toBeLessThan(bottom-100);
   await region.focus();await expect(region).toBeFocused();
   // Explicit setup for keyboard test, with focus kept on the table's public region.
   await main.evaluate(el=>el.scrollTop=0);await region.evaluate(el=>el.scrollLeft=0);
   await page.keyboard.press('PageDown');await expect.poll(()=>main.evaluate(el=>el.scrollTop)).toBeGreaterThan(100);
   if(width===760){await page.keyboard.press('ArrowRight');await expect.poll(()=>region.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);}
   for(let i=0;i<30;i++){await page.keyboard.press('PageDown');if(await main.evaluate(el=>el.scrollTop+el.clientHeight>=el.scrollHeight-2))break;}
   await expect.poll(lastVerticallyVisible).toBe(true);if(kind!=='matches')await expect(footer).toBeInViewport({ratio:1});
   await page.keyboard.press('Home');await expect.poll(()=>main.evaluate(el=>el.scrollTop)).toBe(0);
   await page.keyboard.press('End');await expect.poll(lastVerticallyVisible).toBe(true);
   measurements.push({width,height:680,rows:50,wheelStart:before,wheelBottom:bottom,keyboardBottom:await main.evaluate(el=>el.scrollTop),horizontal:await region.evaluate(el=>el.scrollLeft)});
  }
  const writes=await app.evaluate(()=>(globalThis as any).__scrollWrites);expect(writes).toEqual([]);expect(pageErrors).toBe(0);
  await writeFile(info.outputPath('verification.json'),JSON.stringify({target,kind,syntheticExpandedIPC:true,realHTTPWrites:writes,pageErrors,measurements},null,2));
 }catch(error){if(app)await (await app.firstWindow()).screenshot({path:info.outputPath('failure.png')}).catch(()=>{});throw error;}finally{await app?.close();}
});
