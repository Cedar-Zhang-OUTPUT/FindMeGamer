import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { readFile, writeFile, readdir, lstat } from 'node:fs/promises';
import { createServer, type Server } from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { MatchClient } from '../src/main/match-client';
import { authenticatedMatchRequest } from '../src/main/match-transport';
import { OutreachClient } from '../src/main/outreach-client';
import { authenticatedOutreachRequest } from '../src/main/outreach-transport';
import { DraftsClient } from '../src/main/drafts-client';
import { authenticatedDraftsRequest } from '../src/main/drafts-transport';
import { SendingClient } from '../src/main/sending-client';
import { authenticatedSendingRequest } from '../src/main/sending-transport';
import { CollaborationClient } from '../src/main/collaboration-client';
import { authenticatedCollaborationRequest } from '../src/main/collaboration-transport';
import { GameClient } from '../src/main/game-client';
import { LibraryClient } from '../src/main/library-client';
import { SavedSetClient } from '../src/main/saved-set-client';
import { authenticatedSavedSetRequest } from '../src/main/saved-set-transport';
import { SettingsClient } from '../src/main/settings-client';
import { CreatorClient } from '../src/main/creator-client';
import { authenticatedCreatorRequest } from '../src/main/creator-transport';
import { authenticatedSettingsRequest } from '../src/main/settings-transport';
import { authenticatedGet, authenticatedGameRequest, publicResult, type Fetcher } from '../src/main/transport';


