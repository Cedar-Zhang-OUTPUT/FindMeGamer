// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import {NewActivity} from '../src/renderer/components/match/NewActivity';
import {matchAPIMock,activityFixture} from './match-api-mock';
import {gameFixture} from './game-fixtures';
import type {NavigationGuard} from '../src/shared/games';
afterEach(cleanup);
it('protects a brief-only manual game draft while editing and after returning to game selection',async()=>{
 const api={match:matchAPIMock(),games:{list:vi.fn(async()=>({ok:true,data:{items:[],total:0,offset:0,limit:20}}))},analysis:{steamImport:vi.fn(async()=>({ok:false,error:{code:'source_unavailable',message:'Unavailable',retryable:false}}))}} as unknown as DesktopBridge;
 let guard:NavigationGuard|null=null;const cancel=vi.fn(),leave=vi.fn(),user=userEvent.setup();
 render(<NewActivity api={api} onCreated={vi.fn()} onCancel={cancel} onNavigationGuardChange={value=>{guard=value;}}/>);
 await user.click(screen.getByRole('tab',{name:'Steam'}));await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/123');await user.click(screen.getByRole('button',{name:'Import source'}));await user.click(await screen.findByRole('button',{name:'Enter manually'}));await user.click(screen.getByText('Campaign brief · Optional'));await user.type(screen.getByLabelText('Campaign brief'),'Only this activity');
 act(()=>guard?.(leave));const source=await screen.findByRole('alertdialog',{name:'Leave source import'});expect(source).toBeVisible();await user.click(within(source).getByRole('button',{name:'Discard link and leave'}));const dialog=await screen.findByRole('dialog',{name:'Unsaved Match changes'});expect(dialog).toBeVisible();await user.click(within(dialog).getByRole('button',{name:'Keep working'}));expect(screen.getByLabelText('Campaign brief')).toHaveValue('Only this activity');expect(leave).not.toHaveBeenCalled();
 await user.click(screen.getByRole('button',{name:'Back to games'}));await user.click(screen.getByRole('button',{name:'Activities'}));expect(await screen.findByRole('dialog',{name:'Unsaved Match changes'})).toBeVisible();expect(cancel).not.toHaveBeenCalled();expect(api.match.createActivity).not.toHaveBeenCalled();
});
it('retains Library search and Steam input across same-context tabs without importing on paste',async()=>{
 const {api,user}=setup();api.analysis={steamImport:vi.fn()} as unknown as DesktopBridge['analysis'];
 await user.type(screen.getByRole('searchbox',{name:'Search games'}),'Harbor');
 await user.click(screen.getByRole('tab',{name:'Steam'}));
 await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/1');
 await user.click(screen.getByRole('tab',{name:'Library'}));expect(screen.getByRole('searchbox',{name:'Search games'})).toHaveValue('Harbor');
 await user.click(screen.getByRole('tab',{name:'Steam'}));expect(screen.getByRole('textbox',{name:'Steam URL'})).toHaveValue('https://store.steampowered.com/app/1');
 expect(api.analysis.steamImport).not.toHaveBeenCalled();expect(api.match.createActivity).not.toHaveBeenCalled();
});
it('reviews a Library handoff before creating an activity and accepts unchanged incomplete records',async()=>{
 const match=matchAPIMock(),game=gameFixture('From Library'),api={match,games:{list:vi.fn(async()=>({ok:true,data:{items:[],total:0,offset:0,limit:20}}))}} as unknown as DesktopBridge;
 render(<NewActivity api={api} initialGame={game} onCreated={vi.fn()} onCancel={vi.fn()}/>);
 expect(screen.getByRole('textbox',{name:'Name'})).toHaveValue('From Library');expect(match.createActivity).not.toHaveBeenCalled();
 await userEvent.setup().click(screen.getByRole('button',{name:'Continue to matching'}));await waitFor(()=>expect(match.createActivity).toHaveBeenCalledOnce());
});
it('keeps the named activity guard active during pristine and dirty game review',async()=>{
 const game=gameFixture('Review game'),api={match:matchAPIMock(),games:{list:vi.fn(async()=>({ok:true,data:{items:[game],total:1,offset:0,limit:20}})),detail:vi.fn(async()=>({ok:true,data:game}))}} as unknown as DesktopBridge;
 let guard:NavigationGuard|null=null;render(<NewActivity api={api} onCreated={vi.fn()} onCancel={vi.fn()} onNavigationGuardChange={value=>{guard=value;}}/>);
 const user=userEvent.setup(),leave=vi.fn();await user.click(await screen.findByRole('button',{name:'Use game Review game'}));await user.click(await screen.findByText('Activity name · Optional'));await user.type(screen.getByLabelText('Activity name'),'Do not lose');
 act(()=>guard?.(leave));let dialog=await screen.findByRole('dialog',{name:'Unsaved Match changes'});expect(dialog).toBeVisible();await user.click(within(dialog).getByRole('button',{name:'Keep working'}));expect(leave).not.toHaveBeenCalled();
 await user.type(screen.getByRole('textbox',{name:'Name'}),' changed');act(()=>guard?.(leave));dialog=await screen.findByRole('dialog',{name:'Unsaved game changes'});await user.click(within(dialog).getByRole('button',{name:'Discard changes'}));
 dialog=await screen.findByRole('dialog',{name:'Unsaved Match changes'});expect(dialog).toBeVisible();expect(leave).not.toHaveBeenCalled();await user.click(within(dialog).getByRole('button',{name:'Keep working'}));await user.click(await screen.findByRole('button',{name:'Use game Review game'}));await user.click(await screen.findByText('Activity name · Optional'));expect(screen.getByLabelText('Activity name')).toHaveValue('Do not lose');
});
it('imports once, edits returned UUID/revision and creates an activity without analysis or inferred references',async()=>{
 const {api,user}=setup(),imported={...gameFixture('Imported'),revision:7,reference_works:[{id:'kept-ref',name:'Kept',similarities:[]}]};
 api.analysis={steamImport:vi.fn(async()=>({ok:true,data:imported})),create:vi.fn()} as unknown as DesktopBridge['analysis'];api.games.update=vi.fn(async()=>({ok:true as const,data:{...imported,revision:8,name:'Edited'}}));
 await user.click(screen.getByRole('tab',{name:'Steam'}));await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/1');await user.keyboard('{Enter}');
 const name=await screen.findByRole('textbox',{name:'Name'});expect(name).toHaveValue('Imported');await user.click(screen.getByText('Activity name · Optional'));await user.type(screen.getByLabelText('Activity name'),'Source launch');await user.clear(name);await user.type(name,'Edited');await user.click(screen.getByRole('button',{name:'Continue to matching'}));await waitFor(()=>expect(api.match.createActivity).toHaveBeenCalledOnce());
 expect(api.games.update).toHaveBeenCalledWith({id:imported.id,data:{expected_revision:7,name:'Edited'}});expect(api.match.createActivity).toHaveBeenCalledWith(expect.objectContaining({data:{name:'Source launch',game_id:imported.id,reference_work_ids:[]}}));expect(api.analysis.steamImport).toHaveBeenCalledOnce();expect(api.analysis.create).not.toHaveBeenCalled();
});
it('opens Steam directly from an empty Library without losing the search draft',async()=>{
 const api={match:matchAPIMock(),games:{list:vi.fn(async()=>({ok:true,data:{items:[],total:0,offset:0,limit:20}}))}} as unknown as DesktopBridge;
 render(<NewActivity api={api} onCreated={vi.fn()} onCancel={vi.fn()}/>);const user=userEvent.setup();await user.type(screen.getByRole('searchbox',{name:'Search games'}),'Missing');await user.click(await screen.findByRole('button',{name:'Import from Steam'}));expect(screen.getByRole('textbox',{name:'Steam URL'})).toBeVisible();await user.click(screen.getByRole('tab',{name:'Library'}));expect(screen.getByRole('searchbox',{name:'Search games'})).toHaveValue('Missing');
});
function setup(){const game={...gameFixture('A game'),reference_works:[{id:'ref-one',name:'Reference',similarities:[]}]};const match=matchAPIMock();const api={match,games:{list:vi.fn(async()=>({ok:true,data:{items:[game],total:1,offset:0,limit:20}})),detail:vi.fn(async()=>({ok:true,data:game}))}} as unknown as DesktopBridge;const saved=vi.fn();render(<NewActivity api={api} onCreated={saved} onCancel={()=>{}}/>);return {api,saved,user:userEvent.setup()};}
it('creates a real activity from the selected Game with only checked references, without starting paid planning',async()=>{
  const {api,saved,user}=setup();
  await user.click(await screen.findByRole('button',{name:'Use game A game'}));
  await user.click(await screen.findByText('Activity name · Optional'));await user.type(screen.getByLabelText('Activity name'),'Autumn launch');
  await user.click(screen.getByRole('checkbox',{name:'Use reference Reference'}));
  await user.click(screen.getByRole('button',{name:'Continue to matching'}));
  await waitFor(()=>expect(saved).toHaveBeenCalledWith(activityFixture()));
  expect(api.match.createActivity).toHaveBeenCalledWith({data:{name:'Autumn launch',game_id:gameFixture().id,reference_work_ids:['ref-one']},idempotencyKey:expect.any(String)});
  expect(api.match.createPlan).not.toHaveBeenCalled();
});
it('keeps name and selection locked on a lost creation reply and retries the same saved intent',async()=>{
  const {api,user}=setup();vi.mocked(api.match.createActivity).mockResolvedValueOnce({ok:false,error:{code:'save_outcome_unknown',message:'Unconfirmed',retryable:false}});
  await user.click(await screen.findByRole('button',{name:'Use game A game'}));await user.click(await screen.findByText('Activity name · Optional'));await user.type(screen.getByLabelText('Activity name'),'Retained');
  await user.click(screen.getByRole('button',{name:'Continue to matching'}));
  expect(await screen.findByRole('button',{name:'Edit game'})).toBeDisabled();
  await user.click(screen.getByRole('button',{name:'Retry same request'}));
  expect(vi.mocked(api.match.createActivity).mock.calls[0]).toEqual(vi.mocked(api.match.createActivity).mock.calls[1]);
});
it('clears an old Game lookup failure after successfully retrying the selected Game',async()=>{
  const {api,user}=setup();vi.mocked(api.games.detail).mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Old game lookup failed',retryable:true}});
  await user.click(await screen.findByRole('button',{name:'Use game A game'}));
  await screen.findAllByText('Old game lookup failed');await user.click(screen.getByRole('button',{name:'Try again'}));
  expect(await screen.findByRole('textbox',{name:'Name'})).toHaveValue('A game');
  await user.click(screen.getByRole('button',{name:'Continue to matching'}));
  await waitFor(()=>expect(api.match.createActivity).toHaveBeenCalledOnce());expect(screen.queryByText('Old game lookup failed')).not.toBeInTheDocument();
});
