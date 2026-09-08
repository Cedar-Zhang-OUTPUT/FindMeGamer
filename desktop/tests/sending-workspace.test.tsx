// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {SendBatchHistory} from '../src/renderer/components/match/SendingWorkspace';
import {settingsBridgeMock,ok} from './settings-fixtures';
import {sendBatchFixture} from './sending-fixtures';
afterEach(cleanup);
it('loads history only on demand, preserves page scope, and never sends from history',async()=>{
  const api=settingsBridgeMock().sending,batch=sendBatchFixture(),onOpen=vi.fn();vi.mocked(api.batches).mockResolvedValue(ok({items:[batch],total:51,offset:0,limit:50}));
  const props={api,activityId:batch.activity_id,active:false,epoch:0,disabled:false,onOpen};const view=render(<SendBatchHistory {...props}/>);
  await userEvent.click(screen.getByRole('button',{name:'Sending history'}));expect(api.batches).not.toHaveBeenCalled();view.rerender(<SendBatchHistory {...props} active/>);
  await userEvent.click(await screen.findByRole('button',{name:'View deliveries'}));expect(onOpen).toHaveBeenCalledWith(batch.id);expect(screen.getByRole('button',{name:'Sending history'})).toHaveAttribute('aria-expanded','false');expect(api.send).not.toHaveBeenCalled();
});
it('does not expose a foreign batch and offers a local read retry',async()=>{
  const api=settingsBridgeMock().sending,batch=sendBatchFixture();vi.mocked(api.batches).mockResolvedValue(ok({items:[{...batch,activity_id:'foreign'}],total:1,offset:0,limit:50}));
  render(<SendBatchHistory api={api} activityId={batch.activity_id} active epoch={0} disabled={false} onOpen={vi.fn()}/>);
  await userEvent.click(screen.getByRole('button',{name:'Sending history'}));expect(await screen.findByRole('alert')).toHaveTextContent('Could not load sending history');expect(screen.queryByRole('button',{name:'View deliveries'})).not.toBeInTheDocument();
  vi.mocked(api.batches).mockResolvedValue(ok({items:[],total:0,offset:0,limit:50}));await userEvent.click(screen.getByRole('button',{name:'Try again'}));await waitFor(()=>expect(screen.getByText('No sent batches yet.')).toBeVisible());
});
