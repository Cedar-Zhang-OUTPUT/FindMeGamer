// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useActivitySending} from '../src/renderer/components/match/useActivitySending';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {compositionFixture,draftIds} from './drafts-fixtures';
import {qualificationFixture,sendBatchFixture,deliveryFixture} from './sending-fixtures';
import type {Result} from '../src/shared/bridge';
import type {Qualification,SendBatch} from '../src/shared/sending';
afterEach(cleanup);
function setup(){const api=settingsBridgeMock().sending,composition=compositionFixture();const props={api,activityId:draftIds.activity,composition,active:true,blocked:false,pollMs:100000};return {api,props,...renderHook(p=>useActivitySending(p),{initialProps:props})};}
it('does not check or send until explicitly requested and rejects lost all-N membership',async()=>{
  const {api,result}=setup();expect(api.qualify).not.toHaveBeenCalled();expect(api.send).not.toHaveBeenCalled();
  vi.mocked(api.qualify).mockResolvedValueOnce(ok(qualificationFixture({members:[],total_count:0})));
  await act(()=>result.current.begin());expect(result.current.qualificationCurrent).toBe(false);expect(result.current.error?.code).toBe('sending_scope_mismatch');expect(api.send).not.toHaveBeenCalled();
});
it('invalidates a late qualification after exclusion edit and retains reasons through detours',async()=>{
  const {api,result}=setup();let finish!:(value:Result<Qualification>)=>void;vi.mocked(api.qualify).mockImplementationOnce(()=>new Promise(done=>finish=done));
  act(()=>{void result.current.begin();});act(()=>result.current.changeExclusions([{draft_id:draftIds.draft,reason:'Next release'}]));
  await act(async()=>finish(ok(qualificationFixture())));expect(result.current.qualificationCurrent).toBe(false);
  act(()=>result.current.backToDrafts());expect(result.current.exclusions).toEqual([{draft_id:draftIds.draft,reason:'Next release'}]);expect(api.send).not.toHaveBeenCalled();
});
it('requires a fresh explicit qualification after returning from settings',async()=>{
  const {result,rerender,props,api}=setup();await act(()=>result.current.begin());expect(result.current.qualificationCurrent).toBe(true);
  rerender({...props,active:false});rerender(props);expect(result.current.qualificationCurrent).toBe(false);expect(api.qualify).toHaveBeenCalledTimes(1);
  await act(()=>result.current.send());expect(api.send).not.toHaveBeenCalled();await act(()=>result.current.checkQualification());expect(result.current.qualificationCurrent).toBe(true);
});
it('blocks a previously rendered Send callback immediately when exclusions change',async()=>{
  const {result,api}=setup();await act(()=>result.current.begin());const send=result.current.send;
  await act(async()=>{result.current.changeExclusions([{draft_id:draftIds.draft,reason:'Later'}]);await send();});
  expect(api.send).not.toHaveBeenCalled();expect(result.current.qualificationCurrent).toBe(false);
});
it('sends only the checked frozen request and replays the same UUID and key after queue uncertainty',async()=>{
  const {result,api}=setup();await act(()=>result.current.begin());
  vi.mocked(api.send).mockResolvedValueOnce({ok:false,error:{code:'send_queue_unavailable',message:'Dispatch unavailable',retryable:false}}).mockResolvedValueOnce(ok(sendBatchFixture()));
  await act(()=>result.current.send());expect(result.current.locked).toBe(true);const original=vi.mocked(api.send).mock.calls[0][0];
  act(()=>result.current.changeExclusions([{draft_id:draftIds.draft,reason:'Must not replace frozen input'}]));await act(()=>result.current.retryOriginal());
  expect(api.send).toHaveBeenLastCalledWith(original);expect(result.current.mode.kind).toBe('deliveries');expect(result.current.batch?.id).toBe(sendBatchFixture().id);
});
it('never retries unknown deliveries and records not-sent without resending',async()=>{
  const {result,api}=setup(),unknown=deliveryFixture({state:'unknown',attempt:1,error_code:'smtp_outcome_unknown',sending_at:'2026-09-08T00:01:00Z'}),batch=sendBatchFixture({deliveries:[unknown]});
  vi.mocked(api.batch).mockResolvedValue(ok(batch));await act(()=>result.current.openBatch(batch.id));
  await act(()=>result.current.retryDelivery(unknown.id));expect(api.retry).not.toHaveBeenCalled();
  const at='2026-09-08T00:05:00Z';vi.mocked(api.resolve).mockResolvedValue(ok({...unknown,state:'failed',retryable:true,error_code:'submission_verified_not_sent',failed_at:at,resolution:{outcome:'not_sent',source_note:'Capture log confirms no submission',at,attempt:1}}));
  await act(()=>result.current.resolveDelivery(unknown.id,{expected_attempt:1,outcome:'not_sent',source_note:'Capture log confirms no submission'}));
  expect(api.resolve).toHaveBeenCalledOnce();expect(api.retry).not.toHaveBeenCalled();expect(api.send).not.toHaveBeenCalled();expect(result.current.batch?.deliveries[0].state).toBe('failed');
});
it('fences old batch reads after credentials replacement without clearing local verification input',async()=>{
  const {result,api}=setup();let finish!:(value:Result<SendBatch>)=>void;vi.mocked(api.batch).mockImplementationOnce(()=>new Promise(done=>finish=done));
  act(()=>{void result.current.openBatch(sendBatchFixture().id);result.current.setVerificationDirty(true);});act(()=>result.current.credentialsChanged());
  await act(async()=>finish(ok(sendBatchFixture())));expect(result.current.batch).toBeNull();expect(result.current.current).toBe(false);expect(result.current.dirty).toBe(true);
});
it('does not adopt changed immutable snapshots from batch polling',async()=>{
  const {result,api}=setup();await act(()=>result.current.openBatch(sendBatchFixture().id));
  vi.mocked(api.batch).mockResolvedValue(ok(sendBatchFixture({deliveries:[deliveryFixture({snapshot:{...deliveryFixture().snapshot,recipient_email:'changed@example.test'}})]})));
  await act(()=>result.current.refreshBatch());expect(result.current.current).toBe(false);expect(result.current.batch?.deliveries[0].snapshot.recipient_email).toBe('synthetic-recipient@example.test');expect(result.current.error?.code).toBe('sending_scope_mismatch');
});
