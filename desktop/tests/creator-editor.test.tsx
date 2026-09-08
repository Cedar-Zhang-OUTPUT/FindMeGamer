// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {CreatorEditor} from '../src/renderer/components/creators/CreatorEditor';
import type {DesktopBridge} from '../src/shared/bridge';
import type {NavigationGuard} from '../src/shared/games';
import {creatorFixture} from './creator-fixtures';
import {creatorAPIMock} from './creator-api-mock';
const failed={ok:false as const,error:{code:'save_outcome_unknown',message:'Result unknown',retryable:false}};
function setup(){const creators=creatorAPIMock();return {creators,api:{creators,games:{list:vi.fn(),detail:vi.fn()}} as unknown as DesktopBridge};}
afterEach(cleanup);
describe('Creator edit sessions',()=>{
  it.each(['save','readback'] as const)('keeps internal navigation intent after onCancel changes while the %s dialog is open',async mode=>{
    const {api,creators}=setup();const base=creatorFixture('Before');const latest={...base,name:'Saved current record',revision:9};const user=userEvent.setup();const saved=vi.fn(),oldCancel=vi.fn(),newCancel=vi.fn();
    vi.mocked(creators.update).mockResolvedValueOnce({ok:true,data:latest});
    if(mode==='readback')vi.mocked(creators.detail).mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Read unavailable',retryable:true}});
    vi.mocked(creators.detail).mockResolvedValue({ok:true,data:latest});
    const view=render(<CreatorEditor api={api} initial={{kind:'creator',base}} onSaved={saved} onCancel={oldCancel}/>);
    await user.clear(screen.getByLabelText('Name'));await user.type(screen.getByLabelText('Name'),'Saved current record');
    if(mode==='readback'){await user.click(screen.getByRole('button',{name:'Save changes'}));await screen.findByText('Read unavailable');}
    await user.click(screen.getByRole('button',{name:'Back to creator'}));
    view.rerender(<CreatorEditor api={api} initial={{kind:'creator',base}} onSaved={saved} onCancel={newCancel}/>);
    const dialog=within(screen.getByRole('dialog'));
    if(mode==='readback')expect(dialog.queryByRole('button',{name:'Leave without reloading'})).not.toBeInTheDocument();
    await user.click(dialog.getByRole('button',{name:mode==='readback'?'Retry current record':'Save and leave'}));
    await waitFor(()=>expect(saved).toHaveBeenCalledWith(latest));
    expect(oldCancel).not.toHaveBeenCalled();expect(newCancel).not.toHaveBeenCalled();
    expect(creators.update).toHaveBeenCalledTimes(1);expect(creators.detail).toHaveBeenCalledTimes(mode==='readback'?2:1);
  });
  it.each(['mine','latest'] as const)('binds confirmation to the selected public name (%s) in a conflict',async choice=>{
    const {api,creators}=setup();const base={...creatorFixture(),public_name:'Old name',public_name_confirmed:true};const latest={...base,public_name:'Latest name',public_name_confirmed:false,revision:8};const saved=vi.fn();const user=userEvent.setup();
    vi.mocked(creators.update).mockResolvedValueOnce({ok:false,error:{code:'creator_revision_conflict',message:'Conflict',retryable:false}}).mockResolvedValue({ok:true,data:{...latest,public_name:'My name',public_name_confirmed:true}});
    vi.mocked(creators.detail).mockResolvedValue({ok:true,data:latest});
    render(<CreatorEditor api={api} initial={{kind:'creator',base}} onSaved={saved} onCancel={()=>{}}/>);
    await user.click(screen.getByText('Display details',{exact:true}));await user.clear(screen.getByLabelText('Public name'));await user.type(screen.getByLabelText('Public name'),'My name');await user.click(screen.getByLabelText('Public name confirmed'));await user.click(screen.getByRole('button',{name:'Save changes'}));
    await user.click(await screen.findByRole('radio',{name:choice==='mine'?'Keep mine: Public name':'Use latest: Public name'}));
    const mine=screen.getByRole('radio',{name:'Keep mine: Public name'});
    const current=screen.getByRole('radio',{name:'Use latest: Public name'});
    expect(within(mine.closest('label')!).getByText('Confirmed',{exact:true})).toBeVisible();
    expect(mine).toHaveAccessibleDescription('Confirmed');
    expect(within(current.closest('label')!).getByText('Not confirmed',{exact:true})).toBeVisible();
    expect(current).toHaveAccessibleDescription('Not confirmed');
    expect(screen.queryByRole('radio',{name:'Keep mine: Public name confirmed'})).not.toBeInTheDocument();
    await user.click(screen.getByRole('button',{name:'Apply choices'}));
    if(choice==='mine'){
      await user.click(screen.getByRole('button',{name:'Save changes'}));
      expect(vi.mocked(creators.update).mock.calls[1][0].data).toEqual({expected_revision:8,public_name:'My name',public_name_confirmed:true});
    }else{
      expect(saved).toHaveBeenCalledWith(latest);expect(creators.update).toHaveBeenCalledTimes(1);
    }
  });
  it('freezes uncertain creation and reconciles a successful replay against latest detail',async()=>{
    const {api,creators}=setup();const saved=vi.fn();const user=userEvent.setup();
    vi.mocked(creators.create).mockResolvedValueOnce(failed);
    vi.mocked(creators.detail).mockResolvedValue({ok:true,data:creatorFixture('Latest creator')});
    render(<CreatorEditor api={api} initial={{kind:'creator',base:null}} onSaved={saved} onCancel={()=>{}}/>);
    await user.type(screen.getByLabelText('Account ID'),'UC_fixture');
    await user.click(screen.getByRole('button',{name:'Create creator'}));
    expect(await screen.findByRole('heading',{name:'Save result unconfirmed'})).toBeVisible();
    expect(screen.getByLabelText('Account ID')).toBeDisabled();
    await user.click(screen.getByRole('button',{name:'Retry same request'}));
    await waitFor(()=>expect(saved).toHaveBeenCalledWith(expect.objectContaining({name:'Latest creator'})));
    const calls=vi.mocked(creators.create).mock.calls;
    expect(calls).toHaveLength(2);expect(calls[1][0]).toEqual(calls[0][0]);
    expect(creators.detail).toHaveBeenCalledWith(creatorFixture().id);
  });
  it('permanently disables old POST replay after same-origin credential replacement',async()=>{
    const {api,creators}=setup();const user=userEvent.setup();let guard:NavigationGuard|null=null;
    vi.mocked(creators.create).mockResolvedValueOnce(failed).mockResolvedValueOnce({ok:false,error:{code:'workspace_key_invalid',message:'Repair key',retryable:false}});
    render(<CreatorEditor api={api} initial={{kind:'creator',base:null}} onSaved={()=>{}} onCancel={()=>{}} onNavigationGuardChange={value=>{guard=value;}} onConnectionRepair={()=>{}}/>);
    await user.type(screen.getByLabelText('Account ID'),'UC_fixture');await user.click(screen.getByRole('button',{name:'Create creator'}));
    await user.click(await screen.findByRole('button',{name:'Retry same request'}));
    await screen.findByRole('button',{name:'Repair connection'});
    act(()=>guard?.recovery?.credentialsChanged());
    expect(screen.getByRole('button',{name:'Retry same request'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'Check records'})).toBeEnabled();expect(creators.create).toHaveBeenCalledTimes(2);
  });
  it('resolves changed fields explicitly against the latest Creator revision',async()=>{
    const {api,creators}=setup();const base=creatorFixture('Before');const latest={...base,name:'Colleague',revision:9};const user=userEvent.setup();
    vi.mocked(creators.update).mockResolvedValueOnce({ok:false,error:{code:'creator_revision_conflict',message:'Conflict',retryable:false}}).mockResolvedValueOnce({ok:true,data:{...latest,name:'My edit',revision:10}});
    vi.mocked(creators.detail).mockResolvedValue({ok:true,data:latest});
    render(<CreatorEditor api={api} initial={{kind:'creator',base}} onSaved={()=>{}} onCancel={()=>{}}/>);
    await user.clear(screen.getByLabelText('Name'));await user.type(screen.getByLabelText('Name'),'My edit');await user.click(screen.getByRole('button',{name:'Save changes'}));
    await user.click(await screen.findByRole('radio',{name:'Keep mine: Name'}));await user.click(screen.getByRole('button',{name:'Apply choices'}));await user.click(screen.getByRole('button',{name:'Save changes'}));
    expect(vi.mocked(creators.update).mock.calls[1][0]).toEqual({id:base.id,data:{expected_revision:9,name:'My edit'}});
  });
  it('offers a fresh conflict read after credential repair invalidates a pending read',async()=>{
    const {api,creators}=setup();const base=creatorFixture('Before');const latest={...base,name:'Latest record',revision:9};const user=userEvent.setup();let guard:NavigationGuard|null=null;
    let resolveOld!:(result:Awaited<ReturnType<typeof creators.detail>>)=>void;
    const old=new Promise<Awaited<ReturnType<typeof creators.detail>>>(resolve=>{resolveOld=resolve;});
    vi.mocked(creators.update).mockResolvedValueOnce({ok:false,error:{code:'creator_revision_conflict',message:'Conflict',retryable:false}});
    vi.mocked(creators.detail).mockResolvedValueOnce({ok:false,error:{code:'workspace_key_invalid',message:'Repair key',retryable:false}}).mockReturnValueOnce(old).mockResolvedValueOnce({ok:true,data:latest});
    render(<CreatorEditor api={api} initial={{kind:'creator',base}} onSaved={()=>{}} onCancel={()=>{}} onNavigationGuardChange={value=>{guard=value;}} onConnectionRepair={()=>{}}/>);
    await user.clear(screen.getByLabelText('Name'));await user.type(screen.getByLabelText('Name'),'My retained draft');await user.click(screen.getByRole('button',{name:'Save changes'}));
    await user.click(await screen.findByRole('button',{name:'Try again'}));
    expect(screen.getByText('Reading current record…')).toBeVisible();
    act(()=>guard?.recovery?.credentialsChanged());
    expect(screen.queryByText('Reading current record…')).not.toBeInTheDocument();
    expect((guard as NavigationGuard|null)?.recovery).toBeDefined();
    await user.click(screen.getByRole('button',{name:'Try again'}));
    expect(await screen.findByText('Latest record')).toBeVisible();
    await act(async()=>resolveOld({ok:true,data:{...base,name:'Stale record',revision:8}}));
    expect(screen.queryByText('Stale record')).not.toBeInTheDocument();
    await user.click(screen.getByRole('radio',{name:'Keep mine: Name'}));await user.click(screen.getByRole('button',{name:'Apply choices'}));
    expect(screen.getByLabelText('Name')).toHaveValue('My retained draft');
    expect(creators.update).toHaveBeenCalledTimes(1);
  });
  it('retries only readback before completing navigation after an accepted save',async()=>{
    const {api,creators}=setup();const base=creatorFixture('Before');const latest={...base,name:'Saved current record',revision:9};const user=userEvent.setup();const saved=vi.fn(),proceed=vi.fn();let guard:NavigationGuard|null=null;
    let resolveRead!:(result:Awaited<ReturnType<typeof creators.detail>>)=>void;
    const read=new Promise<Awaited<ReturnType<typeof creators.detail>>>(resolve=>{resolveRead=resolve;});
    vi.mocked(creators.update).mockResolvedValueOnce({ok:true,data:latest});
    vi.mocked(creators.detail).mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Read unavailable',retryable:true}}).mockReturnValueOnce(read);
    render(<CreatorEditor api={api} initial={{kind:'creator',base}} onSaved={saved} onCancel={()=>{}} onNavigationGuardChange={value=>{guard=value;}}/>);
    await user.clear(screen.getByLabelText('Name'));await user.type(screen.getByLabelText('Name'),'Saved current record');await user.click(screen.getByRole('button',{name:'Save changes'}));
    await screen.findByText('Read unavailable');act(()=>guard?.(proceed));
    const dialog=within(screen.getByRole('dialog'));
    expect(dialog.queryByRole('button',{name:'Save and leave'})).not.toBeInTheDocument();
    await user.click(dialog.getByRole('button',{name:'Retry current record'}));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(creators.update).toHaveBeenCalledTimes(1);expect(creators.detail).toHaveBeenCalledTimes(2);
    expect(proceed).not.toHaveBeenCalled();expect(saved).not.toHaveBeenCalled();
    await act(async()=>resolveRead({ok:true,data:latest}));
    expect(saved).toHaveBeenCalledWith(latest);expect(proceed).toHaveBeenCalledTimes(1);
    expect(creators.update).toHaveBeenCalledTimes(1);
  });
  it('keeps a dirty contact draft when navigation is cancelled and sends parent revision only on Save',async()=>{
    const {api,creators}=setup();const base=creatorFixture();const user=userEvent.setup();let guard:NavigationGuard|null=null;const proceed=vi.fn();
    render(<CreatorEditor api={api} initial={{kind:'contact',base:null,creator:base}} onSaved={()=>{}} onCancel={()=>{}} onNavigationGuardChange={value=>{guard=value;}}/>);
    await user.type(screen.getByLabelText('Email'),'new@example.com');act(()=>guard?.(proceed));
    await screen.findByRole('dialog',{name:'Unsaved creator changes'});await user.keyboard('{Escape}');
    expect(screen.getByLabelText('Email')).toHaveValue('new@example.com');expect(proceed).not.toHaveBeenCalled();expect(creators.createContact).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button',{name:'Add email'}));
    expect(creators.createContact).toHaveBeenCalledWith(expect.objectContaining({creatorId:base.id,data:expect.objectContaining({expected_revision:base.revision,email:'new@example.com'})}));
  });
  it('does not carry a colleague confirmation onto a locally changed public name during conflict merge',async()=>{
    const {api,creators}=setup();const base={...creatorFixture(),public_name:'Old name',public_name_confirmed:false};const user=userEvent.setup();
    vi.mocked(creators.update).mockResolvedValue({ok:false,error:{code:'creator_revision_conflict',message:'Conflict',retryable:false}});
    vi.mocked(creators.detail).mockResolvedValue({ok:true,data:{...base,public_name:'Colleague name',public_name_confirmed:true,revision:7}});
    render(<CreatorEditor api={api} initial={{kind:'creator',base}} onSaved={()=>{}} onCancel={()=>{}}/>);
    await user.click(screen.getByText('Display details',{exact:true}));await user.clear(screen.getByLabelText('Public name'));await user.type(screen.getByLabelText('Public name'),'My name');await user.click(screen.getByRole('button',{name:'Save changes'}));
    await user.click(await screen.findByRole('radio',{name:'Keep mine: Public name'}));await user.click(screen.getByRole('button',{name:'Apply choices'}));
    await user.click(screen.getByText('Display details',{exact:true}));expect(screen.getByLabelText('Public name confirmed')).not.toBeChecked();
  });
});
