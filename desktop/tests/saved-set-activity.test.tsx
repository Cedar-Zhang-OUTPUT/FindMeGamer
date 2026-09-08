// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,render,screen,waitFor,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge,Result} from '../src/shared/bridge';
import type {SavedSetView,SavedSetsAPI} from '../src/shared/savedSets';
import {MatchActivity} from '../src/renderer/components/match/MatchActivity';
import {activityFixture,queryFixture,candidateFixture,matchAPIMock} from './match-api-mock';
import {settingsBridgeMock} from './settings-fixtures';
import {SET_ID} from './saved-set-fixtures';
const ok=<T,>(data:T):Result<T>=>({ok:true,data});
afterEach(cleanup);
function setup(){
  const match=matchAPIMock(),onBack=vi.fn(),onOpenCreator=vi.fn();
  const receipt:SavedSetView={id:SET_ID,activity_id:activityFixture().id,query_id:queryFixture().id,name:'Cozy creators',candidate_ids:[candidateFixture(1).id],count:1,created_at:'2026-09-08T01:00:00Z'};
  const savedSets:SavedSetsAPI={list:vi.fn(async()=>ok({items:[],total:0,offset:0,limit:50})),detail:vi.fn(async()=>ok(receipt)),results:vi.fn(async()=>ok({items:[candidateFixture(1)],total:1,offset:0,limit:100})),create:vi.fn(async()=>ok(receipt))};
  const api={...settingsBridgeMock(),match,savedSets} as unknown as DesktopBridge;
  render(<MatchActivity api={api} activityId={activityFixture().id} active onBack={onBack} onOpenCreator={onOpenCreator}/>);
  return {api,match,savedSets,receipt,onBack,onOpenCreator,user:userEvent.setup()};
}
async function mark(user:ReturnType<typeof userEvent.setup>){
  await user.click(await screen.findByRole('button',{name:'Save list'}));
  expect(screen.getByRole('button',{name:'Save 0 creators'})).toBeDisabled();
  await user.click(screen.getByRole('checkbox',{name:'Include Creator 1 in saved list'}));
  await user.type(screen.getByRole('textbox',{name:'List name'}),'Cozy creators');
}
it('saves only explicitly marked membership and reopens the immutable list without outreach or new discovery',async()=>{
  const {user,savedSets,match,receipt}=setup();await mark(user);
  expect(savedSets.create).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Save 1 creator'}));
  await waitFor(()=>expect(savedSets.create).toHaveBeenCalledWith({queryId:receipt.query_id,data:{request_id:expect.any(String),name:'Cozy creators',candidate_ids:receipt.candidate_ids},idempotencyKey:expect.any(String)}));
  expect(await screen.findByRole('heading',{name:'Cozy creators'})).toBeVisible();
  expect(screen.getByText('1 saved')).toBeVisible();
  expect(match.evaluate).not.toHaveBeenCalled();expect(match.createPlan).not.toHaveBeenCalled();expect(match.continueDiscovery).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Original search'}));
  expect(await screen.findByRole('button',{name:'Save list'})).toBeVisible();
  expect(savedSets.create).toHaveBeenCalledOnce();
});
it('preserves marks and name through creator inspection without submitting or discarding',async()=>{
  const {user,onOpenCreator,savedSets}=setup();await mark(user);
  await user.click(within(screen.getByRole('article',{name:'Creator 1'})).getByRole('button',{name:'View creator'}));
  expect(onOpenCreator).toHaveBeenCalledOnce();expect(screen.getByRole('textbox',{name:'List name'})).toHaveValue('Cozy creators');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(savedSets.create).not.toHaveBeenCalled();
});
it('blocks leaving an uncertain saved list and retries the frozen request instead of creating another set',async()=>{
  const {user,savedSets,onBack,receipt}=setup();
  vi.mocked(savedSets.create).mockResolvedValueOnce({ok:false,error:{code:'save_outcome_unknown',message:'Not confirmed',retryable:false}});
  await mark(user);await user.click(screen.getByRole('button',{name:'Save 1 creator'}));
  await user.click(await screen.findByRole('button',{name:'Activities'}));
  const dialog=screen.getByRole('dialog');expect(within(dialog).getByRole('button',{name:'Discard changes'})).toBeDisabled();
  await user.click(within(dialog).getByRole('button',{name:'Keep working'}));expect(onBack).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Retry same save'}));
  await screen.findByRole('heading',{name:receipt.name});
  expect(vi.mocked(savedSets.create).mock.calls[0]).toEqual(vi.mocked(savedSets.create).mock.calls[1]);
});
it('does not let a pending filter add stale candidates to the saved membership',async()=>{
  const {user,match,savedSets}=setup();await mark(user);
  let finish!:(value:Awaited<ReturnType<typeof match.candidates>>)=>void;
  vi.mocked(match.candidates).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve));
  await user.selectOptions(screen.getByLabelText('Evidence'),'none');
  expect(screen.getByRole('checkbox',{name:'Include Creator 1 in saved list'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Save 1 creator'})).toBeDisabled();
  await act(async()=>finish(ok({items:[],total:0,offset:0,limit:100})));
  expect(screen.getByRole('textbox',{name:'List name'})).toHaveValue('Cozy creators');
  expect(screen.getByRole('button',{name:'Save 1 creator'})).toBeEnabled();expect(savedSets.create).not.toHaveBeenCalled();
});
