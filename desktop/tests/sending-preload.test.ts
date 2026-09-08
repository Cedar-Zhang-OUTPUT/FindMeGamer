import {expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
const mocks=vi.hoisted(()=>({expose:vi.fn(),invoke:vi.fn(async()=>({ok:true,data:null}))}));
vi.mock('electron',()=>({contextBridge:{exposeInMainWorld:mocks.expose},ipcRenderer:{invoke:mocks.invoke}}));
it('exposes exactly six sending operations with no generic request',async()=>{
  await import('../src/preload/index');const [,api]=mocks.expose.mock.calls[0] as [string,DesktopBridge];
  expect(api).toHaveProperty('sending');expect(Object.keys(api.sending).sort()).toEqual(['batch','batches','qualify','resolve','retry','send']);
  for(const method of ['qualify','send','batches','batch','retry','resolve'] as const){const input={id:'only-this-record'};await (api.sending[method] as (value:unknown)=>Promise<unknown>)(input);expect(mocks.invoke).toHaveBeenLastCalledWith(`sending:${method}`,input);}
});
