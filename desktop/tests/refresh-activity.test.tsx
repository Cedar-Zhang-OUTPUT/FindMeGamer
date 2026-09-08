// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { RefreshActivity } from '../src/renderer/components/settings/RefreshActivity';
import type { DesktopBridge, Result } from '../src/shared/bridge';
import type { ListPage, ProfileSummary } from '../src/shared/library';

afterEach(cleanup);
const past = '2026-09-01T00:00:00Z';
const future = '2026-09-10T00:00:00Z';
const row = (id: string, next: string | null | undefined = future): ProfileSummary => ({id, kind:'games',name:id,sourceId:id,canonicalUrl:'',summary:null,artworkUrl:null,favorite:false,updatedAt:past,nextAnalysisAt:next,subscribers:null,tags:[]});
const ok = (items: ProfileSummary[] = [], nextCursor: string | null = null): Result<ListPage> => ({ok:true,data:{items,nextCursor}});
const fail: Result<ListPage> = {ok:false,error:{code:'offline',message:'secret internal error',retryable:true}};
function setup(list = vi.fn<DesktopBridge['library']['list']>().mockResolvedValue(ok())) {
  const api = {library:{list,detail:vi.fn()}};
  const view = render(<RefreshActivity api={api} connected/>);
  return {api,list,view,user:userEvent.setup()};
}

it('loads bounded independent categories only when expanded, exposing loaded dates and null schedules', async () => {
  const list = vi.fn<DesktopBridge['library']['list']>().mockImplementation(async ({kind}) => kind==='games'?ok([row('one'),row('two',null)]):ok([row('creator',undefined)]));
  const {user} = setup(list);
  expect(list).not.toHaveBeenCalled();
  await user.click(screen.getByText('Refresh activity'));
  await waitFor(()=>expect(list).toHaveBeenCalledTimes(2));
  expect(list).toHaveBeenCalledWith({kind:'games',limit:100});
  expect(list).toHaveBeenCalledWith({kind:'creators',limit:100});
  const games = within(screen.getByRole('region',{name:'Steam-linked games'}));
  expect(await games.findByText(future)).toBeVisible();
  expect(games.getByText(past)).toBeVisible();
  expect(games.getByText('Without a scheduled refresh').nextElementSibling).toHaveTextContent('1');
  expect(games.getByText('2 records')).toBeVisible();
});

it('labels partial coverage, preserves rows on page failure, and retries only the requested page', async () => {
  const list = vi.fn<DesktopBridge['library']['list']>().mockImplementation(async ({kind,cursor}) => kind==='creators'?ok():cursor?fail:ok([row('one')],'page2'));
  const {user} = setup(list);
  await user.click(screen.getByText('Refresh activity'));
  expect(await screen.findByText('First 1 records')).toBeVisible();
  expect(within(screen.getByRole('region',{name:'Steam-linked games'})).getByText('Next scheduled among loaded records')).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Load more games'}));
  expect(await screen.findByText('Could not load games activity.')).toBeVisible();
  expect(screen.getByText(future)).toBeVisible();
  expect(screen.queryByText('secret internal error')).not.toBeInTheDocument();
  list.mockImplementation(async ()=>ok([row('two',null)]));
  await user.click(screen.getByRole('button',{name:'Retry games'}));
  expect(list).toHaveBeenLastCalledWith({kind:'games',limit:100,cursor:'page2'});
  expect(await screen.findByText('2 records')).toBeVisible();
  expect(list).toHaveBeenCalledTimes(4);
});

it('keeps successful categories visible while the other is delayed and ignores results after disconnect', async () => {
  let finish!: (value: Result<ListPage>)=>void;
  const list = vi.fn<DesktopBridge['library']['list']>().mockImplementation(({kind})=>kind==='games'?Promise.resolve(ok([row('one')])):new Promise(resolve=>{finish=resolve;}));
  const {api,user,view} = setup(list);
  await user.click(screen.getByText('Refresh activity'));
  expect(await screen.findByText(future)).toBeVisible();
  expect(screen.getByText('Loading creators activity…')).toBeVisible();
  view.rerender(<RefreshActivity api={api} connected={false}/>);
  await act(async()=>finish(ok([row('stale')])));
  expect(screen.queryByText(future)).not.toBeInTheDocument();
  expect(screen.getByText('Connect a workspace to view refresh activity.')).toBeVisible();
  list.mockResolvedValue(ok());
  view.rerender(<RefreshActivity api={api} connected/>);
  await user.click(screen.getByText('Refresh activity'));
  await waitFor(()=>expect(list).toHaveBeenCalledTimes(4));
  expect(screen.queryByText(future)).not.toBeInTheDocument();
});

it('reports unavailable optional schedule metadata without counting it as unscheduled', async () => {
  const unknown = row('unknown'); delete unknown.nextAnalysisAt;
  const {user}=setup(vi.fn<DesktopBridge['library']['list']>().mockResolvedValue(ok([unknown,row('unscheduled',null)])));
  await user.click(screen.getByText('Refresh activity'));
  const games=within(await screen.findByRole('region',{name:'Steam-linked games'}));
  expect(await games.findByText('Schedule unavailable')).toBeVisible();
  expect(games.getByText('Unavailable')).toBeVisible();
  expect(games.getByText('Without a scheduled refresh').nextElementSibling).toHaveTextContent('1');
});
