// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {CreatorIdentityEditor} from '../src/renderer/components/creators/CreatorIdentityEditor';
import type {DesktopBridge} from '../src/shared/bridge';
import {creatorFixture} from './creator-fixtures';
import {creatorAPIMock} from './creator-api-mock';
afterEach(cleanup);
function start(){const creators=creatorAPIMock(),initial=creatorFixture(),saved=vi.fn();render(<CreatorIdentityEditor api={{creators} as DesktopBridge} initial={initial} onSaved={saved} onCancel={()=>{}}/>);return{creators,initial,saved,user:userEvent.setup()};}
describe('Explicit Creator identity change',()=>{
  it('requires old/new review and keeps input after cancelling confirmation',async()=>{
    const {user,creators,initial,saved}=start();
    await user.type(screen.getByLabelText('New account ID'),'UC_new_fixture');await user.click(screen.getByRole('button',{name:'Review identity change'}));
    const dialog=screen.getByRole('dialog',{name:'Change account identity?'});
    expect(dialog).toHaveTextContent(initial.source_identity.account_id!);expect(dialog).toHaveTextContent('UC_new_fixture');expect(creators.rebind).not.toHaveBeenCalled();
    await user.keyboard('{Escape}');expect(screen.getByLabelText('New account ID')).toHaveValue('UC_new_fixture');
    await user.click(screen.getByRole('button',{name:'Review identity change'}));await user.click(screen.getByRole('button',{name:'Change identity'}));
    await waitFor(()=>expect(saved).toHaveBeenCalled());
    expect(creators.rebind).toHaveBeenCalledExactlyOnceWith({id:initial.id,data:{platform:'youtube',account_id:'UC_new_fixture',expected_revision:initial.revision,confirmed:true}});
    expect(creators.detail).toHaveBeenCalledWith(initial.id);
  });
  it('does not blindly repeat an uncertain PUT and requires reading the current identity',async()=>{
    const {user,creators}=start();vi.mocked(creators.rebind).mockResolvedValue({ok:false,error:{code:'save_outcome_unknown',message:'Unknown',retryable:false}});
    await user.type(screen.getByLabelText('New account ID'),'UC_new_fixture');await user.click(screen.getByRole('button',{name:'Review identity change'}));await user.click(screen.getByRole('button',{name:'Change identity'}));
    expect(await screen.findByRole('button',{name:'Check current identity'})).toBeEnabled();expect(screen.getByLabelText('New account ID')).toBeDisabled();
    expect(creators.rebind).toHaveBeenCalledTimes(1);await user.click(screen.getByRole('button',{name:'Check current identity'}));
    await screen.findByRole('button',{name:'Review change against current record'});expect(creators.rebind).toHaveBeenCalledTimes(1);
  });
  it('preserves identity draft on a blocking analysis state without automatic retry',async()=>{
    const {user,creators}=start();vi.mocked(creators.rebind).mockResolvedValue({ok:false,error:{code:'creator_analysis_in_progress',message:'Analysis is running. Wait until it finishes.',retryable:false}});
    await user.type(screen.getByLabelText('New account ID'),'UC_new_fixture');await user.click(screen.getByRole('button',{name:'Review identity change'}));await user.click(screen.getByRole('button',{name:'Change identity'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Analysis is running');expect(screen.getByLabelText('New account ID')).toHaveValue('UC_new_fixture');expect(creators.rebind).toHaveBeenCalledTimes(1);
  });
});
