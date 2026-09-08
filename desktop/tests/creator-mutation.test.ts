import { describe,expect,it,vi } from 'vitest';
import { freezeAttempt, canReplay, dispatchMutation, certainlyRejected, type MutationCommand } from '../src/renderer/components/creators/creatorMutation';
import { creatorFixture, workFixture } from './creator-fixtures';
import type { CreatorAPI } from '../src/shared/creators';

describe('Creator mutation boundaries',()=>{
  it('freezes the original omitted-field POST body and key independently of later edits',()=>{
    const command:MutationCommand={kind:'creator',id:null,data:{profile_url:'https://youtube.com/@fixture',languages:['en']}};
    const attempt=freezeAttempt(command,1000,'fixed-creator-key');
    command.data.languages!.push('fr');command.data.profile_url='https://youtube.com/@changed';
    expect(attempt.command).toEqual({kind:'creator',id:null,data:{profile_url:'https://youtube.com/@fixture',languages:['en']}});
    expect(attempt.key).toBe('fixed-creator-key');expect(Object.isFrozen(attempt.command.data)).toBe(true);
    expect(attempt.command.data).not.toHaveProperty('platform');
  });
  it('allows replay only for unchanged credentials within the original 24h window',()=>{
    const attempt=freezeAttempt({kind:'creator',id:null,data:{account_id:'UC_fixture'}},1000,'fixed-creator-key');
    expect(canReplay(attempt,1000+86_400_000-1)).toBe(true);
    expect(canReplay(attempt,1000+86_400_000)).toBe(false);
    expect(canReplay({...attempt,credentialsChanged:true},1001)).toBe(false);
    expect(canReplay({...attempt,workspaceChanged:true},1001)).toBe(false);
    expect(canReplay(attempt,999)).toBe(false);
  });
  it('routes contact creation with parent revision and work editing with its own revision',async()=>{
    const api={createContact:vi.fn(async()=>({ok:true,data:creatorFixture()})),updateWork:vi.fn(async()=>({ok:true,data:workFixture()}))} as unknown as CreatorAPI;
    await dispatchMutation(api,freezeAttempt({kind:'contact',creatorId:'parent',id:null,data:{expected_revision:7,email:'fixture@example.com'}},0,'contact-fixed-key'));
    expect(api.createContact).toHaveBeenCalledExactlyOnceWith({creatorId:'parent',data:{expected_revision:7,email:'fixture@example.com'},idempotencyKey:'contact-fixed-key'});
    await dispatchMutation(api,freezeAttempt({kind:'work',creatorId:'parent',id:'work',data:{expected_revision:3,metrics:[]}},0,'unused-key'));
    expect(api.updateWork).toHaveBeenCalledExactlyOnceWith({creatorId:'parent',workId:'work',data:{expected_revision:3,metrics:[]}});
  });
  it('does not classify uncertain transport errors as permission to start a fresh POST',()=>{
    for(const code of ['save_outcome_unknown','network_error','connection_changed','idempotency_key_conflict'])expect(certainlyRejected(code)).toBe(false);
    expect(certainlyRejected('request_invalid')).toBe(true);
    expect(certainlyRejected('creator_revision_conflict')).toBe(true);
  });
});
