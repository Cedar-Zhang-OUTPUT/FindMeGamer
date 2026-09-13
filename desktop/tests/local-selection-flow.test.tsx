// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,render,screen,within,renderHook,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {OutreachWorkspace} from '../src/renderer/components/match/OutreachWorkspace';
import type {DesktopBridge} from '../src/shared/bridge';
import {afterEach,expect,it,vi} from 'vitest';
import {useActivityOutreach} from '../src/renderer/components/match/useActivityOutreach';
import type {LocalSelectionsAPI} from '../src/shared/localSelections';
import type {LocalPrepareState} from '../src/renderer/components/match/localSelectionPrepare';
import {outreachAPIMock} from './outreach-api-mock';
import {candidateFixture,activityFixture,queryFixture,matchAPIMock} from './match-api-mock';
import {preparationFixture,recipientBatchFixture} from './outreach-fixtures';
import {ok} from './settings-fixtures';
afterEach(cleanup);
it('changes only loaded scope atomically, preserves other choices and never selects later arrivals',async()=>{
 const s=setup(),second=candidateFixture(2),third=candidateFixture(3),hook=renderHook(props=>useActivityOutreach(props),{initialProps:s.props});
 await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 const writes=vi.mocked(s.props.api.localSelections.write);writes.mockClear();const reads=vi.mocked(s.outreach.selections).mock.calls.length;
 await act(()=>hook.result.current.selectLoaded([second],true));expect(hook.result.current.selectionCount).toBe(2);expect(writes).toHaveBeenCalledTimes(1);
 await act(()=>hook.result.current.deselectLoaded([second],true));expect(hook.result.current.selectionCount).toBe(1);expect(hook.result.current.isSelected(s.candidate)).toBe(true);
 hook.rerender({...s.props,candidates:[s.candidate,second,third]});expect(hook.result.current.isSelected(third)).toBe(false);
 expect(s.outreach.selections).toHaveBeenCalledTimes(reads);expect(s.outreach.bulk).not.toHaveBeenCalled();expect(s.outreach.add).not.toHaveBeenCalled();expect(s.outreach.cancel).not.toHaveBeenCalled();
});
it('retains displayed review rows after deselect all so select all restores them locally',async()=>{
 const s=setup(),user=userEvent.setup();
 function Review(){const controller=useActivityOutreach(s.props);return <><button onClick={()=>controller.setPanel('selected')}>Review choices</button><OutreachWorkspace api={s.props.api as DesktopBridge} controller={controller} active onRequest={fn=>fn()} onOpenCreator={()=>{}}/></>;}
 render(<Review/>);await waitFor(()=>expect(s.saved.get(s.props.queryId)?.draft.initialized).toBe(true));await user.click(screen.getByRole('button',{name:'Review choices'}));
 const list=screen.getByRole('list',{name:'Selected creators'}),actions=screen.getByRole('group',{name:'Listed review creators selection'});
 expect(within(list).getByRole('checkbox')).toBeChecked();vi.mocked(s.props.api.localSelections.write).mockClear();
 await user.click(within(actions).getByRole('button',{name:'Deselect all'}));expect(within(list).getByRole('checkbox')).not.toBeChecked();expect(within(list).getAllByRole('listitem')).toHaveLength(1);
 expect(s.props.api.localSelections.write).toHaveBeenCalledTimes(1);expect(screen.queryByRole('button',{name:'Prepare 1'})).not.toBeInTheDocument();
 await user.click(within(actions).getByRole('button',{name:'Select all'}));expect(within(list).getByRole('checkbox')).toBeChecked();expect(screen.getByRole('button',{name:'Prepare 1'})).toBeEnabled();
 expect(s.outreach.bulk).not.toHaveBeenCalled();expect(s.outreach.cancel).not.toHaveBeenCalled();expect(s.outreach.freeze).not.toHaveBeenCalled();
});
function setup(){
 const outreach=outreachAPIMock(),match=matchAPIMock(),candidate=candidateFixture(1),activityId=activityFixture().id;
 const person=preparationFixture({activity_id:activityId,candidate_id:candidate.id,creator_id:candidate.creator_id,identity:{platform:'youtube',account_id:candidate.account_id,revision:candidate.identity_revision}});
 let rows=[person];vi.mocked(outreach.selections).mockImplementation(async()=>ok({items:rows,total:rows.length,offset:0,limit:200}));
 const saved=new Map<string,LocalPrepareState>();const localSelections:LocalSelectionsAPI={read:vi.fn(async input=>ok({scope:'test-workspace',state:structuredClone(saved.get(input.queryId??'none')??null)})),write:vi.fn(async input=>{saved.set(input.queryId??'none',structuredClone(input.state));return ok(undefined);})};
 const props={api:{outreach,match,localSelections},activityId,active:true,queryId:queryFixture().id,candidates:[candidate],candidateCurrent:true,options:{evidence:'all' as const,sort:'relevance' as const},onOptions:vi.fn(),blocked:false};
 return {props,candidate,person,outreach,saved,setRows:(value:typeof rows)=>{rows=value;}};
}
it('toggles immediately without per-click HTTP writes or selection re-reads and survives remount',async()=>{
 const s=setup(),hook=renderHook(props=>useActivityOutreach(props),{initialProps:s.props});await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 const reads=vi.mocked(s.outreach.selections).mock.calls.length;
 act(()=>{for(let i=0;i<51;i++)void hook.result.current.toggle(s.candidate);});
 expect(hook.result.current.isSelected(s.candidate)).toBe(false);expect(hook.result.current.busy).toBe(false);
 expect(s.outreach.add).not.toHaveBeenCalled();expect(s.outreach.cancel).not.toHaveBeenCalled();expect(s.outreach.bulk).not.toHaveBeenCalled();expect(s.outreach.selections).toHaveBeenCalledTimes(reads);
 await waitFor(()=>expect(s.saved.get(s.props.queryId)?.draft.desired).toEqual([]));
 await act(()=>hook.result.current.refresh());expect(hook.result.current.isSelected(s.candidate)).toBe(false);
 hook.unmount();const restored=renderHook(()=>useActivityOutreach(s.props));await waitFor(()=>expect(restored.result.current.selectionReady).toBe(true));expect(restored.result.current.isSelected(s.candidate)).toBe(false);
});
it('rejects an over-limit batch without partial changes or journal writes and deduplicates account aliases',async()=>{
 const s=setup(),hook=renderHook(()=>useActivityOutreach(s.props));await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 const writes=vi.mocked(s.props.api.localSelections.write);writes.mockClear();
 await act(()=>hook.result.current.selectLoaded(Array.from({length:600},(_,i)=>candidateFixture(i+2)),true));
 expect(hook.result.current.selectionCount).toBe(1);expect(writes).not.toHaveBeenCalled();expect(hook.result.current.local.error?.code).toBe('selection_limit');
 const second=candidateFixture(2),alias={...second,id:'same-account-alias'},changed={...candidateFixture(3),identity_changed:true};
 await act(()=>hook.result.current.selectLoaded([second,alias,changed],true));
 expect(hook.result.current.selectionCount).toBe(2);expect(writes).toHaveBeenCalledTimes(1);expect(hook.result.current.isSelected(alias)).toBe(true);expect(hook.result.current.isSelected(changed)).toBe(false);
 await act(()=>hook.result.current.deselectLoaded([alias],true));expect(hook.result.current.selectionCount).toBe(1);expect(hook.result.current.isSelected(s.candidate)).toBe(true);
 expect(s.outreach.bulk).not.toHaveBeenCalled();
});
it('keeps batch actions disabled for stale results and pending preparation',async()=>{
 const s=setup(),hook=renderHook(props=>useActivityOutreach(props),{initialProps:s.props});await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 const writes=vi.mocked(s.props.api.localSelections.write);writes.mockClear();
 await act(()=>hook.result.current.selectLoaded([candidateFixture(2)],false));await act(()=>hook.result.current.deselectLoaded([s.candidate],false));expect(writes).not.toHaveBeenCalled();
 vi.mocked(s.outreach.freeze).mockResolvedValueOnce({ok:false,error:{code:'outreach_outcome_unknown',message:'Lost',retryable:false}});
 await act(()=>hook.result.current.prepare([]));expect(hook.result.current.local.locked).toBe(true);writes.mockClear();
 await act(()=>hook.result.current.selectLoaded([candidateFixture(2)],true));await act(()=>hook.result.current.deselectLoaded([s.candidate],true));
 expect(writes).not.toHaveBeenCalled();expect(hook.result.current.selectionCount).toBe(1);
});
it('does not merge pending choices across query switches',async()=>{
 const s=setup(),hook=renderHook(props=>useActivityOutreach(props),{initialProps:s.props});await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 act(()=>{void hook.result.current.toggle(s.candidate);});await waitFor(()=>expect(s.saved.get(s.props.queryId)?.draft.desired).toEqual([]));
 hook.rerender({...s.props,queryId:'second-query'});await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));expect(hook.result.current.isSelected(s.candidate)).toBe(true);
 hook.rerender(s.props);await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));expect(hook.result.current.isSelected(s.candidate)).toBe(false);
});
it('prepares one final bulk after local changes and blocks toggles while that request is pending',async()=>{
 const s=setup(),second=candidateFixture(2);const person2={...s.person,id:'selection-two',candidate_id:second.id,creator_id:second.creator_id,identity:{platform:'youtube' as const,account_id:second.account_id,revision:second.identity_revision}};
 const hook=renderHook(()=>useActivityOutreach(s.props));await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 act(()=>{void hook.result.current.toggle(second);});expect(hook.result.current.selectionCount).toBe(2);
 let resolve!:(value:Awaited<ReturnType<typeof s.outreach.bulk>>)=>void;vi.mocked(s.outreach.bulk).mockImplementationOnce(()=>new Promise(done=>resolve=done));
 vi.mocked(s.outreach.freeze).mockImplementation(async input=>ok(recipientBatchFixture({activity_id:s.props.activityId,request_id:input.data.request_id,recipient_count:2,recipients:[s.person,person2].map(p=>({id:p.id,selection_id:p.id,snapshot:p,preparation:p,source_changed:false,current_missing_fields:[]}))})));
 let pending!:Promise<void>;act(()=>{pending=hook.result.current.prepare([]);});await waitFor(()=>expect(s.outreach.bulk).toHaveBeenCalledOnce());
 act(()=>{void hook.result.current.toggle(s.candidate);});expect(hook.result.current.selectionCount).toBe(2);
 s.setRows([s.person,person2]);await act(async()=>{resolve(ok({added_selection_ids:[person2.id],cancelled_selection_ids:[]}));await pending;});
 expect(s.outreach.freeze).toHaveBeenCalledOnce();expect(hook.result.current.panel).toBe('batch');expect(s.outreach.add).not.toHaveBeenCalled();
});
it('does not replay a pending transaction into changed credentials',async()=>{
 const s=setup(),hook=renderHook(()=>useActivityOutreach(s.props));await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 vi.mocked(s.outreach.freeze).mockResolvedValueOnce({ok:false,error:{code:'outreach_outcome_unknown',message:'Lost',retryable:false}});
 await act(()=>hook.result.current.prepare([]));expect(s.outreach.freeze).toHaveBeenCalledOnce();
 vi.mocked(s.props.api.localSelections.write).mockResolvedValue({ok:false,error:{code:'connection_changed',message:'Changed',retryable:false}});
 await act(()=>hook.result.current.prepare([]));expect(s.outreach.freeze).toHaveBeenCalledTimes(1);expect(hook.result.current.local.state?.stage).toBe('freeze_pending');expect(hook.result.current.local.error?.code).toBe('connection_changed');
});
it('restores an unknown freeze after remount without generating a new request or bulk',async()=>{
 const s=setup(),hook=renderHook(()=>useActivityOutreach(s.props));await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 vi.mocked(s.outreach.freeze).mockResolvedValueOnce({ok:false,error:{code:'outreach_outcome_unknown',message:'Lost',retryable:false}});
 await act(()=>hook.result.current.prepare([]));const original=vi.mocked(s.outreach.freeze).mock.calls[0][0];hook.unmount();
 vi.mocked(s.outreach.freeze).mockImplementation(async input=>ok(recipientBatchFixture({activity_id:s.props.activityId,request_id:input.data.request_id,recipients:[{id:'recipient',selection_id:s.person.id,snapshot:s.person,preparation:s.person,source_changed:false,current_missing_fields:[]}]})));
 const restored=renderHook(()=>useActivityOutreach(s.props));await waitFor(()=>expect(restored.result.current.local.state?.stage).toBe('freeze_pending'));
 await act(()=>restored.result.current.prepare([]));expect(vi.mocked(s.outreach.freeze).mock.calls[1][0]).toEqual(original);expect(s.outreach.bulk).not.toHaveBeenCalled();expect(restored.result.current.panel).toBe('batch');
});
it('recognizes and unselects the same account under a new query candidate ID without merging query drafts',async()=>{
 const s=setup(),alias={...s.candidate,id:'new-query-alias'},hook=renderHook(props=>useActivityOutreach(props),{initialProps:s.props});await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));
 hook.rerender({...s.props,queryId:'new-query',candidates:[alias]});await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));expect(hook.result.current.isSelected(alias)).toBe(true);
 act(()=>{void hook.result.current.toggle(alias);});expect(hook.result.current.selectionCount).toBe(0);expect(hook.result.current.isSelected(alias)).toBe(false);expect(s.outreach.bulk).not.toHaveBeenCalled();
 hook.rerender(s.props);await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));expect(hook.result.current.isSelected(s.candidate)).toBe(true);
});
it('can explicitly remove an identity-changed row after review and prepare the other person',async()=>{
 const s=setup(),second=candidateFixture(2),other={...s.person,id:'selection-two',candidate_id:second.id,creator_id:second.creator_id,identity:{platform:'youtube' as const,account_id:second.account_id,revision:second.identity_revision}},changed={...s.person,identity_changed:true,revision:s.person.revision+1};
 const hook=renderHook(()=>useActivityOutreach(s.props));await waitFor(()=>expect(hook.result.current.selectionReady).toBe(true));s.setRows([changed,other]);await act(()=>hook.result.current.refresh());
 await act(()=>hook.result.current.prepare([]));expect(hook.result.current.local.state?.stage).toBe('conflict');
 await act(()=>hook.result.current.local.reviewConflict([changed,other]));act(()=>hook.result.current.local.change(hook.result.current.local.state!.draft.members[s.candidate.id],false));
 vi.mocked(s.outreach.bulk).mockImplementation(async input=>{expect(input.data).toEqual({add_candidate_ids:[],cancel_selections:[{selection_id:changed.id,expected_revision:changed.revision}]});s.setRows([{...changed,active:false,revision:changed.revision+1},other]);return ok({added_selection_ids:[],cancelled_selection_ids:[changed.id]});});
 vi.mocked(s.outreach.freeze).mockImplementation(async input=>ok(recipientBatchFixture({activity_id:s.props.activityId,request_id:input.data.request_id,recipient_count:1,recipients:[{id:'recipient',selection_id:other.id,snapshot:other,preparation:other,source_changed:false,current_missing_fields:[]}]})));
 await act(()=>hook.result.current.prepare([]));expect(hook.result.current.panel).toBe('batch');expect(s.outreach.bulk).toHaveBeenCalledOnce();expect(s.outreach.add).not.toHaveBeenCalled();
});
