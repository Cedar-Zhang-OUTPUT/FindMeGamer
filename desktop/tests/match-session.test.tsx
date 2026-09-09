// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {useMatchSession} from '../src/renderer/components/match/useMatchSession';
import {activityFixture,candidateFixture,matchAPIMock,planFixture,queryFixture} from './match-api-mock';
afterEach(cleanup);
it('reads the initialization marker after the first batch ends without starting new work',async()=>{
 const api=matchAPIMock();const base={...activityFixture(),queries:[],initial_selection_initialized:false};
 vi.mocked(api.activity).mockResolvedValueOnce({ok:true,data:base}).mockResolvedValue({ok:true,data:{...base,initial_selection_initialized:true}});
 const {result}=renderHook(()=>useMatchSession(api,base.id,true));
 await waitFor(()=>expect(result.current.activity?.initial_selection_initialized).toBe(true));
 expect(api.createPlan).not.toHaveBeenCalled();expect(api.continueDiscovery).not.toHaveBeenCalled();
});
it('opens persisted activity and frozen query without starting any new work',async()=>{
  const api=matchAPIMock();const {result}=renderHook(()=>useMatchSession(api,activityFixture().id,true));
  await waitFor(()=>expect(result.current.candidates).toHaveLength(2));
  expect(result.current.plan?.id).toBe(planFixture().id);expect(result.current.query?.id).toBe(queryFixture().id);
  expect(api.createPlan).not.toHaveBeenCalled();expect(api.evaluate).not.toHaveBeenCalled();expect(api.continueDiscovery).not.toHaveBeenCalled();
});
it('loads more server pages in order and keeps prior results after a read failure',async()=>{
  const api=matchAPIMock();vi.mocked(api.candidates).mockImplementation(async input=>({ok:true,data:{items:Array.from({length:input.offset?2:100},(_,i)=>candidateFixture((input.offset??0)+i+1)),offset:input.offset??0,total:102,limit:100}}));
  const {result}=renderHook(()=>useMatchSession(api,activityFixture().id,true));
  await waitFor(()=>expect(result.current.candidates).toHaveLength(100));
  act(()=>result.current.loadMoreCandidates());await waitFor(()=>expect(result.current.candidates).toHaveLength(102));
  expect(result.current.candidates[100].id).toBe(candidateFixture(101).id);
  vi.mocked(api.candidates).mockResolvedValue({ok:false,error:{code:'network_error',message:'Offline',retryable:true}});
  act(()=>result.current.refresh());await waitFor(()=>expect(result.current.errors.candidates?.message).toBe('Offline'));
  expect(result.current.candidates).toHaveLength(102);
});
it('does not fetch a hidden task and resumes read-only when visible',async()=>{
  const api=matchAPIMock();const {result,rerender}=renderHook(({active})=>useMatchSession(api,activityFixture().id,active),{initialProps:{active:false}});
  expect(api.activity).not.toHaveBeenCalled();rerender({active:true});await waitFor(()=>expect(result.current.query).not.toBeNull());
  const calls=vi.mocked(api.query).mock.calls.length;rerender({active:false});act(()=>result.current.refresh());expect(api.query).toHaveBeenCalledTimes(calls);
});
it('retains a search-history failure until that read succeeds, independently of successful task polling',async()=>{
  const api=matchAPIMock();const {result}=renderHook(()=>useMatchSession(api,activityFixture().id,true));
  await waitFor(()=>expect(result.current.candidates).toHaveLength(2));
  vi.mocked(api.plans).mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Search history unavailable',retryable:true}});
  act(()=>result.current.refresh());
  await waitFor(()=>expect(api.query).toHaveBeenCalledTimes(3));
  await waitFor(()=>expect(result.current.loading).toBe(false));
  expect(result.current.errors.plans?.message).toBe('Search history unavailable');
  expect(result.current.candidates).toHaveLength(2);
  act(()=>result.current.refresh());
  await waitFor(()=>expect(result.current.errors.plans).toBeUndefined());
});
