// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {QualificationEditor} from '../src/renderer/components/match/QualificationEditor';
import {compositionFixture,draftFixture,draftValues} from './drafts-fixtures';
import type {Qualification} from '../src/shared/sending';
afterEach(cleanup);
function setup(){
  const composition=compositionFixture({recipient_count:3,drafts:[0,1,2].map(i=>draftFixture({id:`draft-${i}`,recipient_snapshot_id:`recipient-${i}`,input_order:i,input:{channel_name:`Person ${i+1}`}}))});
  const qualification:Qualification={composition_id:composition.id,activity_id:composition.activity_id,qualification_token:'a'.repeat(64),sending_account_token:'b'.repeat(64),sender:{name:'Studio',address:'sender@example.test',reply_to:'reply@example.test'},total_count:3,eligible_count:1,repair_count:1,excluded_count:1,send_ready:false,members:composition.drafts.map((d,i)=>({draft_id:d.id,recipient_snapshot_id:d.recipient_snapshot_id,status:i===0?'eligible':i===1?'needs_repair':'excluded',missing_fields:i===1?['email_not_selected']:[],exclusion_reason:i===2?'Not this round':null,recipient_email:i===1?null:`person${i+1}@example.test`,subject:`Subject ${i}`,html:`<p>Exact email ${i}</p>`,text:`Exact email ${i}`,values:draftValues,slot_sources:{},template_version_id:composition.template_version_id,fixed_hash:'c'.repeat(64),revision:0,context_token:'d'.repeat(64),sender_facts:{},identity:{},blocking_delivery_id:null}))};
  return {composition,qualification,exclusions:[{draft_id:'draft-2',reason:'Not this round'}],current:true,busy:false,onExclusionsChange:vi.fn(),onCheck:vi.fn(),onSend:vi.fn(),onRepairDraft:vi.fn(),onOpenSettings:vi.fn()};
}
it('keeps all original people, actual addresses and sender in the review',()=>{
  const p=setup();render(<QualificationEditor {...p}/>);const roster=screen.getByRole('navigation',{name:'Recipients'});
  expect(within(roster).getAllByRole('button')).toHaveLength(3);expect(roster).toHaveTextContent('Person 2');expect(roster).toHaveTextContent('Excluded');expect(roster).toHaveTextContent('person3@example.test');
  expect(screen.getByText('sender@example.test')).toBeVisible();expect(screen.getByText('reply@example.test')).toBeVisible();
  expect(screen.getByTitle('Email preview')).toHaveAttribute('srcdoc',expect.stringContaining('Exact email 0'));
  expect(screen.queryByRole('button',{name:'Send 1 email'})).not.toBeInTheDocument();
});
it('routes missing sender and stale template repairs without sending or rewriting drafts',async()=>{
 const p=setup(),onUseCurrentTemplate=vi.fn();p.qualification.members[0].missing_fields=['sender_identity_missing','template_context_changed'];p.qualification.members[0].status='needs_repair';
 render(<QualificationEditor {...p} onUseCurrentTemplate={onUseCurrentTemplate}/>);
 expect(p.onOpenSettings).not.toHaveBeenCalled();expect(onUseCurrentTemplate).not.toHaveBeenCalled();
 await userEvent.click(screen.getByRole('button',{name:'Email settings'}));expect(p.onOpenSettings).toHaveBeenCalledOnce();await userEvent.click(screen.getByRole('button',{name:'Use current template'}));expect(onUseCurrentTemplate).toHaveBeenCalledOnce();expect(p.onSend).not.toHaveBeenCalled();
});
it('uses explicit exclusion with a retained reason and invalidates send until rechecked',async()=>{
  const p=setup(),view=render(<QualificationEditor {...p}/>);await userEvent.click(screen.getByRole('checkbox',{name:'Exclude Person 1'}));
  expect(p.onExclusionsChange).toHaveBeenLastCalledWith([...p.exclusions,{draft_id:'draft-0',reason:''}]);
  view.rerender(<QualificationEditor {...p} current={false} exclusions={[...p.exclusions,{draft_id:'draft-0',reason:'Later'}]}/>);
  fireEvent.change(screen.getByRole('textbox',{name:'Exclusion reason for Person 1'}),{target:{value:'Next release'}});
  expect(p.onExclusionsChange).toHaveBeenLastCalledWith([...p.exclusions,{draft_id:'draft-0',reason:'Next release'}]);
  expect(screen.queryByRole('button',{name:/^Send \d/})).not.toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'Check recipients'}));expect(p.onCheck).toHaveBeenCalledOnce();
});
it('allows final explicit send without making every preview a mandatory gate',async()=>{
  const p=setup();p.qualification.members[1]={...p.qualification.members[1],status:'eligible',missing_fields:[],recipient_email:'person2@example.test'};p.qualification.eligible_count=2;p.qualification.repair_count=0;p.qualification.send_ready=true;
  const view=render(<QualificationEditor {...p}/>);expect(screen.getByText(/cannot be recalled/i)).toBeVisible();await userEvent.click(screen.getByRole('button',{name:'Send 2 emails'}));expect(p.onSend).toHaveBeenCalledOnce();
  view.rerender(<QualificationEditor {...p} current={false}/>);expect(screen.queryByRole('button',{name:'Send 2 emails'})).not.toBeInTheDocument();
  view.rerender(<QualificationEditor {...p} busy/>);expect(screen.getByRole('button',{name:'Send 2 emails'})).toBeDisabled();
});
it('blocks send when current is mistakenly true but exclusions differ from the qualification',()=>{
  const p=setup();p.qualification.members[1]={...p.qualification.members[1],status:'eligible',missing_fields:[],recipient_email:'person2@example.test'};p.qualification.eligible_count=2;p.qualification.repair_count=0;p.qualification.send_ready=true;
  render(<QualificationEditor {...p} exclusions={[{draft_id:'draft-2',reason:'Changed reason'}]}/>);
  expect(screen.queryByRole('button',{name:'Send 2 emails'})).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Check recipients'})).toBeEnabled();
});
it('requires filled bounded exclusion reasons before checking and never excludes other people automatically',async()=>{
  const p=setup();render(<QualificationEditor {...p} exclusions={[...p.exclusions,{draft_id:'draft-0',reason:'   '}]}/>);
  expect(screen.getByRole('button',{name:'Check recipients'})).toBeDisabled();
  expect(screen.getByRole('textbox',{name:'Exclusion reason for Person 1'})).toHaveAttribute('maxlength','1000');
  await userEvent.click(screen.getByRole('checkbox',{name:'Exclude Person 1'}));
  expect(p.onExclusionsChange).toHaveBeenLastCalledWith(p.exclusions);
});
it('retains all N before qualification, shows exact selected qualified mail, and opens repair directly',async()=>{
  const p=setup(),view=render(<QualificationEditor {...p} qualification={null}/>);
  expect(within(screen.getByRole('navigation',{name:'Recipients'})).getAllByRole('button')).toHaveLength(3);
  expect(screen.queryByTitle('Email preview')).not.toBeInTheDocument();expect(p.onCheck).not.toHaveBeenCalled();
  view.rerender(<QualificationEditor {...p}/>);await userEvent.click(within(screen.getByRole('navigation',{name:'Recipients'})).getAllByRole('button')[1]);
  expect(screen.getByTitle('Email preview')).toHaveAttribute('sandbox','');expect(screen.getByTitle('Email preview')).toHaveAttribute('srcdoc',expect.stringContaining('Exact email 1'));
  await userEvent.click(screen.getByRole('button',{name:'Repair draft'}));expect(p.onRepairDraft).toHaveBeenCalledWith('draft-1');
});
it('refuses ready qualifications that omit or duplicate original members',()=>{
  const p=setup();p.qualification.send_ready=true;p.qualification.members=[p.qualification.members[0]];p.qualification.total_count=1;p.qualification.repair_count=0;p.qualification.excluded_count=0;
  const view=render(<QualificationEditor {...p} exclusions={[]}/>);expect(screen.queryByRole('button',{name:/^Send \d/})).not.toBeInTheDocument();
  p.qualification.members=[p.qualification.members[0],p.qualification.members[0],p.qualification.members[0]];p.qualification.total_count=3;p.qualification.eligible_count=3;
  view.rerender(<QualificationEditor {...p} exclusions={[]}/>);expect(screen.queryByRole('button',{name:/^Send \d/})).not.toBeInTheDocument();
});
