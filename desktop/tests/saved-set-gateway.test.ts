import {expect,it,vi} from 'vitest';
import {WorkspaceGateway} from '../src/main/gateway';
import {publicResult} from '../src/main/transport';
import {QUERY_ID} from './match-fixtures';
import {savedSetCreateFixture,SET_KEY} from './saved-set-fixtures';
import type {SavedSetRequest} from '../src/main/saved-set-transport';
const create:SavedSetRequest={method:'POST',path:`/api/v2/discovery/queries/${QUERY_ID}/saved-sets`,body:savedSetCreateFixture(),idempotencyKey:SET_KEY};
function store(){return {status:vi.fn(async()=>({serviceUrl:'https://workspace.test',hasKey:true,storageAvailable:true})),getConnection:vi.fn(async()=>({serviceUrl:'https://workspace.test',key:'test-key'})),save:vi.fn(async()=>{}),clear:vi.fn(async()=>{})};}
it('validates named-set input before touching credentials',async()=>{
  const storage=store(),fetcher=vi.fn(),gateway=new WorkspaceGateway(storage,fetcher);
  await expect(gateway.savedSetRequest({...create,path:'/api/v2/outreach/send'})).rejects.toMatchObject({code:'request_invalid'});
  expect(storage.getConnection).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it.each([200,401])('fences a saved-set response after connection replacement (%s)',async status=>{
  let finish!:(value:Response)=>void;const fetcher=vi.fn(()=>new Promise<Response>(resolve=>finish=resolve));
  const gateway=new WorkspaceGateway(store(),fetcher),pending=gateway.savedSetRequest(create);
  await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledOnce());await gateway.save({serviceUrl:'https://new.test',key:'new-key'});
  finish(new Response('{}',{status}));await expect(pending).rejects.toMatchObject({code:'connection_changed',retryable:false});expect(fetcher).toHaveBeenCalledOnce();
});
it('does not expose Keychain errors or dispatch when credential access fails',async()=>{
  const storage=store(),fetcher=vi.fn();storage.getConnection.mockRejectedValue(Error('private storage error'));
  const result=await publicResult(()=>new WorkspaceGateway(storage,fetcher).savedSetRequest(create));
  expect(result).toMatchObject({ok:false,error:{code:'secure_storage_unavailable'}});expect(JSON.stringify(result)).not.toContain('private storage error');expect(fetcher).not.toHaveBeenCalled();
});
