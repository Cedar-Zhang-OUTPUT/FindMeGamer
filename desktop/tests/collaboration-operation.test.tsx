// @vitest-environment jsdom
import {act,cleanup,renderHook} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {invitationFixture,activityResponseFixture} from './collaboration-fixtures';
import {freezeCollaborationAttempt,reconcileCollaboration,reviewCollaboration,type CollaborationCommand} from '../src/renderer/components/match/collaborationMutation';
import {useCollaborationOperation} from '../src/renderer/components/match/useCollaborationOperation';
import type {CollaborationAPI} from '../src/shared/collaboration';
import type {Result} from '../src/shared/bridge';
const command=():CollaborationCommand=>({kind:'update',observed:invitationFixture(),data:{expected_revision:0,notes:'Local edit'}});
const saved=()=>invitationFixture({revision:1,notes:'Local edit'});
const unknown={ok:false as const,error:{code:'collaboration_write_unknown',message:'Unconfirmed',retryable:false}};
function mock(){return {list:vi.fn(),detail:vi.fn(),creatorHistory:vi.fn(),update:vi.fn<CollaborationAPI['update']>(async()=>({ok:true as const,data:saved()})),respond:vi.fn()} satisfies CollaborationAPI;}
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('freezes one key, exact revision and body without adding a request UUID or observations',()=>{
  const c=command(),attempt=freezeCollaborationAttempt(c);c.data.expected_revision=9;
  expect(attempt.input.data.expected_revision).toBe(0);expect(attempt.input).not.toHaveProperty('observed');expect(attempt.input.data).not.toHaveProperty('request_id');
  expect(Object.isFrozen(attempt.input.data)).toBe(true);
});
it('requires exact scope, changed fields and untouched manual context for an update receipt',()=>{
  const a=freezeCollaborationAttempt(command());expect(reconcileCollaboration(a,saved())).toBe(true);
  for(const patch of [{selection_id:'foreign'},{revision:2},{notes:'other'},{cooperation_state:'published' as const},{responses:[activityResponseFixture()]},{identity:{platform:'x',account_id:'other'}}])expect(reconcileCollaboration(a,invitationFixture({...saved(),...patch}))).toBe(false);
  expect(reconcileCollaboration(a,invitationFixture({...saved(),sending_state:'sent',invited_at:'2026-09-09T00:00:00Z'}))).toBe(true);
});
it('requires the exact new response revision, actual time and source, never just accepted status',()=>{
  const response=activityResponseFixture(),observed=invitationFixture();
  const a=freezeCollaborationAttempt({kind:'respond',observed,data:{expected_revision:0,outcome:'accepted',source_note:response.source_note,responded_at:response.responded_at}});
  const row=invitationFixture({revision:1,invitation_state:'accepted',responses:[response]});
  expect(reconcileCollaboration(a,row)).toBe(true);
  for(const patch of [{responses:[]},{responses:[{...response,source_note:'other'}]},{responses:[{...response,responded_at:'2026-09-08T00:00:00Z'}]},{responses:[{...response,revision:2}]}])expect(reconcileCollaboration(a,{...row,...patch})).toBe(false);
  expect(reviewCollaboration(a,observed)).toBe(false);expect(reviewCollaboration(a,{...row,revision:2})).toBe(true);
});
it('suppresses duplicate submissions and replays the identical key/input after an uncertain outcome',async()=>{
  const api=mock();api.update.mockResolvedValueOnce(unknown as never);const h=renderHook(()=>useCollaborationOperation(api));
  await act(async()=>{await h.result.current.execute(command());await h.result.current.execute(command());});
  expect(api.update).toHaveBeenCalledTimes(1);const input=api.update.mock.calls[0][0];
  await act(async()=>{expect(await h.result.current.retry()).toEqual(saved());});expect(api.update.mock.calls[1][0]).toBe(input);expect(h.result.current.locked).toBe(false);
});
it('does not unlock on mismatched success; only exact readback or explicit newer revision review resolves it',async()=>{
  const api=mock();api.update.mockResolvedValueOnce({ok:true,data:invitationFixture({revision:1,notes:'Not mine'})});const h=renderHook(()=>useCollaborationOperation(api));
  await act(async()=>{expect(await h.result.current.execute(command())).toBeNull();});expect(h.result.current.locked).toBe(true);
  act(()=>{expect(h.result.current.confirmReadback(invitationFixture())).toBe(false);expect(h.result.current.reviewReadback(invitationFixture())).toBe(false);});
  act(()=>{expect(h.result.current.reviewReadback(invitationFixture({revision:2}))).toBe(true);});expect(h.result.current.locked).toBe(false);
});
it('fences credentials and late outcomes, and never retries after the bounded key window',async()=>{
  const api=mock();let finish!:(r:Result<ReturnType<typeof saved>>)=>void;api.update.mockImplementationOnce(()=>new Promise(done=>finish=done) as never);
  const h=renderHook(()=>useCollaborationOperation(api));let pending!:Promise<unknown>;
  act(()=>{pending=h.result.current.execute(command());h.result.current.credentialsChanged();});
  await act(async()=>{finish({ok:true,data:saved()});expect(await pending).toBeNull();await h.result.current.retry();});expect(api.update).toHaveBeenCalledTimes(1);expect(h.result.current.locked).toBe(true);
  const other=mock();other.update.mockResolvedValueOnce(unknown as never);const second=renderHook(()=>useCollaborationOperation(other));await act(async()=>{await second.result.current.execute(command());});
  vi.spyOn(Date,'now').mockReturnValue(Date.now()+86400001);await act(async()=>{await second.result.current.retry();});expect(other.update).toHaveBeenCalledTimes(1);
});
