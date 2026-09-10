// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import {CreatorRecord} from '../src/renderer/components/creators/CreatorRecord';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {creatorFixture} from './creator-fixtures';
import {invitationFixture} from './collaboration-fixtures';
import type {DesktopBridge} from '../src/shared/bridge';
afterEach(cleanup);
it('uses two shared top-level sections and loads this creator’s invitations only when selected',async()=>{
 const api=settingsBridgeMock() as unknown as DesktopBridge,creator=creatorFixture(),row=invitationFixture({creator_id:creator.id,activity_name:'Game A launch'}),user=userEvent.setup();
 vi.mocked(api.collaboration.creatorHistory).mockResolvedValue(ok({items:[row],total:1,limit:50,offset:0}));
 render(<CreatorRecord api={api} creator={creator} invitationActivityId={row.activity_id} onBack={vi.fn()} onEdit={vi.fn()}/>);
 const tabs=screen.getByRole('tablist',{name:'Creator record sections'});expect(within(tabs).getAllByRole('tab').map(t=>t.textContent)).toEqual(['Profile','Invitations']);
 expect(screen.getAllByRole('tablist')).toHaveLength(1);
 expect(screen.getByRole('button',{name:'Emails'})).toHaveAttribute('aria-expanded','false');
 expect(screen.getByRole('button',{name:'Known works'})).toHaveAttribute('aria-expanded','false');
 expect(api.collaboration.creatorHistory).not.toHaveBeenCalled();await user.click(within(tabs).getByRole('tab',{name:'Invitations'}));
 expect(await screen.findByRole('region',{name:'Invitation relationship'})).toBeVisible();expect(api.collaboration.creatorHistory).toHaveBeenCalledWith({creatorId:creator.id,activityId:row.activity_id,limit:50,offset:0});
 await user.click(screen.getByRole('button',{name:'All activities'}));await screen.findByRole('button',{name:'This activity'});await user.click(within(tabs).getByRole('tab',{name:'Profile'}));expect(screen.getByRole('button',{name:'Edit profile'})).toBeVisible();
 await user.click(within(tabs).getByRole('tab',{name:'Invitations'}));expect(screen.getByRole('button',{name:'This activity'})).toBeVisible();expect(api.collaboration.update).not.toHaveBeenCalled();expect(api.collaboration.respond).not.toHaveBeenCalled();
});
it('uses the caller return label without adding another return action',()=>{
 render(<CreatorRecord api={settingsBridgeMock() as unknown as DesktopBridge} creator={creatorFixture()} onBack={vi.fn()} onEdit={vi.fn()} backLabel="Back to activity"/>);
 expect(screen.getByRole('button',{name:'Back to activity'})).toBeVisible();expect(screen.queryByRole('button',{name:'Back to creators'})).not.toBeInTheDocument();
});
