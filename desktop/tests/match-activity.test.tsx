// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import {MatchActivity} from '../src/renderer/components/match/MatchActivity';
import {activityFixture,matchAPIMock,queryFixture,candidateFixture} from './match-api-mock';
import {settingsBridgeMock} from './settings-fixtures';
afterEach(cleanup);
function setup(match=matchAPIMock()){const api={...settingsBridgeMock(),match} as unknown as DesktopBridge;render(<MatchActivity api={api} activityId={activityFixture().id} active onBack={()=>{}} onOpenCreator={()=>{}}/>);return {api,user:userEvent.setup()};}
it('requires an explicit evaluation and freezes only loaded eligible candidates',async()=>{
  const match=matchAPIMock();vi.mocked(match.candidates).mockResolvedValue({ok:true,data:{items:[candidateFixture(1),{...candidateFixture(2),identity_changed:true}],total:5,limit:100,offset:0}});
  const {user}=setup(match);const evaluate=await screen.findByRole('button',{name:'Evaluate 1 loaded'});
  expect(match.evaluate).not.toHaveBeenCalled();await user.click(evaluate);
  await waitFor(()=>expect(match.evaluate).toHaveBeenCalledWith({queryId:queryFixture().id,data:{candidate_ids:[candidateFixture(1).id]},idempotencyKey:expect.any(String)}));
  expect(await screen.findByRole('tab',{name:/Match briefs/})).toHaveAttribute('aria-selected','true');
  expect(match.createPlan).not.toHaveBeenCalled();
});
it('requires acknowledgement before resuming an unknown provider outcome',async()=>{
  const match=matchAPIMock();vi.mocked(match.query).mockResolvedValue({ok:true,data:{...queryFixture('outcome_unknown'),requires_acknowledgement:true}});
  const {user}=setup(match);const resume=await screen.findByRole('button',{name:'Continue discovery'});
  expect(resume).toBeDisabled();await user.click(screen.getByRole('checkbox',{name:'I accept possible repeated provider charges'}));await user.click(resume);
  await waitFor(()=>expect(match.continueDiscovery).toHaveBeenCalledWith({queryId:queryFixture().id,data:{acknowledge_unknown:true},idempotencyKey:expect.any(String)}));
});
it('offers Stop while running and retains the existing candidate list',async()=>{
  const match=matchAPIMock();vi.mocked(match.query).mockResolvedValue({ok:true,data:queryFixture('running')});const {user}=setup(match);
  await user.click(await screen.findByRole('button',{name:'Stop discovery'}));
  expect(match.stop).toHaveBeenCalledWith({queryId:queryFixture().id,idempotencyKey:expect.any(String)});
  expect(await screen.findByRole('heading',{name:'Creator 1'})).toBeVisible();
  expect(match.continueDiscovery).not.toHaveBeenCalled();
});
it('switches candidate and brief panels with the keyboard without launching evaluation',async()=>{
  const {api,user}=setup();const tab=await screen.findByRole('tab',{name:'Candidates'});tab.focus();await user.keyboard('{ArrowRight}');
  expect(screen.getByRole('tab',{name:'Match briefs'})).toHaveAttribute('aria-selected','true');expect(screen.getByRole('tab',{name:'Match briefs'})).toHaveFocus();
  expect(screen.getByText('No evaluation yet')).toBeVisible();expect(api.match.evaluate).not.toHaveBeenCalled();
});
