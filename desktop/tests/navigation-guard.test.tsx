// @vitest-environment jsdom
import { cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useNavigationGuard } from '../src/renderer/hooks/useNavigationGuard';

afterEach(cleanup);
describe('unsaved task navigation', () => {
  it('navigates directly only without a pending task', () => {
    const {result} = renderHook(useNavigationGuard);
    const proceed = vi.fn();
    result.current.request(proceed);
    expect(proceed).toHaveBeenCalledOnce();
  });
  it('defers the destination until the task explicitly releases it', () => {
    const {result} = renderHook(useNavigationGuard);
    let release: (()=>void) | undefined;
    result.current.register(next => {release=next;});
    const proceed = vi.fn();
    result.current.request(proceed);
    expect(proceed).not.toHaveBeenCalled();
    expect(result.current.hasPending()).toBe(true);
    release!();
    expect(proceed).toHaveBeenCalledOnce();
  });
  it('blocks window reload/close only while a draft or save is unresolved', () => {
    const {result,unmount} = renderHook(useNavigationGuard);
    result.current.register(() => {});
    const blocked = new Event('beforeunload',{cancelable:true});
    window.dispatchEvent(blocked);
    expect(blocked.defaultPrevented).toBe(true);
    result.current.register(null);
    const allowed = new Event('beforeunload',{cancelable:true});
    window.dispatchEvent(allowed);
    expect(allowed.defaultPrevented).toBe(false);
    result.current.register(() => {});
    unmount();
    const after = new Event('beforeunload',{cancelable:true});
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });
});
