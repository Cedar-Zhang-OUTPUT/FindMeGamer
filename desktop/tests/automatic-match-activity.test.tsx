// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {MatchActivity} from '../src/renderer/components/match/MatchActivity';
import {matchAPIMock,activityFixture} from './match-api-mock';
import {settingsBridgeMock} from './settings-fixtures';
import type {DesktopBridge} from '../src/shared/bridge';
afterEach(cleanup);
it('Find creators submits the automatic route once, never Evaluate loaded or the legacy plan action',async()=>{
 const api={...settingsBridgeMock(),match:matchAPIMock()},user=userEvent.setup();vi.mocked(api.match.activity).mockResolvedValue({ok:true,data:{...activityFixture(),queries:[]}});vi.mocked(api.match.plans).mockResolvedValue({ok:true,data:{items:[],total:0,limit:50,offset:0}});
 render(<MatchActivity api={api as unknown as DesktopBridge} activityId={activityFixture().id} active onBack={()=>{}} onOpenCreator={()=>{}}/>);
 await user.click(await screen.findByRole('button',{name:'Find creators'}));await waitFor(()=>expect(api.match.createCreatorSearch).toHaveBeenCalledOnce());
 expect(api.match.createCreatorSearch).toHaveBeenCalledWith(expect.objectContaining({data:expect.objectContaining({mode:'discover'}),idempotencyKey:expect.any(String)}));expect(api.match.createPlan).not.toHaveBeenCalled();expect(api.match.evaluate).not.toHaveBeenCalled();
 expect(screen.getByText('History & saved lists').closest('details')).not.toHaveAttribute('open');expect(screen.queryByRole('button',{name:/Evaluate.*loaded/})).not.toBeInTheDocument();
});
