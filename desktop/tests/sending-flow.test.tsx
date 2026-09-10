// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import {App} from '../src/renderer/App';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {activityFixture} from './match-api-mock';
import {gameFixture} from './game-fixtures';
import {preparationFixture,recipientBatchFixture} from './outreach-fixtures';
import {compositionFixture,draftFixture,draftIds,draftValues} from './drafts-fixtures';
import {qualificationFixture,sendBatchFixture,deliveryFixture} from './sending-fixtures';
afterEach(()=>{cleanup();Reflect.deleteProperty(window,'desktop');});
function setup(){
  const activity=activityFixture(),person=preparationFixture({activity_id:activity.id,name:'Fixture Channel'});
  const original=recipientBatchFixture({activity_id:activity.id,recipients:[{id:draftIds.recipient,selection_id:person.id,snapshot:person,preparation:person,source_changed:false,current_missing_fields:[]}]});
  const composition=compositionFixture({activity_id:activity.id,recipient_batch_id:original.id,drafts:[draftFixture({selection_id:person.id,status:'succeeded',values:draftValues,rendered:{subject:'Saved subject',html:'<p>Saved complete email</p>',text:'Saved complete email',fixed_hash:'c'.repeat(64)}})]});
  const api:DesktopBridge={...settingsBridgeMock(),connection:{status:vi.fn(async()=>ok({serviceUrl:'https://workspace.test',hasKey:true,storageAvailable:true})),test:vi.fn(async()=>ok({authenticated:true,proxy:'system',route:'direct'} as const)),save:vi.fn(),clear:vi.fn()},
    library:{list:vi.fn(async()=>ok({items:[],nextCursor:null})),detail:vi.fn()},games:{list:vi.fn(async()=>ok({items:[],total:0,limit:24,offset:0})),detail:vi.fn(async()=>ok(gameFixture('Current game',activity.game_id))),create:vi.fn(),update:vi.fn()},openExternal:vi.fn()};
  vi.mocked(api.match.activities).mockResolvedValue(ok({items:[activity],total:1,limit:50,offset:0}));
  vi.mocked(api.outreach.batch).mockResolvedValue(ok(original));
  vi.mocked(api.drafts.compositions).mockResolvedValue(ok({items:[composition],total:1,offset:0,limit:50}));vi.mocked(api.drafts.composition).mockResolvedValue(ok(composition));
  const qualification=qualificationFixture({activity_id:activity.id}),batch=sendBatchFixture({activity_id:activity.id,qualification,deliveries:[deliveryFixture({state:'sent',attempt:1,sending_at:'2026-09-08T00:00:01Z',sent_at:'2026-09-08T00:00:02Z'})]});
  vi.mocked(api.sending.qualify).mockImplementation(async input=>{const excluded=input.data.excluded;return ok({...qualification,excluded_count:excluded.length,eligible_count:excluded.length?0:1,send_ready:!excluded.length,members:qualification.members.map(m=>({...m,status:excluded.length?'excluded':'eligible',exclusion_reason:excluded[0]?.reason??null}))});});
  vi.mocked(api.sending.send).mockResolvedValue(ok(batch));vi.mocked(api.sending.batch).mockResolvedValue(ok(batch));
  window.desktop=api;render(<App/>);return {api,user:userEvent.setup(),activity};
}
async function openDrafts(user:ReturnType<typeof userEvent.setup>,name:string){
  await user.click(await screen.findByRole('button',{name:'Match'}));await user.click(await screen.findByRole('button',{name:`Open ${name}`}));
  await user.click(await screen.findByRole('button',{name:'Draft history'}));await user.click(await screen.findByRole('button',{name:'Open draft set'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Review sending'})).toBeEnabled());
}
it('runs draft history → explicit qualification → explicit send → frozen deliveries without unrelated writes',async()=>{
  const {api,user,activity}=setup();await openDrafts(user,activity.name);expect(api.sending.qualify).not.toHaveBeenCalled();expect(api.sending.send).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Review sending'}));await user.click(await screen.findByRole('button',{name:'Send 1 email'}));
  expect(await screen.findByRole('region',{name:'Frozen deliveries'})).toBeVisible();expect(screen.getByTitle('Frozen email preview')).toHaveAttribute('srcdoc',expect.stringContaining('Fixture Channel'));
  expect(screen.getAllByText('Accepted by SMTP').length).toBeGreaterThan(0);expect(api.sending.send).toHaveBeenCalledOnce();expect(api.settings.sendTestEmail).not.toHaveBeenCalled();expect(api.drafts.createComposition).not.toHaveBeenCalled();
});
it('keeps exclusion reason through SMTP detour, opens Email directly and blocks workspace replacement',async()=>{
  const {api,user,activity}=setup();await openDrafts(user,activity.name);await user.click(screen.getByRole('button',{name:'Review sending'}));
  await user.click(await screen.findByRole('checkbox',{name:'Exclude Fixture Channel'}));fireEvent.change(screen.getByRole('textbox',{name:'Exclusion reason for Fixture Channel'}),{target:{value:'After the next release'}});
  await user.click(screen.getByRole('button',{name:'SMTP settings'}));expect(screen.getByRole('tab',{name:'Email'})).toHaveAttribute('aria-selected','true');
  expect(await screen.findByRole('button',{name:'Return to Match'})).toBeVisible();await user.click(screen.getByRole('tab',{name:'Workspace'}));expect(screen.getByLabelText('Service URL')).toBeDisabled();expect(screen.getByRole('button',{name:'Disconnect'})).toBeDisabled();
  await user.click(screen.getByRole('button',{name:'Return to Match'}));expect(screen.getByRole('textbox',{name:'Exclusion reason for Fixture Channel'})).toHaveValue('After the next release');
  expect(screen.queryByRole('button',{name:/^Send \d/})).not.toBeInTheDocument();expect(api.sending.qualify).toHaveBeenCalledTimes(1);expect(api.connection.save).not.toHaveBeenCalled();expect(api.settings.sendTestEmail).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Check recipients'}));await waitFor(()=>expect(api.sending.qualify).toHaveBeenCalledTimes(2));expect(api.sending.send).not.toHaveBeenCalled();
});
it('keeps unsaved text in place and does not qualify it as saved mail',async()=>{
  const {api,user,activity}=setup();await openDrafts(user,activity.name);await user.click(screen.getByRole('button',{name:'Edit personalization'}));fireEvent.change(screen.getByRole('textbox',{name:'Observation'}),{target:{value:'Still editing this observation'}});
  expect(screen.getByRole('button',{name:'Review sending'})).toBeDisabled();expect(api.sending.qualify).not.toHaveBeenCalled();
});
