import {expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
const mocks=vi.hoisted(()=>({expose:vi.fn(),invoke:vi.fn(async()=>({ok:true,data:null}))}));
vi.mock('electron',()=>({contextBridge:{exposeInMainWorld:mocks.expose},ipcRenderer:{invoke:mocks.invoke}}));
it('exposes only narrow, frozen Analyze methods without a generic IPC entry point',async()=>{
 await import('../src/preload/index');const [,api]=mocks.expose.mock.calls[0] as [string,DesktopBridge];
 expect(api).toHaveProperty('analysis');
 expect(Object.keys(api.analysis).sort()).toEqual(['bindYouTube','changed','create','detail','resume','retry','steamImport']);expect(Object.isFrozen(api.analysis)).toBe(true);
 for(const method of ['bindYouTube','changed','create','detail','resume','retry','steamImport'] as const){const input={id:'scoped-record'};await (api.analysis[method] as (v:unknown)=>Promise<unknown>)(input);expect(mocks.invoke).toHaveBeenLastCalledWith(`analysis:${method}`,input);}
});
