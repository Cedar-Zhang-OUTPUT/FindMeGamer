// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import type {SettingsAPI,CollectionSettings} from '../src/shared/settings';
import {useCollectionPolicy} from '../src/renderer/components/match/useCollectionPolicy';
const data:CollectionSettings={items:[{platform:'youtube',enabled:false,implemented:true,credentials_configured:true,availability:'disabled'}]};
afterEach(()=>{cleanup();vi.useRealTimers();});
it('does not read a hidden task; activation and manual refresh only read policy',async()=>{
  const collection=vi.fn(async()=>({ok:true as const,data})),setCollection=vi.fn();const api={collection,setCollection} as unknown as SettingsAPI;
  const {result,rerender}=renderHook(({active})=>useCollectionPolicy(api,active),{initialProps:{active:false}});
  expect(collection).not.toHaveBeenCalled();rerender({active:true});await waitFor(()=>expect(result.current.data).toEqual(data));
  act(()=>result.current.refresh());await waitFor(()=>expect(collection).toHaveBeenCalledTimes(2));expect(setCollection).not.toHaveBeenCalled();
});
it('retains the last known rows on read failure but makes them non-authoritative for new collection',async()=>{
  const collection=vi.fn<SettingsAPI['collection']>().mockResolvedValueOnce({ok:true,data}).mockResolvedValue({ok:false,error:{code:'network_error',message:'Offline',retryable:true}});
  const api={collection} as unknown as SettingsAPI;const {result}=renderHook(()=>useCollectionPolicy(api,true));await waitFor(()=>expect(result.current.phase).toBe('ready'));
  act(()=>result.current.refresh());await waitFor(()=>expect(result.current.phase).toBe('failed'));
  expect(result.current.data).toEqual(data);expect(result.current.error?.code).toBe('network_error');
});
it('ignores a late read after refresh and stops periodic reads when hidden',async()=>{
  let finish!:(value:{ok:true;data:CollectionSettings})=>void;
  const newer={items:[{...data.items[0],enabled:true,availability:'configured_unverified' as const}]};
  const collection=vi.fn<SettingsAPI['collection']>().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue({ok:true,data:newer});
  const api={collection} as unknown as SettingsAPI;const {result,rerender}=renderHook(({active})=>useCollectionPolicy(api,active),{initialProps:{active:true}});
  act(()=>result.current.refresh());await waitFor(()=>expect(result.current.data).toEqual(newer));
  await act(async()=>finish({ok:true,data}));expect(result.current.data).toEqual(newer);
  rerender({active:false});vi.useFakeTimers();await act(async()=>vi.advanceTimersByTime(20000));expect(collection).toHaveBeenCalledTimes(2);
});
it('keeps ready controls stable during a background policy refresh',async()=>{
  vi.useFakeTimers();
  const collection=vi.fn<SettingsAPI['collection']>().mockResolvedValueOnce({ok:true,data}).mockImplementation(()=>new Promise(()=>{}));
  const api={collection} as unknown as SettingsAPI;const {result}=renderHook(()=>useCollectionPolicy(api,true));
  await act(async()=>{});expect(result.current.phase).toBe('ready');
  await act(async()=>vi.advanceTimersByTime(5000));
  expect(collection).toHaveBeenCalledTimes(2);expect(result.current.phase).toBe('ready');expect(result.current.data).toEqual(data);
});
