// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {ConnectionSettings} from '../src/renderer/components/ConnectionSettings';
afterEach(cleanup);
const props=()=>({phase:'disconnected' as const,error:null,route:null,onConnect:vi.fn(async()=>{}),onTest:vi.fn(),onDisconnect:vi.fn(),onLibrary:vi.fn(),onDraftStateChange:vi.fn()});
it('prefills the cloud origin without a key, dirty state or automatic connection',()=>{
 const p=props();render(<ConnectionSettings {...p} status={{serviceUrl:'',hasKey:false,storageAvailable:true}}/>);
 expect(screen.getByLabelText('Service URL')).toHaveValue('https://44.233.174.193');
 expect(screen.getByLabelText('Workspace key')).toHaveValue('');expect(screen.getByRole('button',{name:'Connect'})).toBeDisabled();
 expect(p.onDraftStateChange).toHaveBeenLastCalledWith(false);expect(p.onConnect).not.toHaveBeenCalled();expect(p.onTest).not.toHaveBeenCalled();
});
it('preserves a saved custom origin and submits no replacement key',async()=>{
 const p=props();render(<ConnectionSettings {...p} status={{serviceUrl:'https://existing.example',hasKey:true,storageAvailable:true}}/>);
 expect(screen.getByLabelText('Service URL')).toHaveValue('https://existing.example');
 await userEvent.setup().click(screen.getByRole('button',{name:'Connect'}));
 expect(p.onConnect).toHaveBeenCalledWith({serviceUrl:'https://existing.example'});
});
it('restores the first-run origin on reset without retaining a typed key',async()=>{
 const p=props(),status={serviceUrl:'',hasKey:false,storageAvailable:true};const view=render(<ConnectionSettings {...p} status={status}/>),user=userEvent.setup();
 await user.clear(screen.getByLabelText('Service URL'));await user.type(screen.getByLabelText('Service URL'),'https://draft.example');await user.type(screen.getByLabelText('Workspace key'),'local-test-only');
 view.rerender(<ConnectionSettings {...p} status={status} resetSignal={1}/>);
 expect(screen.getByLabelText('Service URL')).toHaveValue('https://44.233.174.193');expect(screen.getByLabelText('Workspace key')).toHaveValue('');expect(p.onDraftStateChange).toHaveBeenLastCalledWith(false);
});
