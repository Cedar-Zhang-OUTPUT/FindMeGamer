// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {useOutreachSession} from '../src/renderer/components/match/useOutreachSession';
import {outreachAPIMock} from './outreach-api-mock';
import {preparationFixture} from './outreach-fixtures';
afterEach(cleanup);
it('reloads server selections when initialization is observed without selecting anyone locally',async()=>{
 const api=outreachAPIMock(),person=preparationFixture();
 vi.mocked(api.selections).mockResolvedValue({ok:true,data:{items:[],total:0,offset:0,limit:200}});
 const {result,rerender}=renderHook(({initialized})=>useOutreachSession(api,person.activity_id,true,initialized),{initialProps:{initialized:false}});
 await waitFor(()=>expect(result.current.current).toBe(true));
 vi.mocked(api.selections).mockResolvedValue({ok:true,data:{items:[person],total:1,offset:0,limit:200}});
 rerender({initialized:true});await waitFor(()=>expect(result.current.items).toEqual([person]));
 const reads=vi.mocked(api.selections).mock.calls.length;rerender({initialized:true});expect(api.selections).toHaveBeenCalledTimes(reads);
 vi.mocked(api.selections).mockResolvedValue({ok:true,data:{items:[],total:0,offset:0,limit:200}});
 await act(()=>result.current.refresh());expect(result.current.items).toEqual([]);
 expect(api.bulk).not.toHaveBeenCalled();expect(api.add).not.toHaveBeenCalled();
});
