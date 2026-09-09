import {it,expect,vi} from 'vitest';
import {MatchClient} from '../src/main/match-client';
import {activityFixture,ACTIVITY_ID,GAME_ID} from './match-fixtures';
it('accepts a boolean initialization marker but rejects an ambiguous server value',async()=>{
 const value={...activityFixture(),initial_selection_initialized:true};
 expect(await new MatchClient(async()=>({...value,queries:[]})).activity(ACTIVITY_ID)).toEqual({...value,queries:[]});
 await expect(new MatchClient(async()=>({...value,initial_selection_initialized:'true',queries:[]})).activity(ACTIVITY_ID)).rejects.toMatchObject({code:'invalid_response'});
});
it('sends only an activity-scoped revision-checked brief update',async()=>{
 const response={...activityFixture(),revision:1,campaign_brief:'Cozy channels'},request=vi.fn(async()=>response),client=new MatchClient(request);
 expect(await client.updateBrief({id:ACTIVITY_ID,data:{campaign_brief:'Cozy channels',expected_revision:0}})).toEqual(response);
 expect(request).toHaveBeenCalledExactlyOnceWith({method:'PATCH',path:`/api/v2/activities/${ACTIVITY_ID}/campaign-brief`,body:{campaign_brief:'Cozy channels',expected_revision:0}});
});
it('preserves a new activity brief without adding it to game data',async()=>{
 const data={game_id:GAME_ID,name:'Game launch',campaign_brief:'Cozy channels'},response={...activityFixture(),revision:0,campaign_brief:data.campaign_brief},request=vi.fn(async()=>response);
 expect(await new MatchClient(request).createActivity({data,idempotencyKey:'brief-request-key'})).toEqual(response);expect(request).toHaveBeenCalledWith(expect.objectContaining({body:data}));
});
