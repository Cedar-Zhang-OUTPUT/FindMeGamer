// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge,Result} from '../src/shared/bridge';
import {GameLibrary} from '../src/renderer/components/GameLibrary';
import {gameFixture} from './game-fixtures';
const ok=<T,>(data:T):Result<T>=>({ok:true,data});
afterEach(cleanup);
it('offers direct row edit and Match actions without a read-only detail stop',async()=>{
 const game=gameFixture(),games={list:vi.fn(async()=>ok({items:[game],total:1,limit:24,offset:0})),detail:vi.fn(async()=>ok(game)),create:vi.fn(),update:vi.fn()};
 const api={games,openExternal:vi.fn()} as unknown as DesktopBridge,onUseForMatch=vi.fn(),user=userEvent.setup();
 render(<GameLibrary api={api} active onUseForMatch={onUseForMatch}/>);expect(await screen.findByRole('table',{name:'Games'})).toBeVisible();
 await user.click(screen.getByRole('button',{name:'Use A game for Match'}));await waitFor(()=>expect(onUseForMatch).toHaveBeenCalledExactlyOnceWith(game));
  await user.click(screen.getByRole('button',{name:'Edit A game'}));expect(await screen.findByRole('button',{name:'Save changes'})).toBeVisible();expect(games.detail).toHaveBeenCalledTimes(2);
});
function start(){
  const games={list:vi.fn<DesktopBridge['games']['list']>(async()=>ok({items:[gameFixture()],total:49,limit:24,offset:0})),detail:vi.fn(async()=>ok(gameFixture())),create:vi.fn(),update:vi.fn()};
  const api={games,openExternal:vi.fn()} as unknown as DesktopBridge;
  render(<GameLibrary api={api} active/>);return {games,user:userEvent.setup()};
}
it('uses PRD defaults and sends website/order choices to the server without losing unsubmitted search',async()=>{
  const {games,user}=start();await screen.findByRole('button',{name:'Open A game'});
  expect(games.list).toHaveBeenCalledWith(expect.objectContaining({sort:'recent_updated',websiteStatus:'all',offset:0}));
  await user.type(screen.getByRole('searchbox',{name:'Search games'}),'Pending query');
  await user.selectOptions(screen.getByRole('combobox',{name:'Website'}),'missing');
  await user.selectOptions(screen.getByRole('combobox',{name:'Sort games'}),'name');
  expect(games.list).toHaveBeenLastCalledWith(expect.objectContaining({query:'',sort:'name',websiteStatus:'missing',offset:0}));
  expect(screen.getByRole('searchbox',{name:'Search games'})).toHaveValue('Pending query');
});
it('preserves website and ordering on next page, detail return and edited-game cancel',async()=>{
  const {games,user}=start();await screen.findByRole('button',{name:'Open A game'});
  await user.selectOptions(screen.getByRole('combobox',{name:'Website'}),'available');
  await user.selectOptions(screen.getByRole('combobox',{name:'Sort games'}),'recent_added');
  games.list.mockResolvedValueOnce(ok({items:[gameFixture()],total:49,limit:24,offset:24}));
  await user.click(screen.getByRole('button',{name:'Next page'}));
  expect(games.list).toHaveBeenLastCalledWith(expect.objectContaining({websiteStatus:'available',sort:'recent_added',offset:24}));
  await user.click(screen.getByRole('button',{name:'Open A game'}));await user.click(await screen.findByRole('button',{name:'Back to games'}));
  expect(screen.getByRole('combobox',{name:'Website'})).toHaveValue('available');expect(screen.getByText('25–25 of 49')).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Open A game'}));await user.click(await screen.findByRole('button',{name:'Edit game'}));
  await user.click(screen.getByRole('button',{name:'Cancel'}));
  await waitFor(()=>expect(games.list).toHaveBeenLastCalledWith(expect.objectContaining({websiteStatus:'available',sort:'recent_added',offset:24})));
});
it('retains a failed-filter previous page honestly and retries the exact requested filter',async()=>{
  const {games,user}=start();await screen.findByRole('button',{name:'Open A game'});
  games.list.mockResolvedValueOnce({ok:false,error:{code:'network_error',message:'Offline',retryable:true}});
  await user.selectOptions(screen.getByRole('combobox',{name:'Website'}),'missing');
  expect(await screen.findByText('Previous results')).toBeVisible();expect(screen.getByRole('button',{name:'Open A game'})).toBeVisible();
  expect(screen.getByRole('button',{name:'Next page'})).toBeDisabled();
  await user.click(screen.getByRole('button',{name:'Try again'}));
  expect(games.list).toHaveBeenLastCalledWith(expect.objectContaining({websiteStatus:'missing',sort:'recent_updated',offset:0}));
  await waitFor(()=>expect(screen.queryByText('Previous results')).not.toBeInTheDocument());
});
