// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useActivityOutreach} from '../src/renderer/components/match/useActivityOutreach';
import {outreachAPIMock} from './outreach-api-mock';
import {preparationFixture,recipientBatchFixture,SELECTION_ID,SECOND_SELECTION_ID} from './outreach-fixtures';
import {activityFixture,candidateFixture,matchAPIMock,queryFixture} from './match-api-mock';
import {ok} from './settings-fixtures';
import type {Preparation} from '../src/shared/outreach';
afterEach(cleanup);
const person=(i=1)=>preparationFixture({id:i===1?SELECTION_ID:SECOND_SELECTION_ID,activity_id:activityFixture().id,candidate_id:candidateFixture(i).id,creator_id:candidateFixture(i).creator_id,name:`Creator ${i}`,identity:{platform:'youtube',account_id:`UC_${i}`,revision:1},selected_contact:null,missing_fields:['email_not_selected','evidence_missing']});
function setup(initial:Preparation[]=[]){
  const outreach=outreachAPIMock(),match=matchAPIMock(),onOptions=vi.fn();let people=initial;
  vi.mocked(outreach.selections).mockImplementation(async()=>ok({items:people,total:people.length,offset:0,limit:200}));
  vi.mocked(outreach.add).mockImplementation(async()=>{people=[person()];return ok(people[0]);});
  vi.mocked(outreach.bulk).mockImplementation(async input=>{const cancelled=input.data.cancel_selections?.map(v=>v.selection_id)??[];people=people.filter(p=>!cancelled.includes(p.id));return ok({added_selection_ids:[],cancelled_selection_ids:cancelled});});
  const params={api:{outreach,match},activityId:activityFixture().id,active:true,queryId:queryFixture().id,candidates:[candidateFixture(1),candidateFixture(2)],candidateCurrent:true,options:{evidence:'all' as const,sort:'relevance' as const},onOptions,blocked:false};
  const hook=renderHook(()=>useActivityOutreach(params));return {...hook,params,outreach,match,onOptions,setPeople:(next:Preparation[])=>{people=next;}};
}
it('adds only an explicit click and leaves arriving candidates unselected',async()=>{
  const {result,outreach}=setup();await waitFor(()=>expect(result.current.session.current).toBe(true));
  expect(outreach.add).not.toHaveBeenCalled();
  await act(()=>result.current.toggle(candidateFixture(1)));
  expect(outreach.add).toHaveBeenCalledWith({activityId:activityFixture().id,data:{candidate_id:candidateFixture(1).id},idempotencyKey:expect.any(String)});
  expect(result.current.isSelected(candidateFixture(1))).toBe(true);expect(result.current.isSelected(candidateFixture(2))).toBe(false);
});
it('sorting is read-only; an explicit evidence change cancels only excluded visible selected people',async()=>{
  const other={...person(2),id:'other',identity:{...person(2).identity,account_id:'other'}};
  const {result,match,outreach,onOptions}=setup([person(),other]);await waitFor(()=>expect(result.current.session.current).toBe(true));
  await act(()=>result.current.changeOptions({evidence:'all',sort:'followers'}));expect(outreach.bulk).not.toHaveBeenCalled();
  vi.mocked(match.candidates).mockResolvedValueOnce(ok({items:[candidateFixture(2)],total:1,offset:0,limit:100}));
  await act(()=>result.current.changeOptions({evidence:'current_game',sort:'relevance'}));
  expect(outreach.bulk).toHaveBeenCalledWith({activityId:activityFixture().id,data:{cancel_selections:[{selection_id:SELECTION_ID,expected_revision:3}]},idempotencyKey:expect.any(String)});
  expect(onOptions).toHaveBeenLastCalledWith({evidence:'current_game',sort:'relevance'});expect(result.current.notice).toContain('1');
  expect(result.current.session.items.map(p=>p.id)).toEqual(['other']);
});
it('stops before freezing exactly N revisions, preserving incomplete people and excluding arrivals during stop',async()=>{
  const {result,outreach,match,setPeople}=setup([person(),person(2)]);await waitFor(()=>expect(result.current.session.current).toBe(true));
  let stopped!:(v:Awaited<ReturnType<typeof match.stop>>)=>void;
  vi.mocked(match.stop).mockImplementationOnce(()=>new Promise(r=>stopped=r));
  vi.mocked(outreach.freeze).mockImplementation(async input=>ok(recipientBatchFixture({activity_id:activityFixture().id,request_id:input.data.request_id,recipient_count:2,needs_repair_count:2,recipients:[person(),person(2)].map((p,i)=>({id:String(i),selection_id:p.id,snapshot:p,preparation:p,source_changed:false,current_missing_fields:p.missing_fields}))})));
  let pending!:Promise<void>;act(()=>{pending=result.current.prepare([SELECTION_ID,SECOND_SELECTION_ID]);});
  await waitFor(()=>expect(match.stop).toHaveBeenCalledOnce());expect(outreach.freeze).not.toHaveBeenCalled();
  setPeople([person(),person(2),{...person(),id:'later-person',identity:{platform:'youtube',account_id:'later-account',revision:1}}]);
  await act(()=>result.current.session.refresh());expect(result.current.session.items).toHaveLength(3);
  await act(async()=>{stopped(ok({query_id:queryFixture().id,status:'stopped',stop_requested:true}));await pending;});
  expect(outreach.freeze).toHaveBeenCalledWith({activityId:activityFixture().id,data:{request_id:expect.any(String),recipients:[person(),person(2)].map(p=>({selection_id:p.id,expected_revision:3,context_token:p.context_token}))},idempotencyKey:expect.any(String)});
  expect(result.current.batch?.recipient_count).toBe(2);expect(result.current.panel).toBe('batch');
});
it('an uncertain stop cannot freeze; explicit same-stop retry is required',async()=>{
  const {result,outreach,match}=setup([person()]);await waitFor(()=>expect(result.current.session.current).toBe(true));
  vi.mocked(match.stop).mockResolvedValueOnce({ok:false,error:{code:'match_outcome_unknown',message:'Unknown',retryable:false}});
  await act(()=>result.current.prepare([SELECTION_ID]));expect(outreach.freeze).not.toHaveBeenCalled();expect(result.current.locked).toBe(true);
});
it('retries a known stop rejection with the same key before preparing, not an inert retry button',async()=>{
  const {result,outreach,match}=setup([person()]);await waitFor(()=>expect(result.current.session.current).toBe(true));
  vi.mocked(match.stop).mockResolvedValueOnce({ok:false,error:{code:'invalid_request',message:'Stop rejected',retryable:false}});
  await act(()=>result.current.prepare([SELECTION_ID]));expect(outreach.freeze).not.toHaveBeenCalled();
  vi.mocked(outreach.freeze).mockImplementation(async input=>ok(recipientBatchFixture({activity_id:activityFixture().id,request_id:input.data.request_id})));
  await act(()=>result.current.retryStop());expect(match.stop).toHaveBeenCalledTimes(2);
  expect(vi.mocked(match.stop).mock.calls[0]).toEqual(vi.mocked(match.stop).mock.calls[1]);expect(outreach.freeze).toHaveBeenCalledOnce();
});
it('a failed complete-membership read keeps the prior filters and never removes a selected person',async()=>{
  const {result,outreach,match,onOptions}=setup([person()]);await waitFor(()=>expect(result.current.session.current).toBe(true));
  vi.mocked(match.candidates).mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Unavailable',retryable:true}});
  await act(()=>result.current.changeOptions({evidence:'none',sort:'relevance'}));
  expect(onOptions).not.toHaveBeenCalled();expect(outreach.bulk).not.toHaveBeenCalled();expect(result.current.session.items).toHaveLength(1);
});
