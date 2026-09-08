import {describe,it,expect,vi} from 'vitest';
import type {MatchAPI} from '../src/shared/match';
import {freezeMatchAttempt,canRetryMatch,dispatchMatch,matchRejected} from '../src/renderer/components/match/matchMutation';

describe('Match frozen operations',()=>{
  it('freezes the candidate set and complete body for repeated explicit attempts',async()=>{
    const ids=['one','two'];const attempt=freezeMatchAttempt({kind:'evaluate',queryId:'query',data:{candidate_ids:ids}},100,'frozen-key');
    ids.push('later');
    const api={evaluate:vi.fn(async()=>({ok:true,data:{evaluation_id:'run',status:'queued'}}))} as unknown as MatchAPI;
    await dispatchMatch(api,attempt);await dispatchMatch(api,attempt);
    expect(api.evaluate).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.evaluate).mock.calls[0][0]).toEqual({queryId:'query',data:{candidate_ids:['one','two']},idempotencyKey:'frozen-key'});
    expect(vi.mocked(api.evaluate).mock.calls[1][0]).toEqual(vi.mocked(api.evaluate).mock.calls[0][0]);
    expect('data' in attempt.command&&Object.isFrozen(attempt.command.data)).toBe(true);
  });
  it('does not add a body to stop or planning retry',async()=>{
    const api={stop:vi.fn(),retryPlan:vi.fn()} as unknown as MatchAPI;
    await dispatchMatch(api,freezeMatchAttempt({kind:'stop',queryId:'q'},100,'stop-key'));
    await dispatchMatch(api,freezeMatchAttempt({kind:'retryPlan',id:'p'},100,'plan-key'));
    expect(api.stop).toHaveBeenCalledWith({queryId:'q',idempotencyKey:'stop-key'});
    expect(api.retryPlan).toHaveBeenCalledWith({id:'p',idempotencyKey:'plan-key'});
  });
  it('closes expired and changed-connection retries without new keys',()=>{
    const attempt=freezeMatchAttempt({kind:'continueDiscovery',queryId:'q',data:{acknowledge_unknown:true}},100,'key');
    expect(canRetryMatch(attempt,101)).toBe(true);
    expect(canRetryMatch(attempt,99)).toBe(false);
    expect(canRetryMatch(attempt,100+86_400_000)).toBe(false);
    expect(canRetryMatch({...attempt,connectionChanged:true},101)).toBe(false);
  });
  it('only treats definite pre-dispatch/business rejection as editable, never queue or unknown outcomes',()=>{
    expect(matchRejected('game_context_required')).toBe(true);
    expect(matchRejected('workspace_key_invalid')).toBe(true);
    for(const code of ['planning_queue_unavailable','evaluation_queue_unavailable','discovery_queue_unavailable','save_outcome_unknown','connection_changed','future_error'])expect(matchRejected(code)).toBe(false);
  });
});
