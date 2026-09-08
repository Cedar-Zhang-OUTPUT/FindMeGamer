import {expect,it,vi} from 'vitest';
import {GameClient} from '../src/main/game-client';
import {authenticatedGameRequest,type Fetcher} from '../src/main/transport';
import {gameFixture} from './game-fixtures';
const connection={serviceUrl:'https://workspace.example.com',key:'synthetic-test-key'};
it('sends explicit website/order query values and keeps server order and filtered total',async()=>{
  const fetcher=vi.fn<Fetcher>(async()=>Response.json({items:[gameFixture('Z'),gameFixture('A','44444444-4444-4444-8444-444444444444')],total:35,offset:24,limit:24}));
  const client=new GameClient(input=>authenticatedGameRequest(fetcher,connection,input));
  const result=await client.list({query:'cozy & fun',websiteStatus:'missing',sort:'recent_updated',onlyCollection:true,offset:24,limit:24});
  const url=new URL(fetcher.mock.calls[0][0] as string);
  expect(Object.fromEntries(url.searchParams)).toEqual({query:'cozy & fun',website_status:'missing',sort:'recent_updated',only_collection:'true',offset:'24',limit:'24'});
  expect(result.items.map(item=>item.name)).toEqual(['Z','A']);expect(result.total).toBe(35);expect(fetcher).toHaveBeenCalledOnce();
});
it.each([{websiteStatus:'configured'},{sort:'relevance'},{websiteStatus:false},{sort:['name']}])('rejects unsupported Game query input before network %j',async input=>{
  const request=vi.fn();await expect(new GameClient(request).list(input as never)).rejects.toMatchObject({code:'request_invalid'});expect(request).not.toHaveBeenCalled();
});
it('rejects direct transport enum tampering and query options on a detail route',async()=>{
  const fetcher=vi.fn();
  for(const request of [
    {method:'GET',path:'/api/v2/library/games',query:{sort:'relevance'}},
    {method:'GET',path:'/api/v2/library/games',query:{website_status:'configured'}},
    {method:'GET',path:`/api/v2/library/games/${gameFixture().id}`,query:{sort:'name'}},
  ])await expect(authenticatedGameRequest(fetcher,connection,request as never)).rejects.toMatchObject({code:'request_invalid'});
  expect(fetcher).not.toHaveBeenCalled();
});
it('accepts real created/updated timestamps without inventing them for legacy responses',async()=>{
  const current={...gameFixture(),created_at:'2026-09-07T12:00:00Z',updated_at:null};
  const request=vi.fn().mockResolvedValueOnce(current).mockResolvedValueOnce(gameFixture());
  const client=new GameClient(request);expect(await client.detail(current.id)).toEqual(current);
  const legacy=await client.detail(current.id);expect(legacy).not.toHaveProperty('created_at');expect(legacy).not.toHaveProperty('updated_at');
});
it.each(['yesterday',17,'2026-02-30T12:00:00Z'])('rejects malformed updated timestamps %j',async updated_at=>{
  await expect(new GameClient(async()=>({...gameFixture(),updated_at})).detail(gameFixture().id)).rejects.toMatchObject({code:'invalid_response'});
});
