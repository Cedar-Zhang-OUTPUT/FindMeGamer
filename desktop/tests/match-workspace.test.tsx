// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {StrictMode} from 'react';
import {act,cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge,Result} from '../src/shared/bridge';
import type {NavigationGuard} from '../src/shared/games';
import type {CreatorDetail} from '../src/shared/creators';
import type {ActivityPage} from '../src/shared/match';
import {MatchWorkspace} from '../src/renderer/components/match/MatchWorkspace';
import {activityFixture,candidateFixture,matchAPIMock} from './match-api-mock';
import {creatorAPIMock} from './creator-api-mock';
import {creatorFixture} from './creator-fixtures';
import {gameFixture} from './game-fixtures';
import {preparationFixture} from './outreach-fixtures';
import {settingsBridgeMock} from './settings-fixtures';
afterEach(cleanup);
const ok=<T,>(data:T):Result<T>=>({ok:true,data});
function setup(){return {...settingsBridgeMock(),match:matchAPIMock(),creators:creatorAPIMock(),games:{list:vi.fn(async()=>ok({items:[gameFixture('A game')],total:1,limit:20,offset:0})),detail:vi.fn(async()=>ok(gameFixture('A game')))},openExternal:vi.fn(async()=>ok(undefined))} as unknown as DesktopBridge;}
it('retains an unresolved Steam request in real Match analysis history instead of a no-op archive',async()=>{
 const api=setup(),user=userEvent.setup();vi.mocked(api.analysis.steamImport).mockResolvedValue({ok:false,error:{code:'analysis_write_unknown',message:'Not confirmed',retryable:false}});
 render(<MatchWorkspace api={api} active/>);await user.click(screen.getByRole('button',{name:'New activity'}));await user.click(screen.getByRole('tab',{name:'Steam'}));await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/1');await user.click(screen.getByRole('button',{name:'Import source'}));
 await screen.findByRole('button',{name:'Check same request'});expect(screen.getByRole('tab',{name:'Library'})).toBeDisabled();expect(screen.queryByRole('button',{name:'Enter manually'})).not.toBeInTheDocument();
 await user.click(screen.getByRole('button',{name:'Keep unresolved request'}));await user.click(screen.getByRole('button',{name:'Save for review and leave'}));await user.click(screen.getByRole('button',{name:'Activities'}));await user.click(screen.getByRole('button',{name:'Analysis tasks'}));
 const record=await screen.findByRole('article',{name:'Unconfirmed: Steam source import'});await user.click(within(record).getByText('Original request'));expect(record).toHaveTextContent('https://store.steampowered.com/app/1');expect(record).toHaveTextContent(vi.mocked(api.analysis.steamImport).mock.calls[0][0].idempotencyKey);expect(api.analysis.steamImport).toHaveBeenCalledOnce();expect(api.match.createActivity).not.toHaveBeenCalled();
});
it('retains the preparation navigation guard during Creator inspection and returns without discarding the draft',async()=>{
  const api=setup(),user=userEvent.setup(),person=preparationFixture({activity_id:activityFixture().id});
  vi.mocked(api.outreach.selections).mockResolvedValue(ok({items:[person],total:1,offset:0,limit:200}));
  let guard:NavigationGuard|null=null;const register=(value:NavigationGuard|null)=>{guard=value;};
  render(<MatchWorkspace api={api} active onNavigationGuardChange={register}/>);
  await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));
  await user.click(await screen.findByRole('button',{name:'Selected · 1'}));
  await user.click(await screen.findByRole('button',{name:'Edit Creator fixture'}));
  const editor=screen.getByRole('region',{name:'Preparation editor'});
  await user.click(within(editor).getByRole('radio',{name:'None'}));
  await user.click(within(editor).getByRole('button',{name:'View creator'}));
  await screen.findByRole('button',{name:'Edit profile'});
  expect(guard).not.toBeNull();const leave=vi.fn();act(()=>{(guard as NavigationGuard|null)?.(leave);});
  const dialog=await screen.findByRole('dialog',{name:'Unsaved Match changes'});await user.click(within(dialog).getByRole('button',{name:'Keep working'}));expect(leave).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Back to activity'}));
  expect(await screen.findByRole('radio',{name:'None'})).toBeChecked();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
