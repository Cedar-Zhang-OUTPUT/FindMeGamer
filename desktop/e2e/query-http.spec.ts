import {expect,test} from '@playwright/test';
import {readFile,stat} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {CreatorClient} from '../src/main/creator-client';
import {authenticatedCreatorRequest} from '../src/main/creator-transport';
import {GameClient} from '../src/main/game-client';
import {authenticatedGameRequest,type Connection,type Fetcher} from '../src/main/transport';
import {MatchClient} from '../src/main/match-client';
import {authenticatedMatchRequest} from '../src/main/match-transport';
import {SavedSetClient} from '../src/main/saved-set-client';
import {authenticatedSavedSetRequest} from '../src/main/saved-set-transport';
import type {QueryView} from '../src/shared/match';
import {defaultConditions} from '../src/renderer/components/match/discoveryConditionState';

// Only real production adapters against the separately accepted synthetic HTTP
// fixture. No Electron/Keychain/package acceptance is inferred from this test.
test.use({trace:'off',screenshot:'off',video:'off'});
const ORIGIN='http://127.0.0.1:65164',PIN='a852307d6908e671ae1998c9741f19ffe65f5048';
const UUID='[0-9a-f-]{36}';
interface Fixture{base_url:string;backend_revision:string;migration:string;workspace_key:string;game_id:string;reference_work_ids:string[]}
test('full server queries and immutable named membership through real authenticated adapters',async()=>{
  test.setTimeout(120_000);
  const file=process.env.FMG_QUERY_FIXTURE_FILE;
  test.skip(!file,'Requires exclusive coordinator handoff of the pinned query fixture.');if(!file)return;
  const directory=path.dirname(path.resolve(file));expect(path.basename(file)).toBe('client.json');
  expect((await stat(file)).mode&0o777).toBe(0o600);expect((await stat(directory)).mode&0o777).toBe(0o700);
  let fixture:Fixture;
  try{fixture=JSON.parse(await readFile(file,'utf8'));}catch{throw Error('Private fixture unavailable; sensitive details suppressed.');}
  expect(fixture.base_url).toBe(ORIGIN);expect(fixture.backend_revision).toBe(PIN);expect(fixture.migration).toBe('20260908_0015');
  expect(typeof fixture.workspace_key==='string'&&fixture.workspace_key.length>0).toBe(true);
  const records:{method:string;path:string}[]=[];
  const fetcher:Fetcher=async(url,init)=>{
    const target=new URL(url),method=init.method??'GET';
    const allowedRead=method==='GET'&&/^\/api\/v2\/(library\/(creators|games)(\/|$)|activities(\/|$)|discovery\/)/.test(target.pathname);
    const allowedWrite=method==='POST'&&(['/api/v2/activities','/api/v2/library/creators'].includes(target.pathname)||new RegExp(`^/api/v2/activities/${UUID}/discovery-plans$`).test(target.pathname)||new RegExp(`^/api/v2/discovery/queries/${UUID}/(continue|evaluations|saved-sets)$`).test(target.pathname));
    if(target.origin!==ORIGIN||(!allowedRead&&!allowedWrite))throw Error('Query test request escaped the exclusive fixture allowlist.');
    records.push({method,path:target.pathname});return fetch(target,{...init,signal:AbortSignal.any([AbortSignal.timeout(20_000),...(init.signal?[init.signal]:[])])});
  };
  const connection:Connection={serviceUrl:ORIGIN,key:fixture.workspace_key};
  const creators=new CreatorClient(input=>authenticatedCreatorRequest(fetcher,connection,input));
  const games=new GameClient(input=>authenticatedGameRequest(fetcher,connection,input));
  const match=new MatchClient(input=>authenticatedMatchRequest(fetcher,connection,input));
  const sets=new SavedSetClient(input=>authenticatedSavedSetRequest(fetcher,connection,input));
  // Existing fixture language overrides were restored at handoff; seed only our
  // own manual records, never alter the smoke's Creator identities or fields.
  const aliasRecords=[];
  for(const language of ['en','English','英语'])aliasRecords.push(await creators.create({data:{platform:'youtube',account_id:`UCfixture-query-${randomUUID()}`,name:`Fixture · Query language ${language}`,languages:[language]},idempotencyKey:randomUUID()}));
  for(const sort of ['relevance','followers','recent_publish','recent_added'] as const){
    const all=await creators.list({platforms:['youtube','x','twitch','instagram'],languages:['en'],sort,limit:50,offset:0});
    expect(all.items.length).toBeGreaterThan(0);
    const page=await creators.list({platforms:['youtube','x','twitch','instagram'],languages:['en'],sort,limit:1,offset:1});
    expect(page.total).toBe(all.total);expect(page.items.map(item=>item.id)).toEqual(all.items.slice(1,2).map(item=>item.id));
    for(const item of all.items){expect(item.recent_works!.length).toBeLessThanOrEqual(3);expect(typeof item.active_email_count).toBe('number');}
  }
  const en=await creators.list({languages:['en'],sort:'recent_added',limit:50});
  expect(aliasRecords.every(record=>en.items.some(item=>item.id===record.id))).toBe(true);
  for(const language of ['English','英语'])expect((await creators.list({languages:[language],sort:'recent_added',limit:50})).items.map(item=>item.id)).toEqual(en.items.map(item=>item.id));
  for(const sort of ['name','recent_updated','recent_added'] as const){
    const all=await games.list({sort,websiteStatus:'all',limit:100});
    const available=await games.list({sort,websiteStatus:'available',limit:100}),missing=await games.list({sort,websiteStatus:'missing',limit:100});
    expect(available.total+missing.total).toBe(all.total);
    expect(missing.items.every(item=>!item.website_url?.trim())).toBe(true);
  }
  const activity=await match.createActivity({data:{name:`Query UI acceptance ${randomUUID().slice(0,8)}`,game_id:fixture.game_id,reference_work_ids:fixture.reference_work_ids},idempotencyKey:randomUUID()});
  const accepted=await match.createPlan({activityId:activity.id,data:{...defaultConditions(),batch_target:3,result_limit:6},idempotencyKey:randomUUID()});
  let queryId='';
  await expect.poll(async()=>{const plan=await match.plan(accepted.plan_id);queryId=plan.query_id??'';return plan.status;},{timeout:60_000}).toBe('ready');
  let query:QueryView|undefined;
  async function settled(){query=await match.query(queryId);return !['queued','running'].includes(query.status)&&!query.batches.some(batch=>['queued','running'].includes(batch.status));}
  await expect.poll(settled,{timeout:60_000}).toBe(true);
  const first=await match.candidates({queryId,sort:'relevance',evidence:'all',limit:100});expect(first.items.length).toBeGreaterThanOrEqual(2);
  const input={queryId,data:{request_id:randomUUID(),name:'  Explicit subset  ',candidate_ids:first.items.slice(0,2).map(item=>item.id)},idempotencyKey:randomUUID()};
  const saved=await sets.create(input);expect(saved.count).toBe(2);expect(saved.candidate_ids).toEqual(input.data.candidate_ids);expect(saved.name).toBe('Explicit subset');
  expect(await sets.create(input)).toEqual(saved);
  // Persistent request ID, not just temporary HTTP replay retention.
  expect(await sets.create({...input,idempotencyKey:randomUUID()})).toEqual(saved);
  if(query!.result_count<6){await match.continueDiscovery({queryId,data:{acknowledge_unknown:false},idempotencyKey:randomUUID()});await expect.poll(settled,{timeout:60_000}).toBe(true);}
  expect((await match.candidates({queryId,limit:100})).total).toBeGreaterThan(saved.count);
  const frozenQuery=await match.query(queryId),events=path.join(directory,'state','events.jsonl'),eventBytes=(await stat(events)).size;
  const writes=records.filter(record=>record.method==='POST').length;
  for(const sort of ['relevance','followers','recent_publish','recent_added'] as const){
    for(const evidence of ['all','current_game','reference_game','related_content','none'] as const){
      const results=await sets.results({id:saved.id,sort,evidence,limit:100,offset:0});
      expect(results.items.every(item=>saved.candidate_ids.includes(item.id))).toBe(true);
      const page=await sets.results({id:saved.id,sort,evidence,limit:1,offset:1});
      expect(page.total).toBe(results.total);expect(page.items.map(item=>item.id)).toEqual(results.items.slice(1,2).map(item=>item.id));
      const full=await match.candidates({queryId,sort,evidence,limit:100});
      const firstPage=await match.candidates({queryId,sort,evidence,limit:1,offset:0});
      expect(firstPage.total).toBe(full.total);expect(firstPage.items.map(item=>item.id)).toEqual(full.items.slice(0,1).map(item=>item.id));
    }
  }
  expect(await sets.detail(saved.id)).toEqual(saved);
  expect((await sets.list({activityId:activity.id})).items).toEqual([saved]);
  expect(await match.query(queryId)).toEqual(frozenQuery);expect((await stat(events)).size).toBe(eventBytes);
  expect(records.filter(record=>record.method==='POST')).toHaveLength(writes);
  expect(records.some(record=>/selection|outreach|smtp/.test(record.path))).toBe(false);
});
