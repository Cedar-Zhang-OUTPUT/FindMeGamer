// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {LibraryView} from '../src/renderer/components/LibraryView';
import {MatchWorkspace} from '../src/renderer/components/match/MatchWorkspace';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {creatorAPIMock} from './creator-api-mock';
import {matchAPIMock} from './match-api-mock';
import {gameFixture} from './game-fixtures';
import type {DesktopBridge} from '../src/shared/bridge';
afterEach(cleanup);
const bridge=()=>({...settingsBridgeMock(),creators:creatorAPIMock(),match:matchAPIMock(),games:{list:vi.fn(async()=>ok({items:[gameFixture('Test game')],total:1,limit:24,offset:0})),detail:vi.fn(async()=>ok(gameFixture('Test game')))}} as unknown as DesktopBridge);
it('keeps Library tools in one header and yields heading priority to an opened record',async()=>{
 const api=bridge(),user=userEvent.setup();render(<LibraryView api={api} active/>);
 const header=screen.getByRole('group',{name:'Library navigation'});
 expect(within(header).getByRole('heading',{name:'Library'})).toBeVisible();expect(within(header).getByRole('tab',{name:'Creators'})).toBeVisible();expect(within(header).getByRole('button',{name:'Analysis tasks'})).toBeVisible();
 await user.type(screen.getByRole('searchbox',{name:'Search creators'}),'retained');
 await user.click(await screen.findByRole('button',{name:'Open Creator fixture'}));
 expect(screen.queryByRole('heading',{name:'Library'})).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Creator fixture'})).toBeVisible();
 await user.click(screen.getByRole('tab',{name:'Games'}));expect(screen.getByRole('heading',{name:'Library'})).toBeVisible();
 await user.click(screen.getByRole('tab',{name:'Creators'}));expect(screen.queryByRole('heading',{name:'Library'})).not.toBeInTheDocument();
 await user.click(screen.getByRole('button',{name:'Back to creators'}));expect(screen.getByRole('heading',{name:'Library'})).toBeVisible();expect(screen.getByRole('searchbox',{name:'Search creators'})).toHaveValue('retained');
 expect(api.analysis.create).not.toHaveBeenCalled();
});
it('places Match utilities with the current list, activity and creator context',async()=>{
 const api=bridge(),user=userEvent.setup();render(<MatchWorkspace api={api} active/>);
 expect(screen.getByRole('button',{name:'Analysis tasks'}).closest('.match-workspace-heading')).not.toBeNull();
 await user.click(await screen.findByRole('button',{name:'Open Indie launch'}));
 expect(screen.getByRole('button',{name:'Analysis tasks'}).closest('.match-breadcrumb')).not.toBeNull();
 await user.click(within(await screen.findByRole('article',{name:'Creator 1'})).getByRole('button',{name:'View creator'}));
 await screen.findByRole('button',{name:'Edit profile'});
 expect(screen.getByRole('button',{name:'Analysis tasks'}).closest('.creator-context-bar')).not.toBeNull();
 expect(screen.getAllByRole('button',{name:'Back to activity'})).toHaveLength(1);
 expect(api.match.createCreatorSearch).not.toHaveBeenCalled();
});
