// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {act,cleanup,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {CredentialStore} from '../src/main/credential-store';
import {WorkspaceGateway} from '../src/main/gateway';
import {MatchWorkspace} from '../src/renderer/components/match/MatchWorkspace';
import type {DesktopBridge,Result} from '../src/shared/bridge';
import type {ActivityPage} from '../src/shared/match';
import {activityFixture,matchAPIMock} from './match-api-mock';
import {settingsBridgeMock} from './settings-fixtures';

afterEach(cleanup);
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return {promise,resolve};}

it('diagnoses synthetic credential queue and decrypt waits before the HTTP timeout is created',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'fmg-activities-diagnosis-'));
 const first=deferred<string>(),second=deferred<string>();
 const events:{stage:string;elapsedMs:number}[]=[];const start=performance.now();
 const mark=(stage:string)=>events.push({stage,elapsedMs:Math.round(performance.now()-start)});
 let decrypts=0;
 const store=new CredentialStore(directory,{isEncryptionAvailable:()=>true,encryptString:()=>Buffer.from('synthetic-cipher'),decryptString:()=>{decrypts++;mark(`decrypt-${decrypts}-start`);return decrypts===1?first.promise:second.promise;}});
 try{
  await store.save({serviceUrl:'https://workspace.invalid',key:'synthetic-key'});
  const timeout=vi.spyOn(AbortSignal,'timeout');
  const fetcher=vi.fn(async()=>{mark('fetch');return new Response('{}');});
  const gateway=new WorkspaceGateway(store,fetcher);
  const request={method:'GET' as const,path:'/api/v2/activities',query:{offset:'0',limit:'50'}};
  const a=gateway.matchRequest(request),b=gateway.matchRequest(request);
  await waitFor(()=>expect(decrypts).toBe(1));
  await new Promise(resolve=>setTimeout(resolve,60));mark('first-gate-release');
  expect(fetcher).not.toHaveBeenCalled();expect(timeout).not.toHaveBeenCalled();
  first.resolve('synthetic-key');await a;
  await waitFor(()=>expect(decrypts).toBe(2));
  expect(fetcher).toHaveBeenCalledTimes(1);expect(timeout).toHaveBeenCalledTimes(1);
  await new Promise(resolve=>setTimeout(resolve,60));mark('second-gate-release');
  second.resolve('synthetic-key');await b;
  expect(fetcher).toHaveBeenCalledTimes(2);expect(timeout.mock.calls).toEqual([[20_000],[20_000]]);
  expect(events.findIndex(e=>e.stage==='decrypt-2-start')).toBeGreaterThan(events.findIndex(e=>e.stage==='first-gate-release'));
  process.stdout.write(`SYNTHETIC timing only; not OS Keychain or online latency: ${JSON.stringify(events)}\n`);
  timeout.mockRestore();
 }finally{first.resolve('synthetic-key');second.resolve('synthetic-key');vi.restoreAllMocks();await rm(directory,{recursive:true,force:true});}
});

it('counts duplicate pending list invokes across navigation and ignores the old result',async()=>{
 const first=deferred<Result<ActivityPage>>(),second=deferred<Result<ActivityPage>>();
 const api={...settingsBridgeMock(),match:matchAPIMock()} as unknown as DesktopBridge;
 vi.mocked(api.match.activities).mockImplementationOnce(()=>first.promise).mockImplementationOnce(()=>second.promise);
 const view=render(<MatchWorkspace api={api} active/>);
 await waitFor(()=>expect(api.match.activities).toHaveBeenCalledTimes(1));
 view.rerender(<MatchWorkspace api={api} active={false}/>);
 view.rerender(<MatchWorkspace api={api} active/>);
 await waitFor(()=>expect(api.match.activities).toHaveBeenCalledTimes(2));
 const page=(name:string):Result<ActivityPage>=>({ok:true,data:{items:[{...activityFixture(),name}],total:1,offset:0,limit:50}});
 await act(async()=>first.resolve(page('Obsolete response')));
 expect(screen.queryByRole('button',{name:'Open Obsolete response'})).not.toBeInTheDocument();
 await act(async()=>second.resolve(page('Current response')));
 expect(await screen.findByRole('button',{name:'Open Current response'})).toBeVisible();
 view.rerender(<MatchWorkspace api={api} active={false}/>);view.rerender(<MatchWorkspace api={api} active/>);
 expect(api.match.activities).toHaveBeenCalledTimes(2);
 expect(api.match.activity).not.toHaveBeenCalled();expect(api.match.plans).not.toHaveBeenCalled();
 process.stdout.write('Synthetic renderer calls: pending leave/return=2; completed leave/return remains=2; detail=0; plans=0\n');
});
