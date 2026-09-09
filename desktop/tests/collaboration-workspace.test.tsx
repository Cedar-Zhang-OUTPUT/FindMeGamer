// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import type {NavigationGuard} from '../src/shared/games';
import {MatchWorkspace} from '../src/renderer/components/match/MatchWorkspace';
import {CreatorInvitationHistory} from '../src/renderer/components/creators/CreatorInvitationHistory';
import {CollaborationEditor} from '../src/renderer/components/match/CollaborationEditor';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {invitationFixture} from './collaboration-fixtures';
import {activityFixture} from './match-api-mock';
afterEach(cleanup);
it('keeps invitation edits and its parent exit guard through Creator inspection and workspace tabs',async()=>{
 const api={...settingsBridgeMock(),openExternal:vi.fn()} as unknown as DesktopBridge,user=userEvent.setup(),row=invitationFixture({activity_id:activityFixture().id});
 vi.mocked(api.collaboration.list).mockResolvedValue(ok({items:[row],total:1,offset:0,limit:50}));vi.mocked(api.collaboration.detail).mockResolvedValue(ok(row));let guard:NavigationGuard|null=null;
 render(<MatchWorkspace api={api} active surface="outreach" onNavigationGuardChange={g=>{guard=g;}}/>);await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));await user.click(screen.getByRole('tab',{name:'Invitations'}));
 await user.click(await screen.findByRole('button',{name:'Edit progress'}));await user.type(screen.getByLabelText('Notes'),'Keep my notes');await user.click(screen.getByRole('button',{name:'Open creator'}));expect(await screen.findByRole('tab',{name:'Invitations'})).toHaveAttribute('aria-selected','true');await user.click(screen.getByRole('tab',{name:'Profile'}));await screen.findByRole('button',{name:'Edit profile'});
 const exit=vi.fn();act(()=>guard?.(exit));await user.click(await screen.findByRole('button',{name:'Keep working'}));expect(exit).not.toHaveBeenCalled();await user.click(screen.getByRole('button',{name:'Back to activity'}));
 await waitFor(()=>expect(screen.getByLabelText('Notes')).toBeEnabled());expect(screen.getByLabelText('Notes')).toHaveValue('Keep my notes');
 await user.click(screen.getByRole('tab',{name:'Prepare & send'}));await user.click(screen.getByRole('tab',{name:'Invitations'}));expect(screen.getByLabelText('Notes')).toHaveValue('Keep my notes');
 expect(api.collaboration.update).not.toHaveBeenCalled();expect(api.collaboration.respond).not.toHaveBeenCalled();
});
it('loads Creator history only on demand and offers no writes, including historic creator associations',async()=>{
 const api=settingsBridgeMock().collaboration,user=userEvent.setup(),row=invitationFixture({creator_id:'historically-rebound'});vi.mocked(api.creatorHistory).mockResolvedValue(ok({items:[row],total:1,offset:0,limit:50}));
 render(<CreatorInvitationHistory api={api} creatorId="original-creator" active/>);expect(api.creatorHistory).not.toHaveBeenCalled();await user.click(screen.getByText('Invitation history'));await user.click(await screen.findByRole('button',{name:'C synthetic Activity · not invited'}));
 expect(screen.getByRole('region',{name:'Invitation relationship'})).toBeVisible();expect(screen.queryByRole('button',{name:'Record response'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Edit progress'})).not.toBeInTheDocument();expect(api.update).not.toHaveBeenCalled();
});
it('clears only a specifically confirmed edit while preserving another relationship draft',async()=>{
 const user=userEvent.setup(),first=invitationFixture(),second=invitationFixture({selection_id:'second',display_name:'Second'}),props={current:true,busy:false,onUpdate:vi.fn(async()=>false),onRespond:vi.fn(async()=>false),onDirtyChange:vi.fn()};
 const view=render(<CollaborationEditor {...props} invitation={first}/>);await user.click(screen.getByRole('button',{name:'Edit progress'}));await user.type(screen.getByLabelText('Notes'),'First');
 view.rerender(<CollaborationEditor {...props} invitation={second}/>);await user.click(screen.getByRole('button',{name:'Edit progress'}));await user.type(screen.getByLabelText('Notes'),'Second');
 const confirmedChange={activityId:first.activity_id,selectionId:first.selection_id,revision:0,kind:'update' as const};view.rerender(<CollaborationEditor {...props} invitation={second} confirmedChange={confirmedChange}/>);expect(screen.getByLabelText('Notes')).toHaveValue('Second');
 view.rerender(<CollaborationEditor {...props} invitation={{...first,revision:1,notes:'First'}} confirmedChange={confirmedChange}/>);expect(screen.queryByLabelText('Notes')).not.toBeInTheDocument();expect(within(screen.getByRole('region')).getByText('First')).toBeVisible();expect(props.onDirtyChange).toHaveBeenLastCalledWith(true);
});
it('returns keyboard focus to the current workspace tab while the original Creator opener is reloading',async()=>{
 const api={...settingsBridgeMock(),openExternal:vi.fn()} as unknown as DesktopBridge,user=userEvent.setup(),row=invitationFixture({activity_id:activityFixture().id});vi.mocked(api.collaboration.list).mockResolvedValue(ok({items:[row],total:1,offset:0,limit:50}));vi.mocked(api.collaboration.detail).mockResolvedValue(ok(row));
 render(<MatchWorkspace api={api} active surface="outreach"/>);await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));await user.click(screen.getByRole('tab',{name:'Invitations'}));await user.click(await screen.findByRole('button',{name:'Open creator'}));expect(await screen.findByRole('tab',{name:'Invitations'})).toHaveAttribute('aria-selected','true');await user.click(screen.getByRole('tab',{name:'Profile'}));await screen.findByRole('button',{name:'Edit profile'});
 vi.mocked(api.collaboration.detail).mockImplementationOnce(()=>new Promise(()=>{}));await user.click(screen.getByRole('button',{name:'Back to activity'}));
 await waitFor(()=>expect(screen.getByRole('tab',{name:'Invitations'})).toHaveFocus());expect(screen.getByRole('button',{name:'Open creator'})).toBeDisabled();
});
