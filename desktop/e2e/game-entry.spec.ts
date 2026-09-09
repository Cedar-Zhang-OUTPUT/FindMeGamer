import {test,expect,type BrowserContext} from '@playwright/test';
import {readFile,writeFile,lstat} from 'node:fs/promises';
import {createServer,type Server} from 'node:http';
import type {AddressInfo} from 'node:net';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {GameClient} from '../src/main/game-client';
import {CreatorClient} from '../src/main/creator-client';
import {LibraryClient} from '../src/main/library-client';
import {MatchClient} from '../src/main/match-client';
import {AnalysisClient} from '../src/main/analyze-client';
import {authenticatedAnalysisRequest} from '../src/main/analyze-transport';
import {authenticatedCreatorRequest} from '../src/main/creator-transport';
import {authenticatedMatchRequest} from '../src/main/match-transport';
import {authenticatedGameRequest,authenticatedGet,publicResult,type Fetcher} from '../src/main/transport';
import {ROOT,PRIVATE,ORIGIN,PIN,requireCheck,canonical,controls,events,eventCounts,treeHash,sha} from './analyze-fixture';

test.use({trace:'off',screenshot:'off',video:'off'});
test('game entry built renderer uses Library handoff and one source-only Steam import',async({browser},info)=>{
 test.skip(process.env.FMG_GAME_ENTRY!=='64692','Explicit exclusive synthetic lease required.');test.setTimeout(90_000);
 const configPath=PRIVATE+'/client.json',mode=await lstat(configPath);requireCheck(mode.isFile()&&!mode.isSymbolicLink()&&(mode.mode&0o777)===0o600,'private_permissions');
 const config=JSON.parse(await readFile(configPath,'utf8')),ids=JSON.parse(await readFile(PRIVATE+'/analyze-report.json','utf8'));
 requireCheck(config.base_url===ORIGIN&&config.backend_revision===PIN&&config.migration==='20260908_0019','fixture_pin');
 const control=JSON.parse(await readFile(PRIVATE+'/state/analyze-control.json','utf8'));requireCheck(control.mode==='none'&&control.stage==='none','fault_control_not_idle');
 const source=await treeHash(ROOT+'/src'),bundle=await treeHash(ROOT+'/out/renderer'),controlBefore=await controls(),start=(await events()).length;
 const ledger=PRIVATE+`/game-entry-${randomUUID()}.json`,traffic:{method:string;path:string;status?:number;body_hash?:string}[]=[];
 const report:Record<string,unknown>={status:'running',stage:'bootstrap',source_hash:source,bundle_hash:bundle,backend_revision:PIN,native:false,traffic,screenshots:[]};
 let writeAvailable=false,forbidden=0,pageErrors=0,unexpectedBridge=0,blockedImages=0;let context:BrowserContext|undefined,server:Server|undefined;
 const connection={serviceUrl:ORIGIN,key:config.workspace_key};
 const fetcher:Fetcher=async(url,init)=>{
   const u=new URL(url),method=init.method??'GET';let allowed=method==='GET'&&/^\/api\/(?:v1\/(?:session|jobs|profiles)(?:\/|$)|v2\/(?:activities$|library\/(?:games|creators)(?:\/|$)))/.test(u.pathname);
   if(method==='POST'&&writeAvailable&&u.pathname==='/api/v2/library/games/steam-import'){
     const body=JSON.parse(String(init.body));allowed=canonical(body)===canonical({url:'https://store.steampowered.com/app/900000001'});writeAvailable=false;
     requireCheck(Boolean(new Headers(init.headers).get('Idempotency-Key')),'request_key');
   }
   if(u.origin!==ORIGIN||!allowed){forbidden++;throw Error('outside_entry_scope');}
   const row={method,path:u.pathname,...(method==='POST'?{body_hash:sha(String(init.body))}:{})};traffic.push(row);
   const response=await fetch(u,{...init,signal:AbortSignal.any([AbortSignal.timeout(20_000),...(init.signal?[init.signal]:[])])});Object.assign(row,{status:response.status});return response;
 };
 const games=new GameClient(r=>authenticatedGameRequest(fetcher,connection,r)),creators=new CreatorClient(r=>authenticatedCreatorRequest(fetcher,connection,r)),library=new LibraryClient((r,q)=>authenticatedGet(fetcher,connection,r,q)),match=new MatchClient(r=>authenticatedMatchRequest(fetcher,connection,r)),analysis=new AnalysisClient(r=>authenticatedAnalysisRequest(fetcher,connection,r));
 async function checkpoint(stage:string){report.stage=stage;await writeFile(ledger,JSON.stringify(report,null,2),{mode:0o600});}
 try{
  const before=await games.detail(ids.game_id);requireCheck(before.source_identity.canonical_url==='https://store.steampowered.com/app/900000001','expected_source');
  const actions:Record<string,(v?:any)=>Promise<unknown>>={
   'connection.status':async()=>({serviceUrl:ORIGIN,hasKey:true,storageAvailable:true}),'connection.test':async()=>{await library.session();return {authenticated:true,proxy:'system',route:'direct'};},
   'preferences.read':async()=>({appearance:'system',fontSize:'default',automaticUpdates:false}),'updates.status':async()=>({phase:'development',installedVersion:'0.2.0-alpha.1',lastCheckedAt:null,lastAttemptAt:null,release:null,error:null}),
   'games.list':v=>games.list(v),'games.detail':v=>games.detail(v),'creators.list':v=>creators.list(v),'match.activities':v=>match.activities(v),'analysis.steamImport':v=>analysis.steamImport(v),
  };
  server=createServer(async(req,res)=>{const root=ROOT+'/out/renderer',file=path.resolve(root,req.url==='/'?'index.html':String(req.url).split('?')[0].replace(/^\/+/,''));if(req.method!=='GET'||!file.startsWith(root+'/')){res.writeHead(403).end();return;}try{res.writeHead(200,{'Content-Type':({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'} as Record<string,string>)[path.extname(file)]??'application/octet-stream'});res.end(await readFile(file));}catch{res.writeHead(404).end();}});
  await new Promise<void>(resolve=>server!.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  context=await browser.newContext({viewport:{width:1320,height:920},reducedMotion:'reduce'});context.setDefaultTimeout(12_000);
  await context.route('**/*',route=>{const url=route.request().url();if(url.startsWith(origin+'/')||url.startsWith('data:')||url.startsWith('about:'))return route.continue();if(route.request().resourceType()==='image'){blockedImages++;return route.fulfill({status:204,body:''});}forbidden++;return route.abort();});
  const page=await context.newPage();page.on('pageerror',()=>pageErrors++);
  await page.exposeBinding('__entryInvoke',async(_source,name:string,input:unknown)=>{const action=actions[name];if(!action){unexpectedBridge++;return {ok:false,error:{code:'fixture_scope',message:'Outside this verification.',retryable:false}};}return publicResult(()=>action(input));});
  await page.addInitScript(()=>{const group=(name:string,methods:string[])=>Object.fromEntries(methods.map(method=>[method,(input?:unknown)=>(window as any).__entryInvoke(`${name}.${method}`,input)]));Object.defineProperty(window,'desktop',{value:{connection:group('connection',['status','test']),preferences:group('preferences',['read']),updates:group('updates',['status']),games:group('games',['list','detail','create','update']),creators:group('creators',['list']),match:group('match',['activities']),analysis:group('analysis',['steamImport','changed','create'])}});});
  await checkpoint('library_handoff');await page.goto(origin);await expect(page.getByText('Workspace connected',{exact:true})).toBeVisible();await page.getByRole('tab',{name:'Games',exact:true}).click();
  await page.getByRole('searchbox',{name:'Search games',exact:true}).fill(before.name!);await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByRole('button',{name:`Open ${before.name}`,exact:true}).click();await page.getByRole('button',{name:'Use for Match',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Name',exact:true})).toHaveValue(before.name!);requireCheck(traffic.every(r=>r.method==='GET'),'handoff_no_write');
  await page.getByRole('button',{name:'Use game',exact:true}).click();await page.getByRole('button',{name:'Change game',exact:true}).click();await page.getByRole('searchbox',{name:'Search games',exact:true}).fill('Retained search');await page.getByRole('tab',{name:'Steam',exact:true}).click();
  await page.getByRole('textbox',{name:'Steam URL',exact:true}).fill(before.source_identity.canonical_url!);await page.getByRole('tab',{name:'Library',exact:true}).click();await expect(page.getByRole('searchbox',{name:'Search games',exact:true})).toHaveValue('Retained search');await page.getByRole('tab',{name:'Steam',exact:true}).click();await expect(page.getByRole('textbox',{name:'Steam URL',exact:true})).toHaveValue(before.source_identity.canonical_url!);
  await checkpoint('source_import');writeAvailable=true;await page.getByRole('textbox',{name:'Steam URL',exact:true}).press('Enter');await expect(page.getByRole('textbox',{name:'Name',exact:true})).toHaveValue(before.name!);
  const after=await games.detail(before.id);requireCheck(after.id===before.id&&after.revision===before.revision+1&&canonical(after.manual_overrides)===canonical(before.manual_overrides)&&canonical(after.reference_works)===canonical(before.reference_works)&&after.last_analyzed_at===before.last_analyzed_at&&after.favorite===before.favorite,'source_preserves_record');
  await page.getByRole('button',{name:'Use game',exact:true}).click();await expect(page.getByRole('button',{name:'Create activity',exact:true})).toBeVisible();await page.setViewportSize({width:760,height:920});await page.evaluate(()=>{document.documentElement.style.fontSize='135%';});
  requireCheck(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'narrow_overflow');const shot=info.outputPath('game-entry-narrow.png');await page.screenshot({path:shot});(report.screenshots as string[]).push(shot);
  requireCheck(canonical(await eventCounts(start))===canonical({steam:1})&&traffic.filter(r=>r.method==='POST').length===1,'one_source_only_write');requireCheck(!pageErrors&&!unexpectedBridge&&!forbidden,'runtime_or_scope_errors');
  Object.assign(report,{status:'passed',stage:'complete',revision_before:before.revision,revision_after:after.revision,event_counts:await eventCounts(start),checks:['library_handoff_review_no_write','source_tabs_retain_inputs','explicit_steam_import_same_uuid','manual_overrides_references_analysis_preserved','narrow_135_reduced_motion']});
 }catch{report.status='failed';report.error='entry_assertion_failed';}
 finally{await context?.close();if(server)await new Promise<void>(resolve=>server!.close(()=>resolve()));Object.assign(report,{pageErrors,unexpectedBridge,forbidden,blockedImages,source_unchanged:source===await treeHash(ROOT+'/src'),bundle_unchanged:bundle===await treeHash(ROOT+'/out/renderer'),controls_unchanged:canonical(controlBefore)===canonical(await controls())});if(!report.source_unchanged||!report.bundle_unchanged||!report.controls_unchanged)report.status='failed';await checkpoint(String(report.stage));console.log(JSON.stringify({status:report.status,stage:report.stage,ledger}));}
 expect(report.status).toBe('passed');
});
