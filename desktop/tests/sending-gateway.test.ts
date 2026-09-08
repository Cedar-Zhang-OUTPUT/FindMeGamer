import {expect,it,vi} from 'vitest';
import {WorkspaceGateway} from '../src/main/gateway';
import {draftIds} from './drafts-fixtures';
const qualify={method:'POST' as const,path:`/api/v2/outreach/compositions/${draftIds.composition}/qualification`,body:{excluded:[]}};
function store(){return {status:vi.fn(async()=>({serviceUrl:'https://workspace.test',hasKey:true,storageAvailable:true})),getConnection:vi.fn(async()=>({serviceUrl:'https://workspace.test',key:'test-key'})),save:vi.fn(async()=>{}),clear:vi.fn(async()=>{})};}
it('rejects out-of-scope sending paths before reading credentials',async()=>{
  const storage=store(),fetcher=vi.fn(),gateway=new WorkspaceGateway(storage,fetcher);
  expect(gateway).toHaveProperty('sendingRequest');
  await expect(gateway.sendingRequest({...qualify,path:'/api/v2/outreach/send-all'})).rejects.toMatchObject({code:'request_invalid'});
  expect(storage.getConnection).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it.each([true,false])('fences replaced credentials; qualification is a read and send is a write (%s)',async read=>{
  let finish!:(value:Response)=>void;const fetcher=vi.fn(()=>new Promise<Response>(resolve=>finish=resolve));
  const gateway=new WorkspaceGateway(store(),fetcher);expect(gateway).toHaveProperty('sendingRequest');
  const request=read?qualify:{...qualify,path:qualify.path.replace('qualification','send-batches'),body:{excluded:[],request_id:draftIds.request,qualification_token:'a'.repeat(64)},idempotencyKey:'p7-frozen-request'};
  const pending=gateway.sendingRequest(request);await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledOnce());
  await gateway.save({serviceUrl:'https://replacement.test',key:'replacement-key'});finish(new Response('{}'));
  await expect(pending).rejects.toMatchObject({code:'connection_changed',retryable:read});expect(fetcher).toHaveBeenCalledOnce();
});
