// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,renderHook} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {useMatchOperation} from '../src/renderer/components/match/useMatchOperation';
import {matchAPIMock} from './match-api-mock';
afterEach(cleanup);
it('blocks double starts and unknown replacement; explicit retry preserves the entire intent',async()=>{
  const api=matchAPIMock();let finish!:(value:any)=>void;
  vi.mocked(api.evaluate).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve));
  const {result}=renderHook(()=>useMatchOperation(api));
  const command={kind:'evaluate' as const,queryId:'q',data:{candidate_ids:['one']}};
  let pending!:Promise<unknown>;
  act(()=>{pending=result.current.execute(command);});
  await act(async()=>{await result.current.execute({...command,data:{candidate_ids:['two']}});});
  expect(api.evaluate).toHaveBeenCalledOnce();
  await act(async()=>{finish({ok:false,error:{code:'network_error',message:'Interrupted',retryable:true}});await pending;});
  expect(result.current.state.phase).toBe('uncertain');
  await act(async()=>{await result.current.execute(command);});expect(api.evaluate).toHaveBeenCalledOnce();
  await act(async()=>{await result.current.retry();});
  expect(api.evaluate).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.evaluate).mock.calls[0]).toEqual(vi.mocked(api.evaluate).mock.calls[1]);
  expect(result.current.state.phase).toBe('idle');
});
it('a rejected replay stays uncertain and same-origin key replacement blocks replay',async()=>{
  const api=matchAPIMock();vi.mocked(api.createActivity).mockResolvedValueOnce({ok:false,error:{code:'save_outcome_unknown',message:'Unknown',retryable:false}}).mockResolvedValueOnce({ok:false,error:{code:'workspace_key_invalid',message:'Repair key',retryable:false}});
  const {result}=renderHook(()=>useMatchOperation(api));
  await act(async()=>{await result.current.execute({kind:'createActivity',data:{name:'N',game_id:'g'}});await result.current.retry();});
  expect(result.current.state.phase).toBe('uncertain');
  act(()=>result.current.credentialsChanged());
  await act(async()=>{await result.current.retry();});
  expect(api.createActivity).toHaveBeenCalledTimes(2);expect(result.current.retryAllowed).toBe(false);
});