async function openCandidate(user:ReturnType<typeof userEvent.setup>,expandDetails=false){
  await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));
  const card=within(await screen.findByRole('article',{name:'Creator 1'}));
  if(expandDetails)await user.click(card.getByText('Discovery details',{selector:'summary'}));
  const trigger=card.getByRole('button',{name:'View creator'});expect(trigger).toBeVisible();await user.click(trigger);return trigger;
}
it('loads server pages of 50, retains failed-page context and retries the requested page',async()=>{
  const api=setup(),user=userEvent.setup();vi.mocked(api.match.activities).mockImplementation(async input=>input?.offset?{ok:false,error:{code:'network_error',message:'Next page unavailable',retryable:true}}:ok({items:[activityFixture()],total:51,limit:50,offset:0}));
  render(<StrictMode><MatchWorkspace api={api} active/></StrictMode>);
  await screen.findByRole('button',{name:'Open Indie launch'});expect(api.match.activities).toHaveBeenLastCalledWith({limit:50,offset:0});
  await user.click(screen.getByRole('button',{name:'Next page'}));await screen.findByText('Next page unavailable');
  expect(screen.getByRole('button',{name:'Open Indie launch'})).toBeVisible();expect(screen.getByText('1–1 of 51')).toBeVisible();
  vi.mocked(api.match.activities).mockResolvedValueOnce(ok({items:[{...activityFixture('older'),name:'Older launch'}],total:51,limit:50,offset:50}));
  await user.click(screen.getByRole('button',{name:'Try again'}));expect(await screen.findByRole('button',{name:'Open Older launch'})).toBeVisible();expect(api.match.activities).toHaveBeenLastCalledWith({limit:50,offset:50});
});
it('creates a real activity from the empty list and opens it without starting a plan',async()=>{
  const api=setup(),user=userEvent.setup();vi.mocked(api.match.activities).mockResolvedValue(ok({items:[],total:0,limit:50,offset:0}));
  vi.mocked(api.match.activity).mockResolvedValue(ok({...activityFixture(),queries:[]}));vi.mocked(api.match.plans).mockResolvedValue(ok({items:[],total:0,offset:0,limit:50}));
  render(<MatchWorkspace api={api} active/>);await screen.findByRole('heading',{name:'No activities yet'});
  await user.click(screen.getByRole('button',{name:'New activity'}));await user.type(screen.getByLabelText('Activity name'),'Indie launch');await user.click(await screen.findByRole('button',{name:'Select game A game'}));await user.click(await screen.findByRole('button',{name:'Use game'}));await user.click(screen.getByRole('button',{name:'Create activity'}));
  expect(await screen.findByRole('heading',{name:'Indie launch'})).toBeVisible();expect(await screen.findByRole('button',{name:'Find creators'})).toBeVisible();expect(api.match.activity).toHaveBeenCalledWith(activityFixture().id);expect(api.match.createPlan).not.toHaveBeenCalled();
});
it('reuses the actual Creator editor and returns to retained activity details with fresh candidates and focus',async()=>{
  const api=setup(),user=userEvent.setup(),creator=creatorFixture('Creator 1',candidateFixture().creator_id);let saved=false;
  vi.mocked(api.creators.detail).mockImplementation(async()=>ok({...creator,favorite:saved,revision:saved?4:3}));vi.mocked(api.creators.update).mockImplementation(async()=>{saved=true;return ok({...creator,favorite:true,revision:4});});
  render(<div className="main-scroll"><MatchWorkspace api={api} active/></div>);
  const trigger=await openCandidate(user,true);await user.click(await screen.findByRole('button',{name:'Edit profile'}));await user.click(screen.getByRole('checkbox',{name:'Saved'}));await user.click(screen.getByRole('button',{name:'Save changes'}));
  expect(await screen.findByRole('button',{name:'Edit profile'})).toBeVisible();expect(api.creators.update).toHaveBeenCalledWith({id:creator.id,data:{expected_revision:3,favorite:true}});
  const before=vi.mocked(api.match.candidates).mock.calls.length;await user.click(screen.getByRole('button',{name:'Back to activity'}));
  await waitFor(()=>expect(api.match.candidates).toHaveBeenCalledTimes(before+1));await waitFor(()=>expect(trigger).toHaveFocus());expect(screen.getByRole('article',{name:'Creator 1'}).querySelector('details')).toHaveAttribute('open');
});
it('keeps the actual editor draft and its navigation guard across visibility changes',async()=>{
  const api=setup(),user=userEvent.setup();let guard:NavigationGuard|null=null;const register=(value:NavigationGuard|null)=>{guard=value;};
  const view=render(<MatchWorkspace api={api} active onNavigationGuardChange={register}/>);await openCandidate(user);await user.click(await screen.findByRole('button',{name:'Edit profile'}));await user.click(screen.getByRole('checkbox',{name:'Saved'}));
  view.rerender(<MatchWorkspace api={api} active={false} onNavigationGuardChange={register}/>);view.rerender(<MatchWorkspace api={api} active onNavigationGuardChange={register}/>);
  expect(screen.getByRole('checkbox',{name:'Saved'})).toBeChecked();const proceed=vi.fn();act(()=>guard?.(proceed));expect(await screen.findByRole('dialog')).toBeVisible();expect(proceed).not.toHaveBeenCalled();
});
it('ignores an inactive late page response and loads the current list on return',async()=>{
  const api=setup();let finish!:(value:Result<ActivityPage>)=>void;vi.mocked(api.match.activities).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  const view=render(<MatchWorkspace api={api} active/>);await waitFor(()=>expect(api.match.activities).toHaveBeenCalledOnce());view.rerender(<MatchWorkspace api={api} active={false}/>);
  await act(async()=>finish(ok({items:[{...activityFixture(),name:'Stale launch'}],total:1,limit:50,offset:0})));view.rerender(<MatchWorkspace api={api} active/>);
  expect(await screen.findByRole('button',{name:'Open Indie launch'})).toBeVisible();expect(screen.queryByRole('button',{name:'Open Stale launch'})).not.toBeInTheDocument();
});
it('does not reopen a creator after leaving its pending read',async()=>{
  const api=setup(),user=userEvent.setup();let finish!:(value:Result<CreatorDetail>)=>void;vi.mocked(api.creators.detail).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  render(<MatchWorkspace api={api} active/>);await openCandidate(user);await screen.findByText('Loading creator…');await user.click(screen.getByRole('button',{name:'Back to activity'}));
  await act(async()=>finish(ok(creatorFixture('Late creator'))));expect(screen.getByRole('article',{name:'Creator 1'})).toBeVisible();expect(screen.queryByRole('heading',{name:'Late creator'})).not.toBeInTheDocument();
});
it('returns contact edits to Emails and reuses identity confirmation without mutating on cancel',async()=>{
  const api=setup(),user=userEvent.setup();const changed={...creatorFixture(),revision:4,contacts:[{...creatorFixture().contacts[0],email:'changed@example.com'}]};
  vi.mocked(api.creators.detail).mockResolvedValueOnce(ok(creatorFixture())).mockResolvedValue(ok(changed));vi.mocked(api.creators.updateContact).mockResolvedValue(ok(changed));
  render(<MatchWorkspace api={api} active/>);await openCandidate(user);await user.click(await screen.findByRole('tab',{name:'Emails'}));await user.click(screen.getByRole('button',{name:'Edit creator@example.com'}));
  await user.clear(screen.getByRole('textbox',{name:'Email'}));await user.type(screen.getByRole('textbox',{name:'Email'}),'changed@example.com');await user.click(screen.getByRole('button',{name:'Save changes'}));
  expect(await screen.findByRole('tab',{name:'Emails'})).toHaveAttribute('aria-selected','true');expect(screen.getByRole('button',{name:'Edit changed@example.com'})).toBeVisible();
  await user.click(screen.getByRole('tab',{name:'Profile'}));await user.click(screen.getByLabelText('Account identity',{selector:'summary'}));await user.click(screen.getByRole('button',{name:'Change identity'}));
  expect(await screen.findByRole('heading',{name:'Change account identity'})).toBeVisible();await user.type(screen.getByLabelText('New account ID'),'UCnew');await user.click(screen.getByRole('button',{name:'Back to activity'}));
  expect(await screen.findByRole('dialog',{name:'Unsaved identity change'})).toBeVisible();await user.click(screen.getByRole('button',{name:'Discard changes'}));expect(await screen.findByRole('article',{name:'Creator 1'})).toBeVisible();expect(api.creators.rebind).not.toHaveBeenCalled();
});
