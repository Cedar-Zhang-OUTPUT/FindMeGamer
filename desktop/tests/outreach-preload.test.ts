import {expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
const mocks=vi.hoisted(()=>({expose:vi.fn(),invoke:vi.fn(async()=>({ok:true,data:null}))}));
vi.mock('electron',()=>({contextBridge:{exposeInMainWorld:mocks.expose},ipcRenderer:{invoke:mocks.invoke}}));
it('exposes nine preparation methods, never a generic request or send method',async()=>{
  await import('../src/preload/index');
  const [,api]=mocks.expose.mock.calls[0] as [string,DesktopBridge];expect(api).toHaveProperty('outreach');
  expect(Object.keys(api.outreach).sort()).toEqual(['add','batch','batches','bulk','cancel','freeze','selection','selections','update']);
  for(const method of ['add','batch','batches','bulk','cancel','freeze','selection','selections','update'] as const){
    const input={activityId:'activity',id:'selection',data:{contact_id:null,confirm_public_name:false},idempotencyKey:'frozen-key'};
    await (api.outreach[method] as (value:unknown)=>Promise<unknown>)(input);
    expect(mocks.invoke).toHaveBeenLastCalledWith(`outreach:${method}`,input);
  }
});
