// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import {CampaignBrief} from '../src/renderer/components/match/CampaignBrief';
import {activityFixture,matchAPIMock} from './match-api-mock';
afterEach(cleanup);
it('does not report success when the save response contains a different brief',async()=>{
 const api=matchAPIMock(),activity={...activityFixture(),revision:0,campaign_brief:null},onSaved=vi.fn(),user=userEvent.setup();
 vi.mocked(api.updateBrief).mockResolvedValue({ok:true,data:{...activity,revision:1,campaign_brief:'Different text'}});
 render(<CampaignBrief api={api} activity={activity} discardToken={0} onStateChange={vi.fn()} onSaved={onSaved}/>);
 await user.click(screen.getByRole('button',{name:'Add campaign brief'}));await user.type(screen.getByRole('textbox',{name:'Campaign brief'}),'My brief');await user.click(screen.getByRole('button',{name:'Save brief'}));
 expect(await screen.findByRole('button',{name:'Check latest brief'})).toBeVisible();expect(screen.getByRole('textbox',{name:'Campaign brief'})).toHaveValue('My brief');expect(onSaved).not.toHaveBeenCalled();expect(api.updateBrief).toHaveBeenCalledOnce();
});
it('edits only the activity brief and cancels without writes',async()=>{
 const api=matchAPIMock(),activity={...activityFixture(),revision:0,campaign_brief:null},user=userEvent.setup();render(<CampaignBrief api={api} activity={activity} discardToken={0} onStateChange={vi.fn()} onSaved={vi.fn()}/>);
 await user.click(screen.getByRole('button',{name:'Add campaign brief'}));expect(screen.getByRole('textbox',{name:'Campaign brief'})).toHaveValue('');await user.type(screen.getByRole('textbox',{name:'Campaign brief'}),'Cozy creators');await user.click(screen.getByRole('button',{name:'Cancel brief'}));expect(api.updateBrief).not.toHaveBeenCalled();
 await user.click(screen.getByRole('button',{name:'Add campaign brief'}));await user.type(screen.getByRole('textbox',{name:'Campaign brief'}),'Cozy creators');await user.click(screen.getByRole('button',{name:'Save brief'}));await waitFor(()=>expect(api.updateBrief).toHaveBeenCalledWith({id:activity.id,data:{campaign_brief:'Cozy creators',expected_revision:0}}));
 expect(api.createActivity).not.toHaveBeenCalled();expect(api.createPlan).not.toHaveBeenCalled();
});
it('keeps text after uncertain save and reads the latest brief before permitting another write',async()=>{
 const api=matchAPIMock(),activity={...activityFixture(),revision:0,campaign_brief:'Original'},user=userEvent.setup();vi.mocked(api.updateBrief).mockResolvedValue({ok:false,error:{code:'save_outcome_unknown',message:'Unknown',retryable:false}});vi.mocked(api.activity).mockResolvedValue({ok:true,data:{...activity,revision:1,campaign_brief:'Other editor',queries:[]}});
 render(<CampaignBrief api={api} activity={activity} discardToken={0} onStateChange={vi.fn()} onSaved={vi.fn()}/>);await user.click(screen.getByRole('button',{name:'Edit campaign brief'}));await user.clear(screen.getByRole('textbox',{name:'Campaign brief'}));await user.type(screen.getByRole('textbox',{name:'Campaign brief'}),'My version');await user.click(screen.getByRole('button',{name:'Save brief'}));await user.click(await screen.findByRole('button',{name:'Check latest brief'}));
 expect(await screen.findByText('Other editor')).toBeVisible();expect(screen.getByText('My version')).toBeVisible();expect(api.updateBrief).toHaveBeenCalledOnce();await user.click(screen.getByRole('button',{name:'Continue editing my brief'}));expect(screen.getByRole('textbox',{name:'Campaign brief'})).toHaveValue('My version');expect(api.updateBrief).toHaveBeenCalledOnce();
});
