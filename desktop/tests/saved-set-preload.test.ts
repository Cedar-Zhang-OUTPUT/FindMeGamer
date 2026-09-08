import {expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
const mocks=vi.hoisted(()=>({expose:vi.fn(),invoke:vi.fn(async()=>({ok:true,data:null}))}));
vi.mock('electron',()=>({contextBridge:{exposeInMainWorld:mocks.expose},ipcRenderer:{invoke:mocks.invoke}}));
it('exposes only four business methods for named sets and preserves exact inputs',async()=>{
  await import('../src/preload/index');
  const [name,api]=mocks.expose.mock.calls[0] as [string,DesktopBridge];expect(name).toBe('desktop');
  expect(Object.keys(api.savedSets).sort()).toEqual(['create','detail','list','results']);
  const input={queryId:'query',data:{request_id:'request',name:'List',candidate_ids:['one']},idempotencyKey:'key'};
  await api.savedSets.create(input);expect(mocks.invoke).toHaveBeenLastCalledWith('saved-sets:create',input);
  await api.savedSets.list({activityId:'activity',offset:0,limit:50});expect(mocks.invoke).toHaveBeenLastCalledWith('saved-sets:list',{activityId:'activity',offset:0,limit:50});
  await api.savedSets.detail('set');expect(mocks.invoke).toHaveBeenLastCalledWith('saved-sets:detail','set');
  await api.savedSets.results({id:'set',sort:'relevance',evidence:'none',offset:0,limit:100});expect(mocks.invoke).toHaveBeenLastCalledWith('saved-sets:results',{id:'set',sort:'relevance',evidence:'none',offset:0,limit:100});
});
