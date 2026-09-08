// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useOutreachSession,readSelections} from '../src/renderer/components/match/useOutreachSession';
import {preparationFixture} from './outreach-fixtures';
import {ACTIVITY_ID} from './match-fixtures';
import {ok} from './settings-fixtures';
afterEach(cleanup);
const deferred=<T,>()=>{let resolve!:(value:T)=>void;return {promise:new Promise<T>(r=>resolve=r),resolve};};
it('reads the complete authoritative list with current fields, without adding or filtering incomplete people',async()=>{
  const people=Array.from({length:201},(_,index)=>preparationFixture({id:String(index),selected_contact:null,missing_fields:['email']}));
  const selections=vi.fn(async input=>ok({items:people.slice(input.offset,input.offset+200),offset:input.offset,limit:200,total:201}));
  const result=await readSelections({selections},ACTIVITY_ID);
  expect(result).toHaveLength(201);expect(result[200].selected_contact).toBeNull();
  expect(selections.mock.calls.map(([v])=>v)).toEqual([{activityId:ACTIVITY_ID,includeCancelled:false,offset:0,limit:200},{activityId:ACTIVITY_ID,includeCancelled:false,offset:200,limit:200}]);
});
it('keeps successful people but disables actions on a failed reload',async()=>{
  const selections=vi.fn(async()=>ok({items:[preparationFixture()],total:1,offset:0,limit:200}));
  const {result}=renderHook(()=>useOutreachSession({selections},ACTIVITY_ID,true));
  await waitFor(()=>expect(result.current.current).toBe(true));
  selections.mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Offline',retryable:true}} as never);
  await act(()=>result.current.refresh());
  expect(result.current.items).toHaveLength(1);expect(result.current.current).toBe(false);expect(result.current.error?.code).toBe('network_error');
});
it('does not fetch hidden workspace and fences old reads after credential change',async()=>{
  const pending=deferred<ReturnType<typeof ok<{items:ReturnType<typeof preparationFixture>[];total:number;offset:number;limit:number}>>>();
  const api={selections:vi.fn(()=>pending.promise)};
  const {result,rerender}=renderHook(({active})=>useOutreachSession(api,ACTIVITY_ID,active),{initialProps:{active:false}});
  expect(api.selections).not.toHaveBeenCalled();rerender({active:true});await waitFor(()=>expect(api.selections).toHaveBeenCalledOnce());
  act(()=>result.current.credentialsChanged());
  await act(()=>pending.resolve(ok({items:[preparationFixture()],total:1,offset:0,limit:200})));
  expect(result.current.items).toEqual([]);expect(result.current.current).toBe(false);
});
