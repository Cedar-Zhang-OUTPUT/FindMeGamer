// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import {LibraryView} from '../src/renderer/components/LibraryView';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {gameFixture} from './game-fixtures';
import {creatorFormFixture} from './creator-form-fixtures';
afterEach(cleanup);
function bridge(){const mock=settingsBridgeMock(),game=gameFixture('Puzzle');return {...mock,games:{list:vi.fn(async()=>ok({items:[game],total:1,offset:0,limit:24})),detail:vi.fn(async()=>ok(game)),create:vi.fn(),update:vi.fn()},library:{list:vi.fn(),detail:vi.fn()},openExternal:vi.fn(),connection:{status:vi.fn(),save:vi.fn(),clear:vi.fn(),test:vi.fn()}} as DesktopBridge;}
it('source import opens returned game and only explicit confirmation dispatches analysis',async()=>{
 const api=bridge(),game={...gameFixture('Imported puzzle'),revision:1,source_identity:{steam_app_id:'900000001',canonical_url:'https://store.steampowered.com/app/900000001'}};vi.mocked(api.analysis.steamImport).mockResolvedValue(ok(game));
 render(<LibraryView api={api} active/>);const user=userEvent.setup();await user.click(screen.getByRole('tab',{name:'Games'}));await user.click(screen.getByRole('button',{name:'Import from Steam'}));await user.type(screen.getByRole('textbox',{name:'Steam URL'}),game.source_identity.canonical_url);await user.click(screen.getByRole('button',{name:'Import source'}));await screen.findByRole('heading',{name:'Imported puzzle'});
 expect(api.analysis.create).not.toHaveBeenCalled();await user.click(screen.getByRole('button',{name:'Analyze game'}));expect(screen.getByRole('region',{name:'Confirm analysis'})).toHaveTextContent(game.source_identity.canonical_url);expect(api.analysis.create).not.toHaveBeenCalled();await user.click(screen.getByRole('button',{name:'Analyze now'}));expect(api.analysis.create).toHaveBeenCalledWith(expect.objectContaining({target_type:'game',url:game.source_identity.canonical_url,mode:'reanalyze'}));
});
it('URL-only YouTube offers explicit bind, bound numeric X offers analyze, unsupported platform does not',async()=>{
 const api=bridge(),yt=creatorFormFixture({name:'Unbound video',profile_url:'https://www.youtube.com/@channel',source_identity:{platform:'youtube',account_id:null,canonical_url:null,revision:1}});vi.mocked(api.creators.list).mockResolvedValue(ok({items:[yt],total:1,offset:0,limit:50}));vi.mocked(api.creators.detail).mockResolvedValue(ok(yt));vi.mocked(api.analysis.bindYouTube).mockResolvedValue(ok({...yt,analysis_available:true,source_identity:{platform:'youtube',account_id:'UCchannel',canonical_url:'https://www.youtube.com/channel/UCchannel',revision:2}}));
 render(<LibraryView api={api} active/>);const user=userEvent.setup();await user.click(await screen.findByRole('button',{name:'Open Unbound video'}));expect(screen.queryByRole('button',{name:'Analyze creator'})).not.toBeInTheDocument();await user.click(screen.getByRole('button',{name:'Bind YouTube channel'}));await user.click(screen.getByRole('button',{name:'Bind channel'}));await screen.findByRole('button',{name:'Analyze creator'});expect(api.analysis.create).not.toHaveBeenCalled();expect(api.creators.create).not.toHaveBeenCalled();
});
it('opening a completed profile does not overwrite an unconfirmed source request',async()=>{
 const api=bridge(),register=vi.fn();render(<LibraryView api={api} active onNavigationGuardChange={register}/>);const user=userEvent.setup();await user.click(screen.getByRole('tab',{name:'Games'}));await user.click(screen.getByRole('button',{name:'Import from Steam'}));await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/1');await user.click(screen.getByRole('tab',{name:'Creators'}));expect(screen.getByRole('alertdialog',{name:'Leave source import'})).toBeVisible();await user.click(screen.getByRole('button',{name:'Keep importing'}));expect(screen.getByRole('textbox',{name:'Steam URL'})).toHaveValue('https://store.steampowered.com/app/1');expect(register).toHaveBeenCalled();
});
