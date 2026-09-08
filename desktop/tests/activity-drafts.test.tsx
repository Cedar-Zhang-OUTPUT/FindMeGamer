// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useActivityDrafts} from '../src/renderer/components/match/useActivityDrafts';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {gameFixture} from './game-fixtures';
import {recipientBatchFixture,preparationFixture} from './outreach-fixtures';
import {builtinTemplate,compositionFixture,draftFixture,draftIds,draftValues,templateVersion} from './drafts-fixtures';
afterEach(()=>{cleanup();vi.useRealTimers();});
const batch=()=>recipientBatchFixture({id:draftIds.batch,activity_id:draftIds.activity,recipients:[{id:draftIds.recipient,selection_id:draftIds.selection,snapshot:preparationFixture({id:draftIds.selection}),preparation:preparationFixture({id:draftIds.selection}),source_changed:false,current_missing_fields:[]}]});
function setup(){const bridge=settingsBridgeMock();const api={...bridge,games:{detail:vi.fn(async()=>ok(gameFixture('Current game',draftIds.game)))}};vi.mocked(api.drafts.templates).mockResolvedValue(ok({items:[templateVersion],builtin:builtinTemplate}));vi.mocked(api.outreach.batch).mockResolvedValue(ok(batch()));return api;}
it('does no draft reads/writes on discovery; template reads current game and creates only on explicit action',async()=>{
  const api=setup(),view=renderHook(()=>useActivityDrafts({api,activityId:draftIds.activity,gameId:draftIds.game,active:true}));
  expect(api.drafts.templates).not.toHaveBeenCalled();expect(api.drafts.composition).not.toHaveBeenCalled();
  await act(()=>view.result.current.begin(batch()));expect(view.result.current.game?.name).toBe('Current game');expect(api.drafts.registerCanonical).not.toHaveBeenCalled();expect(api.drafts.createComposition).not.toHaveBeenCalled();
  act(()=>view.result.current.selectTemplate(draftIds.template));await act(()=>view.result.current.create());
  expect(view.result.current.mode.kind).toBe('composition');expect(view.result.current.composition?.drafts).toHaveLength(1);
  expect(api.drafts.createComposition).toHaveBeenCalledWith(expect.objectContaining({activityId:draftIds.activity,data:expect.objectContaining({recipient_batch_id:batch().id,template_version_id:draftIds.template,request_id:expect.any(String)}),idempotencyKey:expect.any(String)}));
});
it('retains all original membership and locks an ambiguous creation that returns another recipient',async()=>{
  const api=setup();vi.mocked(api.drafts.createComposition).mockResolvedValue(ok(compositionFixture({drafts:[draftFixture({recipient_snapshot_id:'foreign'})]})));
  const {result}=renderHook(()=>useActivityDrafts({api,activityId:draftIds.activity,gameId:draftIds.game,active:true}));
  await act(()=>result.current.begin(batch()));act(()=>result.current.selectTemplate(draftIds.template));await act(()=>result.current.create());
  expect(result.current.locked).toBe(true);expect(result.current.composition).toBeNull();expect(result.current.batch?.recipients[0].id).toBe(draftIds.recipient);
});
it('history and return are GET only; hidden draft state neither polls nor clears local editing',async()=>{
  const api=setup(),view=renderHook(({active})=>useActivityDrafts({api,activityId:draftIds.activity,gameId:draftIds.game,active,pollMs:20}),{initialProps:{active:true}});
  await act(()=>view.result.current.open(draftIds.composition));act(()=>view.result.current.setDirty('editor',true));
  view.rerender({active:false});const reads=vi.mocked(api.drafts.composition).mock.calls.length;
  await act(()=>new Promise(resolve=>setTimeout(resolve,55)));expect(api.drafts.composition).toHaveBeenCalledTimes(reads);expect(view.result.current.dirty).toBe(true);
  view.rerender({active:true});await waitFor(()=>expect(vi.mocked(api.drafts.composition).mock.calls.length).toBeGreaterThan(reads));
  expect(view.result.current.dirty).toBe(true);expect(api.drafts.refresh).not.toHaveBeenCalled();expect(api.drafts.retry).not.toHaveBeenCalled();expect(api.drafts.createComposition).not.toHaveBeenCalled();
});
it('saves only the current affected draft and preserves the immutable batch',async()=>{
  const api=setup();const before=JSON.stringify(batch());const updated=draftFixture({revision:1,status:'succeeded',values:draftValues});vi.mocked(api.drafts.edit).mockResolvedValue(ok(updated));
  const {result}=renderHook(()=>useActivityDrafts({api,activityId:draftIds.activity,gameId:draftIds.game,active:true}));
  await act(()=>result.current.open(draftIds.composition));await act(()=>result.current.saveDraft(draftValues));
  expect(api.drafts.edit).toHaveBeenCalledWith({id:draftIds.draft,data:{expected_revision:0,context_token:'a'.repeat(64),values:draftValues}});
  expect(result.current.composition?.drafts[0].revision).toBe(1);expect(JSON.stringify(result.current.batch)).toBe(before);expect(api.outreach.update).not.toHaveBeenCalled();
});
it('never lets a delayed background GET replace an acknowledged edit',async()=>{
  const api=setup();let resolveRead!:(value:ReturnType<typeof ok<ReturnType<typeof compositionFixture>>>)=>void;
  const {result}=renderHook(()=>useActivityDrafts({api,activityId:draftIds.activity,gameId:draftIds.game,active:true,pollMs:10}));
  await act(()=>result.current.open(draftIds.composition));
  vi.mocked(api.drafts.composition).mockImplementationOnce(()=>new Promise(resolve=>{resolveRead=resolve;}));
  await waitFor(()=>expect(resolveRead).toBeTypeOf('function'));
  vi.mocked(api.drafts.edit).mockResolvedValue(ok(draftFixture({revision:1,status:'succeeded',values:draftValues})));
  await act(()=>result.current.saveDraft(draftValues));await act(()=>resolveRead(ok(compositionFixture())));
  expect(result.current.composition?.drafts[0].revision).toBe(1);
});
it('invalidates old template choices and history reads when credentials change',async()=>{
  const api=setup(),{result}=renderHook(()=>useActivityDrafts({api,activityId:draftIds.activity,gameId:draftIds.game,active:true}));
  await act(()=>result.current.begin(batch()));act(()=>result.current.selectTemplate(draftIds.template));
  const epoch=result.current.historyEpoch;act(()=>result.current.credentialsChanged());
  expect(result.current.catalog).toBeNull();expect(result.current.game).toBeNull();expect(result.current.historyEpoch).toBeGreaterThan(epoch);
  await act(()=>result.current.create());expect(api.drafts.createComposition).not.toHaveBeenCalled();
});
it('opens a failed history read in the draft task, with an actionable local retry',async()=>{
  const api=setup();vi.mocked(api.drafts.composition).mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Unavailable',retryable:true}});
  const {result}=renderHook(()=>useActivityDrafts({api,activityId:draftIds.activity,gameId:draftIds.game,active:true}));
  await act(()=>result.current.open(draftIds.composition));
  expect(result.current.mode).toEqual({kind:'composition',id:draftIds.composition});expect(result.current.error?.code).toBe('network_error');
  await act(()=>result.current.refresh());expect(result.current.composition?.id).toBe(draftIds.composition);expect(result.current.current).toBe(true);
});
