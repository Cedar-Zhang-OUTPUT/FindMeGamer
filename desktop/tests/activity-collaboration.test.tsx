// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useActivityCollaboration} from '../src/renderer/components/match/useActivityCollaboration';
import {invitationFixture} from './collaboration-fixtures';
import {settingsBridgeMock,ok} from './settings-fixtures';
afterEach(cleanup);
function setup(active=true){const api=settingsBridgeMock().collaboration,row=invitationFixture();vi.mocked(api.list).mockResolvedValue(ok({items:[row],total:1,limit:50,offset:0}));vi.mocked(api.detail).mockResolvedValue(ok(row));const props={api,activityId:row.activity_id,active,blocked:false};return {api,row,props,...renderHook(p=>useActivityCollaboration(p),{initialProps:props})};}
it('is lazy, uses server filters, and retains selected detail when it leaves the filtered page',async()=>{
 const h=setup(false);expect(h.api.list).not.toHaveBeenCalled();h.rerender({...h.props,active:true});await waitFor(()=>expect(h.result.current.current).toBe(true));
 vi.mocked(h.api.list).mockResolvedValue(ok({items:[],total:0,limit:50,offset:0}));act(()=>h.result.current.changeFilters({invitation_state:'accepted'}));
 await waitFor(()=>expect(h.api.list).toHaveBeenLastCalledWith({activityId:h.row.activity_id,invitation_state:'accepted',limit:50,offset:0}));
 expect(h.result.current.selectedId).toBe(h.row.selection_id);expect(h.result.current.invitation?.selection_id).toBe(h.row.selection_id);expect(h.api.update).not.toHaveBeenCalled();expect(h.api.respond).not.toHaveBeenCalled();
});
it('retains dirty context on a detour, reloads current revision on return and rejects stale submit',async()=>{
 const h=setup();await waitFor(()=>expect(h.result.current.current).toBe(true));act(()=>h.result.current.setDirty(true));h.rerender({...h.props,active:false});
 vi.mocked(h.api.detail).mockResolvedValue(ok({...h.row,revision:2}));h.rerender({...h.props,active:true});await waitFor(()=>expect(h.result.current.invitation?.revision).toBe(2));expect(h.result.current.dirty).toBe(true);
 await act(async()=>{expect(await h.result.current.update({expected_revision:0,notes:'Retain'})).toBe(false);});expect(h.api.update).not.toHaveBeenCalled();
});
it('retains inputs on conflicts; refresh never automatically submits with a new revision',async()=>{
 const h=setup();await waitFor(()=>expect(h.result.current.current).toBe(true));vi.mocked(h.api.update).mockResolvedValue({ok:false,error:{code:'collaboration_revision_conflict',message:'Changed',retryable:false}});
 await act(async()=>{expect(await h.result.current.update({expected_revision:0,notes:'Edit'})).toBe(false);});
 vi.mocked(h.api.detail).mockResolvedValue(ok({...h.row,revision:1,notes:'Other'}));await act(async()=>{await h.result.current.checkCurrent();});expect(h.api.update).toHaveBeenCalledTimes(1);expect(h.result.current.invitation?.revision).toBe(1);
});
it('same-request recovery clears only the acknowledged session and rejects callback captured before credentials invalidation',async()=>{
 const h=setup();await waitFor(()=>expect(h.result.current.current).toBe(true));const stale=h.result.current.update;
 act(()=>h.result.current.credentialsChanged());await act(async()=>{expect(await stale({expected_revision:0,notes:'Must not send'})).toBe(false);});expect(h.api.update).not.toHaveBeenCalled();
 await act(async()=>{await h.result.current.checkCurrent();});vi.mocked(h.api.update).mockResolvedValueOnce({ok:false,error:{code:'collaboration_write_unknown',message:'Unknown',retryable:false}}).mockResolvedValueOnce(ok({...h.row,revision:1,notes:'Edit'}));
 await act(async()=>{await h.result.current.update({expected_revision:0,notes:'Edit'});});expect(h.result.current.locked).toBe(true);
 await act(async()=>{await h.result.current.retryOriginal();});expect(h.result.current.confirmedChange).toMatchObject({selectionId:h.row.selection_id,revision:0,kind:'update'});expect(h.result.current.locked).toBe(false);
});
it('never lets a delayed pre-commit detail response overwrite an acknowledged save',async()=>{
 const h=setup();await waitFor(()=>expect(h.result.current.current).toBe(true));let finishWrite!:(v:ReturnType<typeof ok<typeof h.row>>)=>void,finishRead!:(v:ReturnType<typeof ok<typeof h.row>>)=>void;
 vi.mocked(h.api.update).mockImplementationOnce(()=>new Promise(done=>finishWrite=done));vi.mocked(h.api.detail).mockImplementationOnce(()=>new Promise(done=>finishRead=done));let save!:Promise<boolean>,read!:ReturnType<typeof h.result.current.checkCurrent>;
 act(()=>{save=h.result.current.update({expected_revision:0,notes:'Committed'});});act(()=>{read=h.result.current.checkCurrent();});
 await act(async()=>{finishWrite(ok({...h.row,revision:1,notes:'Committed'}));expect(await save).toBe(true);});
 await act(async()=>{finishRead(ok(h.row));await read;});expect(h.result.current.invitation?.revision).toBe(1);expect(h.result.current.invitation?.notes).toBe('Committed');expect(h.result.current.current).toBe(true);
});