test.use({trace:'off',screenshot:'off',video:'off'});
const PRIVATE='/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-3g7w9lta/private';
const ORIGIN='http://127.0.0.1:60016',PIN='6d8425a99d7bd050424904a1492166b14f2ee5ac';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const safe=(value:unknown,code:string)=>{if(!value)throw Error(code);};
// Explicit UI-driven synthetic journey. No settings, source, SMTP or delivery writes.
test('Missing sender remains a qualification-only gate with local repair navigation',async({browser},info)=>{
 test.skip(process.env.FMG_MEETING_MISSING_SENDER!=='60016','Exclusive synthetic fixture only');test.setTimeout(180_000);
 safe(((await lstat(PRIVATE+'/client.json')).mode&0o077)===0,'private_permissions');
 const config=JSON.parse(await readFile(PRIVATE+'/client.json','utf8'));
 const ids=JSON.parse(await readFile(PRIVATE+'/meeting-report.json','utf8'));
 safe(config.base_url===ORIGIN&&config.backend_revision===PIN&&config.migration==='20260909_0021','fixture_pin');
 const run=randomUUID(),ledger=PRIVATE+'/prd-ui-'+run+'.json';let activityName='Meeting UI '+run.slice(0,8);
 const report:Record<string,any>={status:'running',stage:'start',screenshots:[],http:{},owned:[],native:false};
 const activities=new Set<string>([ids.activity_id]),queries=new Set<string>(),compositions=new Set<string>(),templates=new Set<string>(),draftIds=new Set<string>();
 async function smtpState(){try{return(await readFile(PRIVATE+'/state/smtp-events.jsonl')).toString('base64');}catch(error){if((error as NodeJS.ErrnoException).code==='ENOENT')return 'absent';throw error;}}
 const baseline=await smtpState();
 let page:Page|undefined,context:BrowserContext|undefined,server:Server|undefined;
 async function checkpoint(stage:string){report.stage=stage;await writeFile(ledger,JSON.stringify(report,null,2),{mode:0o600});}
 const fetcher:Fetcher=async(url,init)=>{
  const u=new URL(url),method=init.method??'GET';safe(u.origin===ORIGIN,'origin');
  const a=/^\/api\/v2\/activities\/([^/]+)(.*)$/.exec(u.pathname);
  const q=/^\/api\/v2\/discovery\/queries\/([^/]+)\/(?:stop|continue)$/.exec(u.pathname);
  const c=/^\/api\/v2\/outreach\/compositions\/([^/]+)\/qualification$/.exec(u.pathname);
  const d=/^\/api\/v2\/outreach\/drafts\/([^/]+)\/refresh$/.exec(u.pathname);
  const read=method==='GET'&&/^\/api\/(v1\/(session|settings\/|outreach\/smtp)|v2\/)/.test(u.pathname);
  const write=method==='POST'&&c&&compositions.has(c[1]);
  safe(read||write,'write_scope');
  const family=method+' '+u.pathname.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi,':id');report.http[family]=(report.http[family]??0)+1;
  return fetch(u,{...init,signal:AbortSignal.any([AbortSignal.timeout(20000),...(init.signal?[init.signal]:[])])});
 };
 const connection={serviceUrl:ORIGIN,key:config.workspace_key};
 const match=new MatchClient(r=>authenticatedMatchRequest(fetcher,connection,r)),outreach=new OutreachClient(r=>authenticatedOutreachRequest(fetcher,connection,r));
 const drafts=new DraftsClient(r=>authenticatedDraftsRequest(fetcher,connection,r)),sending=new SendingClient(r=>authenticatedSendingRequest(fetcher,connection,r));
 const collaboration=new CollaborationClient(r=>authenticatedCollaborationRequest(fetcher,connection,r)),games=new GameClient(r=>authenticatedGameRequest(fetcher,connection,r));
 const creators=new CreatorClient(r=>authenticatedCreatorRequest(fetcher,connection,r)),savedSets=new SavedSetClient(r=>authenticatedSavedSetRequest(fetcher,connection,r));
 const library=new LibraryClient((r,q)=>authenticatedGet(fetcher,connection,r,q)),settings=new SettingsClient(r=>authenticatedSettingsRequest(fetcher,connection,r));
 const clients:Record<string,any>={match,outreach,drafts,sending,collaboration,games,creators,savedSets,library,settings};
 const allowed:Record<string,string[]>={match:['activities','activity','createActivity','updateBrief','plans','plan','createPlan','query','candidates','stop','continueDiscovery','evaluations','evaluation','evaluationResults'],outreach:['selections','selection','add','bulk','update','cancel','batches','batch','freeze'],drafts:['templates','template','registerCanonical','compositions','composition','createComposition','refresh'],sending:['batches','batch','qualify'],collaboration:['list','detail','creatorHistory'],games:['list','detail'],creators:['list','detail','works'],savedSets:['list'],library:['list','detail'],settings:['collection','smtp']};
 const game=await games.detail('242a25ed-8d33-441a-9586-7f76112dc0c2');report.game_id=game.id;
 const originalActivity=await match.activity(ids.activity_id),originalPlan=await match.plan(ids.plan_id),originalGame=JSON.stringify(game);
 const oldComposition=await drafts.composition(ids.missing_sender_composition_id);compositions.add(oldComposition.id);
 const actions:Record<string,(v?:any)=>Promise<any>>={
  'connection.status':async()=>({serviceUrl:ORIGIN,hasKey:true,storageAvailable:true}),
  'connection.test':async()=>{await library.session();return{authenticated:true,proxy:'system',route:'direct'};},
  'preferences.read':async()=>({appearance:'system',fontSize:'default',automaticUpdates:false}),
  'updates.status':async()=>({phase:'development',installedVersion:'0.2.0-internal.3',lastCheckedAt:null,lastAttemptAt:null,release:null,error:null})
 };
 for(const[group,methods]of Object.entries(allowed))for(const method of methods)actions[group+'.'+method]=async input=>{
  if(group==='match'&&method==='createActivity')safe(input.data.name===activityName&&input.data.game_id===game.id,'create_intent');
  if(input?.activityId)safe(activities.has(input.activityId),'activity_scope');
  if(group==='drafts'&&method==='registerCanonical')safe(input.gameId===game.id,'template_scope');
  const value=await clients[group][method](input);
  if(group==='match'&&method==='createActivity'){activities.add(value.id);report.activity_id=value.id;report.owned.push(value.id);}
  if(group==='match'&&method==='plan'&&value.query_id)queries.add(value.query_id);
  if(group==='drafts'&&method==='registerCanonical')templates.add(value.id);
  if(group==='drafts'&&method==='createComposition'){compositions.add(value.id);report.composition_id=value.id;value.drafts.forEach((draft:any)=>draftIds.add(draft.id));}
  return value;
 };
 try{
  server=createServer(async(req,res)=>{const base=ROOT+'/out/renderer',file=path.resolve(base,req.url==='/'?'index.html':String(req.url).split('?')[0].replace(/^\/+/,''));if(req.method!=='GET'||!file.startsWith(base+'/')){res.writeHead(403).end();return;}try{const mime:Record<string,string>={'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml','.woff2':'font/woff2'};res.writeHead(200,{'Content-Type':mime[path.extname(file)]??'application/octet-stream'});res.end(await readFile(file));}catch{res.writeHead(404).end();}});
  await new Promise<void>(r=>server!.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+(server.address() as AddressInfo).port;
  context=await browser.newContext({viewport:{width:1440,height:1080},reducedMotion:'reduce'});await context.route('**/*',route=>route.request().url().startsWith(origin+'/')||/^(data:|about:)/.test(route.request().url())?route.continue():route.abort());
  page=await context.newPage();page.setDefaultTimeout(15000);let errors=0;page.on('pageerror',()=>errors++);
  await page.exposeBinding('__fmgInvoke',async(_source,name:string,value:unknown)=>{safe(Boolean(actions[name]),'bridge_'+name.replaceAll('.','_'));return publicResult(()=>actions[name](value));});
  await page.addInitScript(({allowed})=>{
   const group=(name:string,methods:string[])=>Object.fromEntries(methods.map(method=>[method,(v?:unknown)=>(window as any).__fmgInvoke(name+'.'+method,v)]));
   const bridge:Record<string,unknown>={connection:group('connection',['status','test']),preferences:group('preferences',['read']),updates:group('updates',['status'])};
   for(const[name,methods]of Object.entries(allowed))bridge[name]=group(name,methods);
   Object.defineProperty(window,'desktop',{value:bridge});
  },{allowed});
  async function shot(name:string){const file=info.outputPath(name+'.png');await page!.screenshot({path:file});report.screenshots.push(file);}
  await page.goto(origin);await expect(page.getByText('Workspace connected',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Match',exact:true}).click();
  await page.getByRole('button',{name:'Open '+originalActivity.name,exact:true}).click();
  await checkpoint('missing_sender');
  await page.getByRole('button',{name:'Draft history',exact:true}).click();
  const open=page.getByRole('button',{name:'Open draft set',exact:true});await expect(open.first()).toBeVisible();await open.last().click();
  await expect(page.getByRole('navigation',{name:'Draft people'})).toBeVisible();
  await page.getByRole('button',{name:'Review sending',exact:true}).click();
  const review=page.getByRole('region',{name:'Review recipients',exact:true});
  await expect(review.getByRole('button',{name:'Email settings',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:/^Send [0-9]+ email/})).toHaveCount(0);await shot('missing-sender-repair');
  await review.getByRole('button',{name:'Email settings',exact:true}).click();await expect(page.getByRole('tab',{name:/^Email/})).toHaveAttribute('aria-selected','true');await shot('email-settings');
  await page.getByRole('button',{name:'Return to Match',exact:true}).click();await expect(review).toBeVisible();
  await review.getByRole('button',{name:'Use current template',exact:true}).click();
  await page.getByRole('alertdialog').getByRole('button',{name:'Discard changes',exact:true}).click();
  const template=page.getByRole('region',{name:'Email template',exact:true});await expect(template).toBeVisible();
  const preview=await template.getByTitle('Template preview').getAttribute('srcdoc');
  safe(preview?.includes(game.name!)&&!preview.includes('Synthetic Demo Sender')&&!preview.includes('Toki'),'neutral_preview');
  await expect(template.getByRole('button',{name:'Create 1 drafts',exact:true})).toBeEnabled();await shot('neutral-template');
  safe(errors===0,'page_errors');safe(baseline===await smtpState(),'no_smtp');report.status='passed';await checkpoint('complete');
 }catch(error){report.status='failed';report.failure=error instanceof Error?error.message.slice(0,1500):'unknown';if(page)await page.screenshot({path:info.outputPath('failure.png')}).catch(()=>{});await checkpoint(String(report.stage));}
 finally{await context?.close();if(server)await new Promise<void>(r=>server!.close(()=>r()));await writeFile(ledger,JSON.stringify(report,null,2),{mode:0o600});console.log(JSON.stringify({status:report.status,stage:report.stage,ledger}));}
 expect(report.status,'PRD workflow '+report.stage).toBe('passed');
});
