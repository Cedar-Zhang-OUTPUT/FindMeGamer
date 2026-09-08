// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/renderer/App';
import type { DesktopBridge } from '../src/shared/bridge';
import { ok, settingsBridgeMock } from './settings-fixtures';

function start(connected = false) {
  const local = settingsBridgeMock();
  const api: DesktopBridge = { ...local,
    connection: {
      status: vi.fn(async () => ok({serviceUrl:connected?'https://workspace.example.com':'',hasKey:connected,storageAvailable:true})),
      test: vi.fn(async () => ok({authenticated:true,proxy:'system',route:'direct'} as const)),
      save: vi.fn(async () => ok({serviceUrl:'https://workspace.example.com',hasKey:true,storageAvailable:true})),
      clear: vi.fn(async () => ok({serviceUrl:'',hasKey:false,storageAvailable:true})),
    },
    library:{list:vi.fn(async()=>ok({items:[],nextCursor:null})),detail:vi.fn()},
    games:{list:vi.fn(async()=>ok({items:[],total:0,limit:24,offset:0})),detail:vi.fn(),create:vi.fn(),update:vi.fn()},
    openExternal:vi.fn(async()=>ok(undefined)),
  };
  window.desktop=api; render(<App/>); return {api,user:userEvent.setup()};
}
afterEach(()=>{cleanup();vi.restoreAllMocks();Reflect.deleteProperty(window,'desktop');document.documentElement.removeAttribute('data-theme');document.documentElement.style.removeProperty('font-size');});

