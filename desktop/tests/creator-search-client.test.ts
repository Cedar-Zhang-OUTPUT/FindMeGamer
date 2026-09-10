import {expect,it,vi} from 'vitest';
import {MatchClient} from '../src/main/match-client';
import {validateMatchRequest} from '../src/main/match-transport';
const id='11111111-1111-4111-8111-111111111111';
export const searchFixture=()=>({id,activity_id:id,plan_id:id,query_id:null,evaluation_id:null,parent_search_id:null,status:'queued' as const,stage:'planning' as const,counts:{discovered:0,profile_ready:0,profile_reused:0,profile_failed:0,email_available:0,email_missing:0,email_failed:0,evaluated:0,matched:0},stop_requested:false,retryable:false,outcome_unknown:false,error_code:null,created_at:'2026-09-10T00:00:00Z',updated_at:'2026-09-10T00:00:00Z'});
it('starts exactly one automatic search with no client-loaded candidate list',async()=>{
 const request=vi.fn(async()=>({search_id:id,status:'queued'}));const client=new MatchClient(request);
 await client.createCreatorSearch({activityId:id,data:{mode:'discover',platforms:['youtube']},idempotencyKey:'test-key-123'});
 expect(request).toHaveBeenCalledExactlyOnceWith({method:'POST',path:`/api/v2/activities/${id}/creator-searches`,body:{mode:'discover',platforms:['youtube']},idempotencyKey:'test-key-123'});
});
it('strictly validates automatic task reads and scope',async()=>{
 const raw=searchFixture(),request=vi.fn(async()=>raw);expect(await new MatchClient(request).creatorSearch(id)).toEqual(raw);
 for(const patch of [{stage:'fake_done'},{counts:{...raw.counts,matched:-1}},{secret:true}])await expect(new MatchClient(vi.fn(async()=>({...raw,...patch}))).creatorSearch(id)).rejects.toThrow();
});
it('rejects preview, caller-selected candidate IDs and nonempty stop/append bodies',()=>{
 for(const body of [{mode:'preview',platforms:['youtube']},{mode:'discover',platforms:['youtube'],candidate_ids:[id]}])expect(()=>validateMatchRequest({method:'POST',path:`/api/v2/activities/${id}/creator-searches`,body,idempotencyKey:'test-key-123'})).toThrow();
 expect(()=>validateMatchRequest({method:'POST',path:`/api/v2/creator-searches/${id}/stop`,body:{force:true},idempotencyKey:'test-key-123'})).toThrow();
});
