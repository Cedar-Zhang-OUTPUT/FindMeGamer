// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import {NewActivity} from '../src/renderer/components/match/NewActivity';
import {matchAPIMock,activityFixture} from './match-api-mock';
import {gameFixture} from './game-fixtures';
afterEach(cleanup);
function setup(){const game={...gameFixture('A game'),reference_works:[{id:'ref-one',name:'Reference',similarities:[]}]};const match=matchAPIMock();const api={match,games:{list:vi.fn(async()=>({ok:true,data:{items:[game],total:1,offset:0,limit:20}})),detail:vi.fn(async()=>({ok:true,data:game}))}} as unknown as DesktopBridge;const saved=vi.fn();render(<NewActivity api={api} onCreated={saved} onCancel={()=>{}}/>);return {api,saved,user:userEvent.setup()};}
it('creates a real activity from the selected Game with only checked references, without starting paid planning',async()=>{
  const {api,saved,user}=setup();
  await user.type(screen.getByLabelText('Activity name'),'Autumn launch');
  await user.click(await screen.findByRole('button',{name:'Select game A game'}));
  await user.click(await screen.findByText('Reference works'));
  await user.click(screen.getByRole('checkbox',{name:'Reference'}));
  await user.click(screen.getByRole('button',{name:'Create activity'}));
  await waitFor(()=>expect(saved).toHaveBeenCalledWith(activityFixture()));
  expect(api.match.createActivity).toHaveBeenCalledWith({data:{name:'Autumn launch',game_id:gameFixture().id,reference_work_ids:['ref-one']},idempotencyKey:expect.any(String)});
  expect(api.match.createPlan).not.toHaveBeenCalled();
});
it('keeps name and selection locked on a lost creation reply and retries the same saved intent',async()=>{
  const {api,user}=setup();vi.mocked(api.match.createActivity).mockResolvedValueOnce({ok:false,error:{code:'save_outcome_unknown',message:'Unconfirmed',retryable:false}});
  await user.type(screen.getByLabelText('Activity name'),'Retained');await user.click(await screen.findByRole('button',{name:'Select game A game'}));
  await user.click(await screen.findByRole('button',{name:'Create activity'}));
  expect(await screen.findByLabelText('Activity name')).toBeDisabled();
  await user.click(screen.getByRole('button',{name:'Retry same request'}));
  expect(vi.mocked(api.match.createActivity).mock.calls[0]).toEqual(vi.mocked(api.match.createActivity).mock.calls[1]);
});
it('clears an old Game lookup failure after a new Game is successfully saved',async()=>{
  const {api,user}=setup();vi.mocked(api.games.detail).mockResolvedValue({ok:false,error:{code:'network_error',message:'Old game lookup failed',retryable:true}});
  await user.type(screen.getByLabelText('Activity name'),'Recovered activity');await user.click(await screen.findByRole('button',{name:'Select game A game'}));
  await screen.findAllByText('Old game lookup failed');await user.click(screen.getByRole('button',{name:'New game'}));
  const savedGame=gameFixture('Recovered game');api.games.create=vi.fn(async()=>{vi.mocked(api.games.detail).mockResolvedValue({ok:true,data:savedGame});return {ok:true as const,data:savedGame};});
  await user.type(screen.getByRole('textbox',{name:'Name'}),'Recovered game');await user.click(screen.getByRole('button',{name:'Create game'}));
  await user.click(await screen.findByRole('button',{name:'Create activity'}));
  await waitFor(()=>expect(api.match.createActivity).toHaveBeenCalledOnce());expect(screen.queryByText('Old game lookup failed')).not.toBeInTheDocument();
});
