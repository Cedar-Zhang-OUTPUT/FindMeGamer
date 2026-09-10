// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useCreatorSearchSession} from '../src/renderer/components/match/useCreatorSearchSession';
import {matchAPIMock,activityFixture,queryFixture,candidateFixture,evaluationFixture} from './match-api-mock';
import type {CreatorSearch,CreatorSearchPerson} from '../src/shared/creatorSearch';
import type {EvaluationResult} from '../src/shared/match';
afterEach(cleanup);
const ok=<T,>(data:T)=>({ok:true as const,data});
const id=activityFixture().id;
function task(status:CreatorSearch['status']='running'):CreatorSearch{return{id,activity_id:id,plan_id:id,query_id:queryFixture().id,evaluation_id:evaluationFixture().id,parent_search_id:null,status,stage:status==='completed'?'complete':'emails',counts:{discovered:120,profile_ready:120,profile_reused:100,profile_failed:0,email_available:60,email_missing:60,email_failed:0,evaluated:status==='completed'?120:0,matched:100},stop_requested:false,retryable:false,outcome_unknown:false,error_code:null,created_at:'2026-09-10T00:00:00Z',updated_at:'2026-09-10T00:00:00Z'};}
it('polls the automatic task after discovery finishes and reads every result page only at terminal',async()=>{
 const api=matchAPIMock();let terminal=false;vi.mocked(api.creatorSearches).mockResolvedValue(ok({items:[task()],total:1,offset:0,limit:50}));vi.mocked(api.creatorSearch).mockImplementation(async()=>ok(task(terminal?'completed':'running')));
 const candidates=Array.from({length:120},(_,n)=>candidateFixture(n+1));
 const people=candidates.map(c=>({candidate_id:c.id,creator_id:c.creator_id,platform:'youtube',profile_status:'ready',email_status:'missing',analysis_job_id:null,profile_error_code:null,email_error_code:null} as CreatorSearchPerson));
 const results=candidates.map(c=>({candidate_id:c.id,creator_id:c.creator_id} as EvaluationResult));
 vi.mocked(api.creatorSearchPeople).mockImplementation(async({offset=0,limit=100})=>ok({items:people.slice(offset,offset+limit),total:120,offset,limit}));
 vi.mocked(api.evaluationResults).mockImplementation(async({offset=0,limit=100})=>ok({items:results.slice(offset,offset+limit),total:120,offset,limit}));
 vi.mocked(api.candidates).mockImplementation(async({offset=0,limit=100})=>ok({items:candidates.slice(offset,offset+limit),total:120,offset,limit}));
 const view=renderHook(()=>useCreatorSearchSession(api,id,true,20));await waitFor(()=>expect(view.result.current.search?.stage).toBe('emails'));
 expect(view.result.current.current).toBe(false);expect(api.evaluationResults).not.toHaveBeenCalled();expect(api.evaluate).not.toHaveBeenCalled();
 terminal=true;await waitFor(()=>expect(view.result.current.current).toBe(true));expect(view.result.current.results).toHaveLength(120);expect(view.result.current.candidates).toHaveLength(120);
 expect(api.evaluationResults).toHaveBeenCalledWith({id:evaluationFixture().id,offset:100,limit:100});expect(api.createPlan).not.toHaveBeenCalled();expect(api.createCreatorSearch).not.toHaveBeenCalled();
});
it('keeps existing legacy queries read-only when the new history is empty',async()=>{
 const api=matchAPIMock(),view=renderHook(()=>useCreatorSearchSession(api,id,true));await waitFor(()=>expect(view.result.current.scope.kind).toBe('legacy'));expect(api.creatorSearch).not.toHaveBeenCalled();expect(api.createCreatorSearch).not.toHaveBeenCalled();expect(api.evaluate).not.toHaveBeenCalled();
});
it('does not let a delayed old task replace a user history choice',async()=>{
 const api=matchAPIMock();vi.mocked(api.creatorSearches).mockResolvedValue(ok({items:[task()],total:1,offset:0,limit:50}));let resolve!:(value:ReturnType<typeof ok<CreatorSearch>>)=>void;
 vi.mocked(api.creatorSearch).mockImplementation(()=>new Promise(r=>{resolve=r;}));const view=renderHook(()=>useCreatorSearchSession(api,id,true));await waitFor(()=>expect(resolve).toBeTypeOf('function'));
 act(()=>view.result.current.select(null));await act(()=>resolve(ok(task('completed'))));expect(view.result.current.scope.kind).toBe('legacy');expect(view.result.current.search).toBeNull();
});
