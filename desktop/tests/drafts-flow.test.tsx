// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import {MatchActivity} from '../src/renderer/components/match/MatchActivity';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {activityFixture} from './match-api-mock';
import {gameFixture} from './game-fixtures';
import {preparationFixture,recipientBatchFixture} from './outreach-fixtures';
import {compositionFixture,draftFixture,draftIds,draftValues} from './drafts-fixtures';
import {gameBoundBuiltin as builtinTemplate,gameBoundVersion as templateVersion} from './game-bound-template-fixtures';
afterEach(cleanup);
function setup(){
  const activity=activityFixture(),person=preparationFixture({activity_id:activity.id,name:'Fixture Channel'});
  const batch=recipientBatchFixture({activity_id:activity.id,recipients:[{id:draftIds.recipient,selection_id:person.id,snapshot:person,preparation:person,source_changed:false,current_missing_fields:[]}]});
  let composition=compositionFixture({activity_id:activity.id,recipient_batch_id:batch.id,drafts:[draftFixture({selection_id:person.id,recipient_snapshot_id:draftIds.recipient,status:'succeeded',values:draftValues,rendered:{subject:'Saved subject',html:'<p>A saved complete email</p>',text:'A saved complete email',fixed_hash:templateVersion.fixed_hash}})]});
  const api={...settingsBridgeMock(),games:{detail:vi.fn(async()=>ok(gameFixture('Current game',activity.game_id)))}} as unknown as DesktopBridge;
  vi.mocked(api.outreach.selections).mockResolvedValue(ok({items:[person],total:1,offset:0,limit:200}));
  vi.mocked(api.outreach.freeze).mockImplementation(async input=>ok({...batch,request_id:input.data.request_id}));
  vi.mocked(api.outreach.batch).mockResolvedValue(ok(batch));
  vi.mocked(api.drafts.templates).mockResolvedValue(ok({items:[{...templateVersion,game_id:activity.game_id}],builtin:builtinTemplate}));
  vi.mocked(api.drafts.createComposition).mockImplementation(async()=>ok(composition));
  vi.mocked(api.drafts.composition).mockImplementation(async()=>ok(composition));
  vi.mocked(api.drafts.edit).mockImplementation(async input=>{const updated={...composition.drafts[0],revision:1,values:input.data.values};composition={...composition,drafts:[updated]};return ok(updated);});
  render(<MatchActivity api={api} activityId={activity.id} active onBack={()=>{}} onOpenCreator={()=>{}}/>);
  return {api,user:userEvent.setup()};
}
async function createDrafts(user:ReturnType<typeof userEvent.setup>){
  await user.click(await screen.findByRole('button',{name:'Draft 1 emails'}));
  await user.click(await screen.findByRole('button',{name:'Create 1 drafts'}));
  await user.click(await screen.findByRole('button',{name:'Edit personalization'}));
  await screen.findByRole('textbox',{name:'Observation'});
}
it('connects selected people → frozen preparation → explicit template → draft editing without extra business writes',async()=>{
  const {api,user}=setup();await createDrafts(user);
  expect(api.match.stop).toHaveBeenCalledOnce();expect(api.outreach.freeze).toHaveBeenCalledOnce();expect(api.drafts.createComposition).toHaveBeenCalledOnce();expect(api.drafts.registerCanonical).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('textbox',{name:'Observation'}),{target:{value:'noticed the important scene.'}});
  await user.click(screen.getByRole('button',{name:'Save changes'}));
  await waitFor(()=>expect(api.drafts.edit).toHaveBeenCalledOnce());
  expect(screen.queryByRole('button',{name:/^Send$/i})).not.toBeInTheDocument();expect(api.settings.sendTestEmail).not.toHaveBeenCalled();
});
it('keeps unsaved mail through the in-activity source-repair detour without an unsaved-discard dialog',async()=>{
  const {api,user}=setup();await createDrafts(user);
  fireEvent.change(screen.getByRole('textbox',{name:'Observation'}),{target:{value:'My retained local edit.'}});
  await user.click(screen.getByRole('button',{name:'Edit referenced work source'}));
  const back=await screen.findByRole('button',{name:'Back to drafts'});await waitFor(()=>expect(back).toBeEnabled());await user.click(back);
  await waitFor(()=>expect(screen.getByRole('textbox',{name:'Observation'})).toHaveValue('My retained local edit.'));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(api.drafts.edit).not.toHaveBeenCalled();expect(api.drafts.refresh).not.toHaveBeenCalled();expect(api.drafts.createComposition).toHaveBeenCalledOnce();
});
