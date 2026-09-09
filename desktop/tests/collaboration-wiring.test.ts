import {expect,it,vi} from 'vitest';
import {WorkspaceGateway} from '../src/main/gateway';
import type {DesktopBridge} from '../src/shared/bridge';
import {collaborationIds} from './collaboration-fixtures';
const mocks=vi.hoisted(()=>({expose:vi.fn(),invoke:vi.fn(async()=>({ok:true,data:null}))}));
vi.mock('electron',()=>({contextBridge:{exposeInMainWorld:mocks.expose},ipcRenderer:{invoke:mocks.invoke}}));
it('exposes only five invitation operations through isolated preload',async()=>{
 await import('../src/preload/index');const [,api]=mocks.expose.mock.calls[0] as [string,DesktopBridge];
 expect(Object.keys(api.collaboration).sort()).toEqual(['creatorHistory','detail','list','respond','update']);
 for(const method of ['creatorHistory','detail','list','respond','update'] as const){const input={activityId:'scoped'};await (api.collaboration[method] as (v:unknown)=>Promise<unknown>)(input);expect(mocks.invoke).toHaveBeenLastCalledWith(`collaboration:${method}`,input);}
});
it('validates before credentials and fences late collaboration writes after replacement',async()=>{
 const store={status:vi.fn(async()=>({serviceUrl:'https://workspace.test',hasKey:true,storageAvailable:true})),getConnection:vi.fn(async()=>({serviceUrl:'https://workspace.test',key:'test-key'})),save:vi.fn(async()=>{}),clear:vi.fn(async()=>{})};
 let finish!:(r:Response)=>void;const fetcher=vi.fn(()=>new Promise<Response>(done=>finish=done)),gateway=new WorkspaceGateway(store,fetcher);
 await expect(gateway.collaborationRequest({method:'GET',path:'/not-allowed'})).rejects.toMatchObject({code:'request_invalid'});expect(store.getConnection).not.toHaveBeenCalled();
 const pending=gateway.collaborationRequest({method:'POST',path:`/api/v2/activities/${collaborationIds.activity}/invitations/${collaborationIds.selection}/update`,body:{expected_revision:0,notes:'Saved'},idempotencyKey:'c-original-key'});
 await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledOnce());await gateway.save({serviceUrl:'https://replacement.test',key:'replacement-key'});finish(new Response('{}'));
 await expect(pending).rejects.toMatchObject({code:'connection_changed',retryable:false});
});
