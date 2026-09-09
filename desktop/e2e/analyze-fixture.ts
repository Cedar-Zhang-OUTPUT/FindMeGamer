import {readFile,writeFile,readdir,lstat} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {AnalysisClient} from '../src/main/analyze-client';
import {authenticatedAnalysisRequest} from '../src/main/analyze-transport';
import {GameClient} from '../src/main/game-client';
import {CreatorClient} from '../src/main/creator-client';
import {LibraryClient} from '../src/main/library-client';
import {SettingsClient} from '../src/main/settings-client';
import {authenticatedCreatorRequest} from '../src/main/creator-transport';
import {authenticatedSettingsRequest} from '../src/main/settings-transport';
import {authenticatedGet,authenticatedGameRequest,type Fetcher} from '../src/main/transport';
export const PRIVATE='/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-xmmhoufp/private';
export const ORIGIN='http://127.0.0.1:64692',PIN='5706ad76f924991b80ee2a7fb6806528366be5ce';
export const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export const requireCheck=(value:unknown,code:string)=>{if(!value)throw new Error(code);};
export const sha=(value:Buffer|string)=>createHash('sha256').update(value).digest('hex');
export function canonical(value:unknown):string {if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>JSON.stringify(k)+':'+canonical(v)).join(',')+'}';return JSON.stringify(value);}
export async function treeHash(directory:string){const h=createHash('sha256');async function walk(dir:string){for(const entry of (await readdir(dir,{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))){const full=path.join(dir,entry.name);if(entry.isDirectory())await walk(full);else if(entry.isFile()){h.update(path.relative(directory,full));h.update(await readFile(full));}}}await walk(directory);return h.digest('hex');}
async function privateJSON(name:string){const full=PRIVATE+'/'+name,stat=await lstat(full);requireCheck(stat.isFile()&&!stat.isSymbolicLink()&&(stat.mode&0o777)===0o600,'private_permissions');return JSON.parse(await readFile(full,'utf8'));}
export async function events(){return (await readFile(PRIVATE+'/state/events.jsonl','utf8')).split('\n').filter(Boolean).map(line=>JSON.parse(line) as {endpoint:string;status:number});}
export async function eventCounts(offset:number){const counts:Record<string,number>={};for(const e of (await events()).slice(offset))counts[e.endpoint]=(counts[e.endpoint]??0)+1;return counts;}
export async function controls(){const data:Record<string,string>={};for(const name of (await readdir(PRIVATE+'/state')).filter(n=>/control\.json$/.test(n)).sort())data[name]=sha(await readFile(PRIVATE+'/state/'+name));return data;}
export async function analyzeFixture(kind:'api'|'renderer',readOnly=false){
 const config=await privateJSON('client.json'),ids=await privateJSON('analyze-report.json');
 requireCheck(config.base_url===ORIGIN&&config.backend_revision===PIN&&config.migration==='20260908_0019'&&ids.backend_revision===PIN,'fixture_pin');
 for(const id of [ids.game_id,ids.youtube_id,ids.x_id,...ids.jobs])requireCheck(typeof id==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(id),'fixture_ids');
 const control=await privateJSON('state/analyze-control.json');requireCheck(control.stage==='none'&&control.mode==='none','fault_control_not_idle');
 const run=randomUUID(),ledger=PRIVATE+`/analyze-${kind}-${run}.json`,http:Record<string,number>={},writes:{path:string;body_hash:string;key_hash:string;status?:number}[]=[];
 const report:Record<string,unknown>={status:'running',stage:'bootstrap',evidence:kind==='renderer'?'headless-built-renderer-restricted-production-node-clients':'real-production-clients-read-only',read_only:kind==='api'||readOnly,backend_revision:PIN,fixture:{game_id:ids.game_id,youtube_id:ids.youtube_id,x_id:ids.x_id},checks:[],screenshots:[]};
 const source=await treeHash(ROOT+'/src'),bundle=await treeHash(ROOT+'/out/renderer'),controlBefore=await controls();Object.assign(report,{source_hash:source,bundle_hash:bundle});
 let permittedImport=false,permittedTarget:string|null=null,forbiddenHTTP=0;
 const targetURLs=['https://store.steampowered.com/app/900000001','https://www.youtube.com/channel/UCanalyzeFixture01','https://x.com/i/user/900000001'];
 const fetcher:Fetcher=async(url,init)=>{
  const u=new URL(url),method=init.method??'GET';let allowed=method==='GET'&&/^\/api\/(?:v1\/(?:session$|jobs(?:\/|$)|settings\/|profiles\/)|v2\/library\/(?:games|creators)(?:\/|$))/.test(u.pathname);
  let write:typeof writes[number]|undefined;
  if(kind==='renderer'&&!readOnly&&method==='POST'){
   const body=JSON.parse(String(init.body));
   if(permittedImport&&u.pathname==='/api/v2/library/games/steam-import'){allowed=body.url===targetURLs[0]&&body.game_id===ids.game_id&&Number.isInteger(body.expected_revision)&&Object.keys(body).sort().join(',')==='expected_revision,game_id,url';permittedImport=false;}
   if(permittedTarget&&u.pathname==='/api/v1/jobs/analysis'){allowed=body.url===permittedTarget&&targetURLs.includes(body.url)&&body.mode==='reanalyze'&&body.target_type===(body.url===targetURLs[0]?'game':'creator')&&Object.keys(body).sort().join(',')==='mode,target_type,url';permittedTarget=null;}
   if(allowed){const key=new Headers(init.headers).get('Idempotency-Key');requireCheck(key,'missing_idempotency_key');write={path:u.pathname,body_hash:sha(canonical(body)),key_hash:sha(key!)};writes.push(write);}
  }
  if(u.origin!==ORIGIN||!allowed){forbiddenHTTP++;throw new Error('http_scope');}
  const family=`${method} ${u.pathname.replace(/[a-f0-9]{8}-[a-f0-9-]{27}/gi,':id')}`;http[family]=(http[family]??0)+1;
  const result=await fetch(u,{...init,signal:AbortSignal.any([AbortSignal.timeout(20_000),...(init.signal?[init.signal]:[])])});if(write)write.status=result.status;return result;
 };
 const connection={serviceUrl:ORIGIN,key:config.workspace_key};
 const analysis=new AnalysisClient(r=>authenticatedAnalysisRequest(fetcher,connection,r)),games=new GameClient(r=>authenticatedGameRequest(fetcher,connection,r)),creators=new CreatorClient(r=>authenticatedCreatorRequest(fetcher,connection,r)),library=new LibraryClient((r,q)=>authenticatedGet(fetcher,connection,r,q)),settings=new SettingsClient(r=>authenticatedSettingsRequest(fetcher,connection,r));
 async function checkpoint(stage:string){report.stage=stage;await writeFile(ledger,JSON.stringify({...report,http_counts:http,writes},null,2),{mode:0o600});}
 async function finish(){Object.assign(report,{http_counts:http,writes,forbidden_http:forbiddenHTTP,source_hash_after:await treeHash(ROOT+'/src'),bundle_hash_after:await treeHash(ROOT+'/out/renderer'),controls_unchanged:canonical(await controls())===canonical(controlBefore)});if(source!==report.source_hash_after||bundle!==report.bundle_hash_after||!report.controls_unchanged||forbiddenHTTP){report.status='failed';report.final_error='freeze_or_scope_changed';}await checkpoint(String(report.stage));console.log(JSON.stringify({status:report.status,stage:report.stage,ledger}));}
 return {ids,run,ledger,report,http,writes,analysis,games,creators,library,settings,checkpoint,finish,permitImport:()=>{permittedImport=true;},permitAnalyze:(url:string)=>{requireCheck(targetURLs.includes(url),'target_scope');permittedTarget=url;}};
}
