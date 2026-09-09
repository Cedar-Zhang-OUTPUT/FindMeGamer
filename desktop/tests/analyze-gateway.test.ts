import {expect,it,vi} from 'vitest';
import {WorkspaceGateway} from '../src/main/gateway';
const jobId='a43324a4-3631-4735-9dba-6bc818d1dd86';
function store(){return {status:vi.fn(async()=>({serviceUrl:'https://workspace.test',hasKey:true,storageAvailable:true})),getConnection:vi.fn(async()=>({serviceUrl:'https://workspace.test',key:'test-key'})),save:vi.fn(async()=>{}),clear:vi.fn(async()=>{})};}
it('rejects out-of-scope Analyze requests before reading credentials',async()=>{
 const storage=store(),fetcher=vi.fn(),gateway=new WorkspaceGateway(storage,fetcher);
 expect(gateway).toHaveProperty('analysisRequest');
 await expect(gateway.analysisRequest({method:'GET',path:'/api/v1/jobs/arbitrary/private'})).rejects.toMatchObject({code:'request_invalid'});
 expect(storage.getConnection).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it.each([true,false])('fences late Analyze read/write after connection replacement (%s)',async read=>{
 let finish!:(r:Response)=>void;const fetcher=vi.fn(()=>new Promise<Response>(done=>finish=done)),gateway=new WorkspaceGateway(store(),fetcher);
 expect(gateway).toHaveProperty('analysisRequest');
 const pending=gateway.analysisRequest(read?{method:'GET',path:`/api/v1/jobs/${jobId}`}:{method:'POST',path:'/api/v1/jobs/analysis',body:{target_type:'creator',url:'https://x.com/i/user/900000001',mode:'reanalyze'},idempotencyKey:'analysis-frozen-intent'});
 await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledOnce());await gateway.save({serviceUrl:'https://replacement.test',key:'replacement-key'});finish(new Response('{}'));
 await expect(pending).rejects.toMatchObject({code:'connection_changed',retryable:read});expect(fetcher).toHaveBeenCalledOnce();
});
it('never dispatches Analyze after a failed secure-store read',async()=>{
 const storage=store();storage.getConnection.mockRejectedValue(new Error('private-storage-detail'));const fetcher=vi.fn(),gateway=new WorkspaceGateway(storage,fetcher);
 expect(gateway).toHaveProperty('analysisRequest');
 await expect(gateway.analysisRequest({method:'GET',path:`/api/v1/jobs/${jobId}`})).rejects.toMatchObject({code:'secure_storage_unavailable'});expect(fetcher).not.toHaveBeenCalled();
});
it('fences an Analyze write while its credential lookup is still pending',async()=>{
 const storage=store();let release!:(value:{serviceUrl:string;key:string})=>void;
 storage.getConnection.mockImplementation(()=>new Promise(resolve=>release=resolve));
 const fetcher=vi.fn(),gateway=new WorkspaceGateway(storage,fetcher);
 const pending=gateway.analysisRequest({method:'POST',path:`/api/v1/jobs/analysis/${jobId}/retry`,body:{},idempotencyKey:'analysis-retry-intent'});
 await vi.waitFor(()=>expect(storage.getConnection).toHaveBeenCalledOnce());await gateway.clear();release({serviceUrl:'https://workspace.test',key:'old-key'});
 await expect(pending).rejects.toMatchObject({code:'connection_changed',retryable:false});expect(fetcher).not.toHaveBeenCalled();
});
