// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,within,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {CollaborationWorkspace} from '../src/renderer/components/match/CollaborationWorkspace';
import {useActivityCollaboration} from '../src/renderer/components/match/useActivityCollaboration';
import {invitationFixture} from './collaboration-fixtures';
import {settingsBridgeMock,ok} from './settings-fixtures';
afterEach(cleanup);
function setup(empty=false){
 const api=settingsBridgeMock().collaboration,first=invitationFixture(),second=invitationFixture({selection_id:'second',display_name:'Second creator'}),choose=vi.fn();
 vi.mocked(api.list).mockResolvedValue(ok({items:empty?[]:[first,second],total:empty?0:2,offset:0,limit:50}));
 vi.mocked(api.detail).mockImplementation(async({selectionId})=>ok(selectionId==='second'?second:first));
 function Harness(){const controller=useActivityCollaboration({api,activityId:first.activity_id,active:true});return <CollaborationWorkspace controller={controller} active onOpenCreator={vi.fn()} onChoosePeople={choose}/>;}
 render(<Harness/>);return {api,first,second,choose,user:userEvent.setup()};
}
it('connects compact relationship choices to a persistent current invitation and retains drafts on selection',async()=>{
 const {api,user}=setup();const list=screen.getByRole('complementary',{name:'Invitation list'}),detail=screen.getByRole('region',{name:'Current invitation'});
 await within(detail).findByRole('heading',{name:'Synthetic creator'});
 const first=within(list).getByRole('button',{name:/Synthetic creator/});expect(first).toHaveAttribute('aria-controls',detail.id);expect(first).toHaveAttribute('aria-pressed','true');
 expect(within(first).getByLabelText('Sending: queued')).toBeVisible();expect(within(first).getByLabelText('Response: not invited')).toBeVisible();expect(within(first).getByLabelText('Follow-up: not followed up')).toBeVisible();
 await user.click(within(detail).getByRole('button',{name:'Edit progress'}));await user.type(within(detail).getByLabelText('Notes'),'Retained draft');
 await user.click(within(list).getByRole('button',{name:/Second creator/}));await within(detail).findByRole('heading',{name:'Second creator'});
 await user.click(first);await waitFor(()=>expect(within(detail).getByLabelText('Notes')).toHaveValue('Retained draft'));
 await user.click(within(detail).getByRole('button',{name:'Cancel'}));expect(within(detail).queryByLabelText('Notes')).not.toBeInTheDocument();expect(api.update).not.toHaveBeenCalled();expect(api.respond).not.toHaveBeenCalled();
});
it('keeps unconfirmed save recovery beside the current invitation, with edits intact',async()=>{
 const {api,user}=setup();const detail=screen.getByRole('region',{name:'Current invitation'});
 await user.click(await within(detail).findByRole('button',{name:'Edit progress'}));await user.type(within(detail).getByLabelText('Notes'),'Do not lose');
 vi.mocked(api.update).mockResolvedValue({ok:false,error:{code:'collaboration_write_unknown',message:'Save outcome unknown',retryable:false}});
 await user.click(within(detail).getByRole('button',{name:'Save progress'}));await within(detail).findByRole('button',{name:'Retry original request'});
 expect(within(detail).getByLabelText('Notes')).toHaveValue('Do not lose');expect(within(detail).getByRole('button',{name:'Check current record'})).toBeEnabled();
 expect(screen.getByRole('complementary',{name:'Invitation list'}).querySelector('li button')).toBeDisabled();expect(api.update).toHaveBeenCalledTimes(1);
});
it('keeps the empty-state start action in the invitation list',async()=>{
 const {choose,user}=setup(true);const list=screen.getByRole('complementary',{name:'Invitation list'});
 await user.click(await within(list).findByRole('button',{name:'Choose creators'}));expect(choose).toHaveBeenCalledOnce();
 expect(screen.queryByRole('button',{name:'Record response'})).not.toBeInTheDocument();
});
it('keeps old context disabled while a newly selected relationship is loading',async()=>{
 const {api,user,second}=setup();await screen.findByRole('heading',{name:'Synthetic creator'});
 let resolve!:(value:ReturnType<typeof ok<typeof second>>)=>void;
 vi.mocked(api.detail).mockImplementationOnce(()=>new Promise(done=>resolve=done));
 await user.click(screen.getByRole('button',{name:/Second creator/}));
 expect(screen.getByText('Loading relationship…')).toBeVisible();expect(screen.getByRole('button',{name:'Edit progress'})).toBeDisabled();
 resolve(ok(second));await screen.findByRole('heading',{name:'Second creator'});expect(screen.getByRole('button',{name:'Edit progress'})).toBeEnabled();
});
