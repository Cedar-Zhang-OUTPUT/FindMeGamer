import {expect,it,vi} from 'vitest';
import type {CollectionSettings} from '../src/shared/settings';
import {MatchClient} from '../src/main/match-client';
import {queryFixture as wireQuery} from './match-fixtures';
import {queryFixture} from './match-api-mock';
import {canContinueWithCollection,eligiblePlatforms,collectionLabel} from '../src/renderer/components/match/collectionPolicy';

const policy=():CollectionSettings=>({items:[
  {platform:'youtube',enabled:false,implemented:true,credentials_configured:true,availability:'disabled'},
  {platform:'x',enabled:true,implemented:true,credentials_configured:true,availability:'configured_unverified'},
  {platform:'twitch',enabled:true,implemented:false,credentials_configured:false,availability:'not_implemented'},
  {platform:'instagram',enabled:false,implemented:false,credentials_configured:false,availability:'disabled'},
]});
it('lets a selected enabled source continue when another source is administratively blocked',()=>{
  const query=queryFixture();query.conditions.providers.push({platform:'x',query:'indie'});query.sources={youtube:{status:'more',blocked_reason:'collection_disabled'},x:{status:'more'}};
  expect(canContinueWithCollection(query,policy())).toBe(true);
});
it('allows four library sources and continues unscanned library pages while real-time is unavailable',()=>{
 expect(eligiblePlatforms(['youtube','x','twitch','instagram'],policy())).toEqual(['youtube','x','twitch','instagram']);
 const query=queryFixture();query.conditions.providers=[{platform:'twitch',query:'indie'}];query.sources={twitch:{status:'not_supported',library:{status:'more',scanned_count:50,added_count:5}}};
 expect(canContinueWithCollection(query,policy())).toBe(true);
 expect(canContinueWithCollection({...query,requests_reserved:120,scanned_reserved:6000},policy())).toBe(true);
 expect(canContinueWithCollection({...query,result_count:600},policy())).toBe(false);
 query.sources={twitch:{status:'not_supported',library:{status:'complete',scanned_count:50,added_count:5}}};expect(canContinueWithCollection(query,policy())).toBe(false);
});
it('does not use an enabled but unselected source or an unimplemented platform',()=>{
  expect(canContinueWithCollection(queryFixture(),policy())).toBe(false);
  expect(eligiblePlatforms(['youtube','twitch','instagram'],policy())).toEqual(['youtube','twitch','instagram']);
  expect(collectionLabel(policy().items[2])).toBe('Real-time data unavailable');
});
it('allows explicit continuation after re-enable without rewriting saved source status',()=>{
  const query=queryFixture();query.sources.youtube={status:'more',blocked_reason:'collection_disabled'};
  const settings=policy();settings.items[0]={...settings.items[0],enabled:true,availability:'configured_unverified'};
  expect(canContinueWithCollection(query,settings)).toBe(true);
  expect(query.sources.youtube).toEqual({status:'more',blocked_reason:'collection_disabled'});
});
it('keeps quota and exhausted-source limits even when a channel is enabled',()=>{
  const settings=policy();settings.items[0]={...settings.items[0],enabled:true,availability:'configured_unverified'};
  expect(canContinueWithCollection({...queryFixture(),requests_reserved:120},settings)).toBe(false);
  expect(canContinueWithCollection({...queryFixture(),sources:{youtube:{status:'exhausted'}}},settings)).toBe(false);
  const query=queryFixture();query.conditions.providers.push({platform:'x',query:'indie'});query.sources={youtube:{status:'more',blocked_reason:'collection_disabled'},x:{status:'exhausted'}};
  expect(canContinueWithCollection(query,policy())).toBe(false);
});
it('requires a known policy and saved credentials without claiming verified access',()=>{
  expect(eligiblePlatforms(['x'],null)).toEqual(['x']);
  const settings=policy();settings.items[1]={...settings.items[1],credentials_configured:false,availability:'missing_connection'};
  expect(eligiblePlatforms(['x'],settings)).toEqual(['x']);
  expect(collectionLabel(settings.items[1])).toBe('Credentials needed');
  expect(collectionLabel(policy().items[1])).toBe('Access unverified');
});
it.each([false,'enabled',{},null])('rejects a malformed source blocked_reason: %j',async blocked_reason=>{
  const response=wireQuery();response.sources.youtube={status:'more',blocked_reason};
  await expect(new MatchClient(vi.fn(async()=>response)).query(response.id)).rejects.toMatchObject({code:'invalid_response'});
});
it('retains the administrative blocked reason alongside the original provider outcome',async()=>{
  const response=wireQuery();response.sources.youtube={status:'partial',coverage:'partial',issues:[],blocked_reason:'collection_disabled'};
  const result=await new MatchClient(vi.fn(async()=>response)).query(response.id);
  expect(result.sources.youtube).toEqual({status:'partial',coverage:'partial',issues:[],blocked_reason:'collection_disabled'});
});
it('validates independent Library source progress without discarding the real-time outcome',async()=>{
 const response=wireQuery();response.sources.youtube={status:'not_supported',library:{status:'more',scanned_count:200,added_count:20}};
 expect((await new MatchClient(vi.fn(async()=>response)).query(response.id)).sources).toEqual(response.sources);
 for(const library of [{status:'invented',scanned_count:0,added_count:0},{status:'more',scanned_count:-1,added_count:2},{status:'more',scanned_count:2,added_count:1,_cursor:'private'}]){
   response.sources.youtube=JSON.parse(JSON.stringify({status:'not_supported',library}));await expect(new MatchClient(vi.fn(async()=>response)).query(response.id)).rejects.toMatchObject({code:'invalid_response'});
 }
});
