// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import {NewActivity} from '../src/renderer/components/match/NewActivity';
import {GameStart} from '../src/renderer/components/match/GameStart';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {gameFixture} from './game-fixtures';
import type {DesktopBridge} from '../src/shared/bridge';
afterEach(cleanup);
function setup(){const game=gameFixture('LIMINAL: Within'),api={...settingsBridgeMock(),games:{list:vi.fn(async()=>ok({items:[game],total:1,limit:24,offset:0})),detail:vi.fn(async()=>ok(game))}} as unknown as DesktopBridge;const onCreated=vi.fn();render(<NewActivity api={api} onCreated={onCreated} onCancel={vi.fn()}/>);return {api,game,onCreated,user:userEvent.setup()};}
it('P1 focuses exclusively on choosing a game, with a card, Library management and independent Steam entry',async()=>{
 setup();expect(screen.getByRole('heading',{name:'Choose a game'})).toBeVisible();
 expect(screen.queryByLabelText('Activity name')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Create activity'})).not.toBeInTheDocument();expect(screen.queryByText('Linked game')).not.toBeInTheDocument();
 expect(await screen.findByRole('article',{name:'LIMINAL: Within'})).toBeVisible();expect(screen.getByRole('button',{name:'Use game LIMINAL: Within'})).toBeVisible();expect(screen.getByRole('button',{name:'Manage Library'})).toBeVisible();expect(screen.getByRole('button',{name:'Use Steam link'})).toBeVisible();
});
it('P1 use game enters editable P2 and continues directly to the activity conditions without a second creation form',async()=>{
 const {api,game,onCreated,user}=setup();await user.click(await screen.findByRole('button',{name:'Use game LIMINAL: Within'}));expect(await screen.findByRole('textbox',{name:'Name'})).toHaveValue(game.name);expect(api.match.createActivity).not.toHaveBeenCalled();
 await user.click(screen.getByRole('button',{name:'Continue to matching'}));await waitFor(()=>expect(onCreated).toHaveBeenCalledOnce());expect(api.match.createActivity).toHaveBeenCalledWith(expect.objectContaining({data:{name:game.name,game_id:game.id,reference_work_ids:[]}}));expect(api.match.createPlan).not.toHaveBeenCalled();
});
it('keeps game facts prefilled and sends only the user-written activity brief on explicit continuation',async()=>{
 const {api,game,user}=setup();api.games.update=vi.fn();await user.click(await screen.findByRole('button',{name:'Use game LIMINAL: Within'}));await screen.findByRole('textbox',{name:'Name'});
 expect(screen.getByRole('textbox',{name:'Description'})).toHaveValue(game.description??'');await user.click(screen.getByText('Campaign brief · Optional'));
 const brief=screen.getByRole('textbox',{name:'Campaign brief'});expect(brief).toHaveValue('');await user.type(brief,'Highlight co-op; find cozy channels');await user.click(screen.getByRole('button',{name:'Continue to matching'}));
 await waitFor(()=>expect(api.match.createActivity).toHaveBeenCalledWith(expect.objectContaining({data:expect.objectContaining({game_id:game.id,campaign_brief:'Highlight co-op; find cozy channels'})})));expect(api.games.update).not.toHaveBeenCalled();
});
it('the game picker retains its search after reviewing and returning from P2',async()=>{
 const {user}=setup();await user.type(screen.getByRole('searchbox',{name:'Search games'}),'LIMINAL');await user.click(await screen.findByRole('button',{name:'Use game LIMINAL: Within'}));await user.click(await screen.findByRole('button',{name:'Back to games'}));expect(screen.getByRole('searchbox',{name:'Search games'})).toHaveValue('LIMINAL');
});
it('saving game edits while returning to P1 never creates an activity',async()=>{
 const {api,game,user}=setup();api.games.update=vi.fn(async()=>ok({...game,name:'Revised game',revision:game.revision+1}));
 await user.click(await screen.findByRole('button',{name:'Use game LIMINAL: Within'}));await user.type(await screen.findByRole('textbox',{name:'Name'}),' revised');
 await user.click(screen.getByRole('button',{name:'Back to games'}));await user.click(await screen.findByRole('button',{name:'Save and leave'}));
 expect(await screen.findByRole('heading',{name:'Choose a game'})).toBeVisible();expect(api.games.update).toHaveBeenCalledOnce();expect(api.match.createActivity).not.toHaveBeenCalled();
});
it('canceling a reference modal retains no empty reference or business write',async()=>{
 const {api,user}=setup();await user.click(await screen.findByRole('button',{name:'Use game LIMINAL: Within'}));await user.click(await screen.findByRole('button',{name:'Add reference'}));
 const dialog=screen.getByRole('dialog',{name:'Add reference'});await user.type(within(dialog).getByLabelText('Reference name'),'Not saved');await user.keyboard('{Escape}');
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Reference works 0'})).toBeVisible();expect(screen.getByRole('button',{name:'Add reference'})).toHaveFocus();expect(api.match.createActivity).not.toHaveBeenCalled();
});
it('maps a newly selected reference one-to-one even when an unselected saved reference has the same name and URL',async()=>{
 const {api,game,user}=setup();const original={id:'reference-a',name:'Shared',url:null,reason:'Original reason',similarities:[]};
 vi.mocked(api.games.detail).mockResolvedValue(ok({...game,reference_works:[original]}));api.games.update=vi.fn(async()=>ok({...game,revision:2,reference_works:[original,{...original,id:'reference-b',reason:'New reason'}]}));
 await user.click(await screen.findByRole('button',{name:'Use game LIMINAL: Within'}));await user.click(await screen.findByRole('button',{name:'Add reference'}));const dialog=screen.getByRole('dialog',{name:'Add reference'});
 await user.type(within(dialog).getByLabelText('Reference name'),'New');await user.type(within(dialog).getByLabelText('Reason · Optional'),'New reason');await user.click(within(dialog).getByRole('button',{name:'Add'}));
 await user.click(screen.getByRole('button',{name:'Edit reference New'}));const name=screen.getByRole('textbox',{name:'Reference name'});await user.clear(name);await user.type(name,'Shared');await user.click(screen.getAllByRole('checkbox',{name:'Use reference Shared'})[1]);
 await user.click(screen.getByRole('button',{name:'Continue to matching'}));await waitFor(()=>expect(api.match.createActivity).toHaveBeenCalledWith(expect.objectContaining({data:expect.objectContaining({reference_work_ids:['reference-b']})})));
});
it('refreshes game cards on Library return without resetting the search draft',async()=>{
 const game=gameFixture('Before'),api={games:{list:vi.fn(async()=>ok({items:[game],total:1,offset:0,limit:24}))}} as unknown as DesktopBridge;
 const props={api,disabled:false,onUse:vi.fn(),onSteam:vi.fn(),onManage:vi.fn()};const view=render(<GameStart {...props} refreshToken={0}/>);const user=userEvent.setup();await screen.findByRole('article',{name:'Before'});await user.type(screen.getByRole('searchbox',{name:'Search games'}),'retained');
 vi.mocked(api.games.list).mockResolvedValue(ok({items:[{...game,name:'After'}],total:1,offset:0,limit:24}));view.rerender(<GameStart {...props} refreshToken={1}/>);
 expect(await screen.findByRole('article',{name:'After'})).toBeVisible();expect(screen.getByRole('searchbox',{name:'Search games'})).toHaveValue('retained');
});
