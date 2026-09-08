import {expect,it,vi} from 'vitest';
import {WorkspaceGateway} from '../src/main/gateway';
import {publicResult} from '../src/main/transport';
import {ACTIVITY_ID,CANDIDATE_ID} from './match-fixtures';
const create={method:'POST' as const,path:`/api/v2/activities/${ACTIVITY_ID}/selections`,body:{candidate_id:CANDIDATE_ID},idempotencyKey:'f7-selection-key'};
function store(){return {status:vi.fn(async()=>({serviceUrl:'https://workspace.test',hasKey:true,storageAvailable:true})),getConnection:vi.fn(async()=>({serviceUrl:'https://workspace.test',key:'test-key'})),save:vi.fn(async()=>{}),clear:vi.fn(async()=>{})};}
it('rejects outreach paths outside preparation before reading credentials',async()=>{
  const storage=store(),fetcher=vi.fn(),gateway=new WorkspaceGateway(storage,fetcher);
  expect(gateway).toHaveProperty('outreachRequest');
  await expect(gateway.outreachRequest({...create,path:'/api/v2/outreach/send'})).rejects.toMatchObject({code:'request_invalid'});
  expect(storage.getConnection).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it.each([200,401])('cannot apply an outreach receipt from replaced credentials (%s)',async status=>{
  let finish!:(value:Response)=>void;const fetcher=vi.fn(()=>new Promise<Response>(resolve=>finish=resolve));
  const gateway=new WorkspaceGateway(store(),fetcher);expect(gateway).toHaveProperty('outreachRequest');
  const pending=gateway.outreachRequest(create);
  await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledOnce());await gateway.save({serviceUrl:'https://replacement.test',key:'replacement-key'});
  finish(new Response('{}',{status}));await expect(pending).rejects.toMatchObject({code:'connection_changed',retryable:false});
  expect(fetcher).toHaveBeenCalledOnce();
});
it('sanitizes failed preparation credential access without dispatch',async()=>{
  const storage=store(),fetcher=vi.fn(),gateway=new WorkspaceGateway(storage,fetcher);expect(gateway).toHaveProperty('outreachRequest');
  storage.getConnection.mockRejectedValue(Error('private key material'));
  const result=await publicResult(()=>gateway.outreachRequest(create));
  expect(result).toMatchObject({ok:false,error:{code:'secure_storage_unavailable'}});expect(JSON.stringify(result)).not.toContain('private key material');expect(fetcher).not.toHaveBeenCalled();
});
