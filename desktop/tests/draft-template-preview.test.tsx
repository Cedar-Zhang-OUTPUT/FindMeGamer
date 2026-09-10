// @vitest-environment jsdom
import {act,cleanup,renderHook,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useDraftTemplatePreview} from '../src/renderer/components/match/useDraftTemplatePreview';
import {templateVersion} from './drafts-fixtures';
afterEach(cleanup);
const ok=<T,>(data:T)=>({ok:true as const,data});
it('loads the exact immutable version once, keeps reads independent, and retries a failed GET',async()=>{
 const failure={code:'service_error',message:'Template unavailable',retryable:true};
 const api={template:vi.fn().mockResolvedValueOnce({ok:false,error:failure}).mockResolvedValue(ok(templateVersion))};
 const view=renderHook(()=>useDraftTemplatePreview(api,templateVersion.id,true));
 await waitFor(()=>expect(view.result.current.error).toEqual(failure));
 act(()=>view.result.current.reload());await waitFor(()=>expect(view.result.current.template?.id).toBe(templateVersion.id));
 view.rerender();expect(api.template).toHaveBeenCalledTimes(2);expect(api.template).toHaveBeenCalledWith(templateVersion.id);
});
it('uses only exact catalog versions and rejects a mismatched GET response',async()=>{
 const api={template:vi.fn(async()=>ok(templateVersion))};
 const view=renderHook(({id,cached})=>useDraftTemplatePreview(api,id,true,cached),{initialProps:{id:templateVersion.id,cached:templateVersion}});
 expect(view.result.current.template).toEqual(templateVersion);expect(api.template).not.toHaveBeenCalled();
 view.rerender({id:'another-version',cached:templateVersion});
 expect(view.result.current.template).toBeNull();
 await waitFor(()=>expect(view.result.current.error?.code).toBe('invalid_response'));
});
it('ignores late old versions and fences reads when hidden',async()=>{
 let finish!:(value:ReturnType<typeof ok<typeof templateVersion>>)=>void;
 const next={...templateVersion,id:'new-version'};
 const api={template:vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue(ok(next))};
 const view=renderHook(({id,active})=>useDraftTemplatePreview(api,id,active),{initialProps:{id:templateVersion.id,active:true}});
 view.rerender({id:next.id,active:true});await waitFor(()=>expect(view.result.current.template?.id).toBe(next.id));
 await act(()=>finish(ok(templateVersion)));expect(view.result.current.template?.id).toBe(next.id);
 view.rerender({id:next.id,active:false});expect(view.result.current.loading).toBe(false);
});
