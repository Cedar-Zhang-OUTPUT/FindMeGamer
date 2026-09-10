// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import {App} from '../src/renderer/App';
import type {DesktopBridge} from '../src/shared/bridge';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {activityFixture,planFixture} from './match-api-mock';
import {invitationFixture} from './collaboration-fixtures';
afterEach(()=>{cleanup();Reflect.deleteProperty(window,'desktop');});
function setup(){
 const row=invitationFixture({activity_id:activityFixture().id,activity_name:'Indie launch'}),api={...settingsBridgeMock(),connection:{status:vi.fn(async()=>ok({hasKey:true,serviceUrl:'https://workspace.example.com',storageAvailable:true})),test:vi.fn(async()=>ok({authenticated:true,proxy:'system',route:'direct'})),save:vi.fn(),clear:vi.fn()},openExternal:vi.fn()} as unknown as DesktopBridge;
 vi.mocked(api.collaboration.list).mockResolvedValue(ok({items:[row],total:1,offset:0,limit:50}));vi.mocked(api.collaboration.detail).mockResolvedValue(ok(row));
 window.desktop=api;render(<App/>);return {api,row,user:userEvent.setup()};
}
it('opens real activities from Outreach and defaults to their invitation list without creating or sending',async()=>{
 const {api,row,user}=setup();await screen.findByRole('button',{name:'Open Pixel Harbor'});await user.click(screen.getByRole('button',{name:'Outreach'}));
 await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));expect(await screen.findByRole('table',{name:'Invitation relationships'})).toBeVisible();expect(screen.getByRole('tab',{name:'Invitations'})).toHaveAttribute('aria-selected','true');
 expect(api.collaboration.list).toHaveBeenCalledWith(expect.objectContaining({activityId:row.activity_id}));expect(api.match.createActivity).not.toHaveBeenCalled();expect(api.sending.send).not.toHaveBeenCalled();expect(screen.queryByText('Not connected yet')).not.toBeInTheDocument();
});
it('keeps one activity session when going from Match to Outreach and continuing discovery',async()=>{
 const {api,user}=setup();await screen.findByRole('button',{name:'Open Pixel Harbor'});await user.click(screen.getByRole('button',{name:'Match'}));await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));
 await screen.findByRole('article',{name:'Creator 1'});const reads=vi.mocked(api.match.activity).mock.calls.length;
 expect(screen.queryByRole('tab',{name:'Invitations'})).not.toBeInTheDocument();
 await user.click(screen.getByRole('button',{name:'Open in Outreach'}));await screen.findByRole('table',{name:'Invitation relationships'});await user.selectOptions(screen.getByLabelText('Response',{selector:'select'}),'accepted');
 await user.click(screen.getByRole('button',{name:'Continue in Match'}));expect(screen.getByRole('button',{name:'Match'})).toHaveAttribute('aria-current','page');expect(await screen.findByRole('article',{name:'Creator 1'})).toBeVisible();expect(api.match.activity).toHaveBeenCalledTimes(reads);
 await user.click(screen.getByRole('button',{name:'Outreach'}));expect(await screen.findByLabelText('Response',{selector:'select'})).toHaveValue('accepted');expect(api.match.continueDiscovery).not.toHaveBeenCalled();
});
it('keeps first-search focus in Match and guards the Outreach shortcut without submitting conditions',async()=>{
 const {api,user}=setup();vi.mocked(api.match.activity).mockResolvedValue(ok({...activityFixture(),queries:[]}));vi.mocked(api.match.plans).mockResolvedValue(ok({items:[],total:0,offset:0,limit:50}));
 await screen.findByRole('button',{name:'Open Pixel Harbor'});await user.click(screen.getByRole('button',{name:'Match'}));await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));
 await screen.findByRole('form',{name:'Discovery conditions'});expect(screen.queryByRole('tablist',{name:'Activity workspace'})).not.toBeInTheDocument();expect(api.collaboration.list).not.toHaveBeenCalled();
 await user.type(screen.getByLabelText('Content keywords'),'cozy');await user.click(screen.getByRole('button',{name:'Add keyword'}));
 await user.click(screen.getByRole('button',{name:'Open in Outreach'}));let dialog=await screen.findByRole('dialog',{name:'Unsaved Match changes'});await user.click(within(dialog).getByRole('button',{name:'Keep working'}));
 expect(screen.getByRole('button',{name:'Remove keyword cozy'})).toBeVisible();expect(api.collaboration.list).not.toHaveBeenCalled();
 await user.click(screen.getByRole('button',{name:'Open in Outreach'}));dialog=await screen.findByRole('dialog',{name:'Unsaved Match changes'});await user.click(within(dialog).getByRole('button',{name:'Discard changes'}));
 expect(await screen.findByRole('tab',{name:'Invitations'})).toHaveAttribute('aria-selected','true');await screen.findByRole('table',{name:'Invitation relationships'});
 expect(api.collaboration.list).toHaveBeenCalledWith(expect.objectContaining({activityId:activityFixture().id}));await user.click(screen.getByRole('button',{name:'Continue in Match'}));expect(await screen.findByRole('form',{name:'Discovery conditions'})).toBeVisible();
 expect(api.match.createActivity).not.toHaveBeenCalled();expect(api.match.createPlan).not.toHaveBeenCalled();expect(api.match.continueDiscovery).not.toHaveBeenCalled();expect(api.sending.send).not.toHaveBeenCalled();
});
it('preserves Outreach progress edits through SMTP Settings and guards leaving for Match',async()=>{
 const {api,user}=setup();await screen.findByRole('button',{name:'Open Pixel Harbor'});await user.click(screen.getByRole('button',{name:'Outreach'}));await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));
 await user.click(await screen.findByRole('button',{name:'Update relationship for Synthetic creator'}));await user.click(await screen.findByRole('button',{name:'Edit progress'}));await user.type(screen.getByLabelText('Notes'),'Retain outreach draft');await user.click(screen.getByRole('button',{name:'Email settings'}));
 expect(await screen.findByRole('tab',{name:'Email'})).toHaveAttribute('aria-selected','true');await user.click(screen.getByRole('button',{name:'Return to Outreach'}));await waitFor(()=>expect(screen.getByLabelText('Notes')).toBeEnabled());expect(screen.getByLabelText('Notes')).toHaveValue('Retain outreach draft');
 await user.click(screen.getByRole('button',{name:'Continue in Match'}));const dialog=await screen.findByRole('dialog',{name:'Unsaved Match changes'});await user.click(within(dialog).getByRole('button',{name:'Keep working'}));expect(screen.getByRole('button',{name:'Outreach'})).toHaveAttribute('aria-current','page');expect(api.settings.sendTestEmail).not.toHaveBeenCalled();
});
it('retains a failed planning task and its explicit retry after an Outreach round trip',async()=>{
 const {api,user}=setup(),failed={...planFixture('failed'),query_id:null,error_code:'planning_model_output_invalid',retryable:true};
 vi.mocked(api.match.activity).mockResolvedValue(ok({...activityFixture(),queries:[]}));vi.mocked(api.match.plans).mockResolvedValue(ok({items:[failed],total:1,offset:0,limit:50}));vi.mocked(api.match.plan).mockResolvedValue(ok(failed));
 await screen.findByRole('button',{name:'Open Pixel Harbor'});await user.click(screen.getByRole('button',{name:'Match'}));await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));await screen.findByRole('button',{name:'Retry planning'});
 const history=screen.getByLabelText('Search history') as HTMLSelectElement,selected=history.value;
 await user.click(screen.getByRole('button',{name:'Open in Outreach'}));await screen.findByRole('table',{name:'Invitation relationships'});await user.click(screen.getByRole('button',{name:'Continue in Match'}));
 expect(await screen.findByRole('button',{name:'Retry planning'})).toBeEnabled();expect(screen.getByLabelText('Search history')).toHaveValue(selected);expect(api.match.retryPlan).not.toHaveBeenCalled();expect(api.match.createPlan).not.toHaveBeenCalled();expect(api.match.createActivity).not.toHaveBeenCalled();expect(api.sending.send).not.toHaveBeenCalled();
});
it('opens the shared Creator record in the source activity context and returns to retained invitation filters',async()=>{
 const {api,row,user}=setup();vi.mocked(api.collaboration.creatorHistory).mockResolvedValue(ok({items:[row],total:1,limit:50,offset:0}));await screen.findByRole('button',{name:'Open Pixel Harbor'});await user.click(screen.getByRole('button',{name:'Outreach'}));await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));await screen.findByRole('table',{name:'Invitation relationships'});
 await user.selectOptions(screen.getByLabelText('Follow-up',{selector:'select'}),'follow_up_needed');await user.click(await screen.findByRole('button',{name:'Synthetic creator'}));expect(await screen.findByRole('tab',{name:'Invitations'})).toHaveAttribute('aria-selected','true');
 await waitFor(()=>expect(api.collaboration.creatorHistory).toHaveBeenCalledWith({creatorId:row.creator_id,activityId:row.activity_id,limit:50,offset:0}));expect(screen.getByRole('button',{name:'All activities'})).toBeVisible();await user.click(screen.getByRole('button',{name:'Back to activity'}));expect(await screen.findByLabelText('Follow-up',{selector:'select'})).toHaveValue('follow_up_needed');
});