describe('complete Settings host',()=>{
  it('shows one connection status and keeps route details optional',async()=>{
    const {user}=start(true);
    await user.click(await screen.findByRole('button',{name:'Settings'}));
    expect(screen.getByText('Connection verified')).toBeVisible();
    expect(screen.queryByText('Connected', {exact:true})).not.toBeInTheDocument();
    const route=screen.getByText(/Direct route/);
    expect(route).not.toBeVisible();
    await user.click(screen.getByText('Connection details',{selector:'summary'}));
    expect(route).toBeVisible();
    expect(screen.getByRole('button',{name:'Open Library'})).toBeEnabled();
  });
  it('offers reconnect only when connected workspace fields change',async()=>{
    const {api,user}=start(true);await user.click(await screen.findByRole('button',{name:'Settings'}));
    expect(screen.queryByRole('button',{name:'Connect'})).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Test connection'})).toBeEnabled();
    await user.type(screen.getByLabelText('Workspace key',{exact:true}),'replacement-test-key');
    expect(screen.getByRole('button',{name:'Connect'})).toBeEnabled();
    expect(screen.getByRole('button',{name:'Test connection'})).toBeDisabled();
    expect(api.connection.save).not.toHaveBeenCalled();
  });
  it('previews appearance immediately and rolls back a failed local write',async()=>{
    const {api,user}=start();
    let resolve!:(value:Awaited<ReturnType<typeof api.preferences.update>>)=>void;
    vi.mocked(api.preferences.update).mockReturnValueOnce(new Promise(done=>{resolve=done;}));
    await user.click(await screen.findByRole('button',{name:'Open Settings'}));await user.click(screen.getByRole('tab',{name:'Appearance'}));
    await user.click(screen.getByRole('radio',{name:'Dark'}));
    expect(document.documentElement).toHaveAttribute('data-theme','dark');
    expect(screen.getByRole('radio',{name:'Dark'})).toBeDisabled();
    await act(async()=>resolve({ok:false,error:{code:'local_write_failed',message:'Local preference could not be saved.',retryable:true}}));
    expect(screen.getByRole('radio',{name:'System'})).toBeChecked();
    expect(screen.getByRole('alert')).toHaveTextContent('Local preference could not be saved.');
  });
  it('preserves a hidden service draft and blocks workspace replacement until explicitly discarded',async()=>{
    const {api,user}=start(true);await waitFor(()=>expect(api.settings.smtp).toHaveBeenCalledOnce());
    await user.click(screen.getByRole('button',{name:'Settings'}));await user.click(screen.getByRole('tab',{name:'Services'}));
    await user.click(screen.getByRole('button',{name:'Replace YouTube credential'}));await user.type(screen.getByLabelText('YouTube replacement credential'),'synthetic-retained');
    await user.click(screen.getByRole('tab',{name:'Appearance'}));await user.click(screen.getByRole('tab',{name:'Services'}));
    expect(screen.getByLabelText('YouTube replacement credential')).toHaveValue('synthetic-retained');
    await user.click(screen.getByRole('tab',{name:'Workspace'}));expect(screen.getByRole('button',{name:'Disconnect'})).toBeDisabled();expect(screen.getByLabelText('Service URL')).toBeDisabled();
    await user.click(screen.getByRole('button',{name:'Library'}));await user.keyboard('{Escape}');expect(api.connection.clear).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button',{name:'Library'}));await user.click(screen.getByRole('button',{name:'Discard changes'}));
    await user.click(screen.getByRole('button',{name:'Settings'}));expect(screen.getByRole('button',{name:'Disconnect'})).toBeEnabled();
    await user.click(screen.getByRole('tab',{name:'Services'}));await user.click(screen.getByRole('button',{name:'Replace YouTube credential'}));expect(screen.getByLabelText('YouTube replacement credential')).toHaveValue('');
  });
  it('blocks app exit/navigation while a shared mutation is pending without automatically navigating afterward',async()=>{
    const {api,user}=start(true);await waitFor(()=>expect(api.settings.smtp).toHaveBeenCalledOnce());
    let resolve!:(value:Awaited<ReturnType<typeof api.settings.replaceConnection>>)=>void;
    vi.mocked(api.settings.replaceConnection).mockReturnValueOnce(new Promise(done=>{resolve=done;}));
    await user.click(screen.getByRole('button',{name:'Settings'}));await user.click(screen.getByRole('tab',{name:'Services'}));
    await user.click(screen.getByRole('button',{name:'Replace YouTube credential'}));await user.type(screen.getByLabelText('YouTube replacement credential'),'synthetic-pending');await user.click(screen.getByRole('button',{name:'Save YouTube credential'}));await user.click(screen.getByRole('button',{name:'Confirm'}));
    await user.click(screen.getByRole('button',{name:'Library'}));expect(screen.getByRole('dialog',{name:'Action in progress'})).toBeVisible();
    const unload=new Event('beforeunload',{cancelable:true});window.dispatchEvent(unload);expect(unload.defaultPrevented).toBe(true);
    await act(async()=>resolve(ok({configured:true,lastTestStatus:null,lastTestedAt:null})));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Settings'})).toBeVisible();
  });
  it('offers local appearance without workspace access and applies it across the app',async()=>{
    const {api,user}=start();
    await user.click(await screen.findByRole('button',{name:'Open Settings'}));
    await user.click(screen.getByRole('tab',{name:'Appearance'}));
    await user.click(await screen.findByRole('radio',{name:'Dark'}));
    await waitFor(()=>expect(document.documentElement).toHaveAttribute('data-theme','dark'));
    await user.selectOptions(screen.getByLabelText('Text size'),'extra-large');
    expect(api.preferences.update).toHaveBeenLastCalledWith({fontSize:'extra-large'});
    await waitFor(()=>expect(document.documentElement.style.fontSize).toBe('20px'));
    await user.click(screen.getByRole('button',{name:'Restore appearance defaults'}));
    expect(api.preferences.restoreAppearance).toHaveBeenCalledOnce();
    expect(api.settings.smtp).not.toHaveBeenCalled();
  });
  it('keeps workspace input across categories and confirms before discarding it',async()=>{
    const {api,user}=start();
    await user.click(await screen.findByRole('button',{name:'Open Settings'}));
    await user.type(screen.getByLabelText('Service URL'),'https://draft.example.com');
    await user.type(screen.getByLabelText('Workspace key'),'synthetic-unsaved');
    await user.click(screen.getByRole('tab',{name:'Appearance'}));
    await user.click(screen.getByRole('tab',{name:'Workspace'}));
    expect(screen.getByLabelText('Service URL')).toHaveValue('https://draft.example.com');
    await user.click(screen.getByRole('button',{name:'Library'}));
    expect(screen.getByRole('dialog',{name:'Unsaved settings'})).toBeVisible();
    await user.keyboard('{Escape}');
    expect(screen.getByLabelText('Workspace key')).toHaveValue('synthetic-unsaved');
    await user.click(screen.getByRole('button',{name:'Library'}));
    await user.click(screen.getByRole('button',{name:'Discard changes'}));
    await user.click(screen.getByRole('button',{name:'Settings'}));
    expect(screen.getByLabelText('Workspace key')).toHaveValue('');
    expect(api.connection.save).not.toHaveBeenCalled();
  });
  it('keeps software checking and automatic-check preference local',async()=>{
    const {api,user}=start();
    await user.click(await screen.findByRole('button',{name:'Open Settings'}));
    await user.click(screen.getByRole('tab',{name:'Updates'}));
    await user.click(await screen.findByRole('button',{name:'Check for updates'}));
    expect(await screen.findByText('Up to date')).toBeVisible();
    await user.click(screen.getByLabelText('Automatically check for updates'));
    expect(api.preferences.update).toHaveBeenLastCalledWith({automaticUpdates:false});
    await user.click(screen.getByRole('button',{name:'All releases on GitHub'}));
    expect(api.openExternal).toHaveBeenCalledWith('https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases');
    expect(api.connection.save).not.toHaveBeenCalled();
  });
});
