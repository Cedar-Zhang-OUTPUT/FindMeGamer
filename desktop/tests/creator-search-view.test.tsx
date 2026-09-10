// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import userEvent from '@testing-library/user-event';
import {CreatorSearchView} from '../src/renderer/components/match/CreatorSearchView';
import {candidateFixture} from './match-api-mock';
afterEach(cleanup);
const task:any={id:'search',status:'running',stage:'emails',counts:{discovered:68,profile_ready:68,profile_reused:48,profile_failed:0,email_available:10,email_missing:12,email_failed:0,evaluated:0,matched:0},stop_requested:false,retryable:false,outcome_unknown:false,error_code:null};
const props:any={search:task,loading:false,current:false,people:[],results:[],candidates:[],error:null,disabled:false,onStop:vi.fn(),onRetry:vi.fn(),onAppend:vi.fn(),onRefresh:vi.fn(),onOpenCreator:vi.fn(),onOpenExternal:vi.fn(),isSelected:()=>false,onToggle:vi.fn()};
it('shows one real processing stage with stop, not completed results or drafting',()=>{
 render(<CreatorSearchView {...props}/>);expect(screen.getByRole('heading',{name:'Finding contact details'})).toBeVisible();expect(screen.getByRole('button',{name:'Stop search'})).toBeVisible();expect(screen.queryByText('Complete')).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:/Draft.*emails/})).not.toBeInTheDocument();expect(screen.getByText('Processing details').closest('details')).not.toHaveAttribute('open');
});
it('counts reused profiles only once and keeps an uncertain retry behind charge acknowledgement',async()=>{
 const user=userEvent.setup(),onRetry=vi.fn();
 const {rerender}=render(<CreatorSearchView {...props} search={{...task,stage:'profiles'}}/>);
 expect(screen.getByRole('status')).toHaveTextContent('68 processed · 68 discovered');
 rerender(<CreatorSearchView {...props} onRetry={onRetry} search={{...task,status:'partial',stage:'complete',retryable:true,outcome_unknown:true}}/>);
 expect(screen.getByRole('heading',{name:'Finished with issues'})).toBeVisible();
 const retry=screen.getByRole('button',{name:'Retry unfinished work'});expect(retry).toBeDisabled();
 await user.click(screen.getByRole('checkbox',{name:/possible repeated/}));await user.click(retry);expect(onRetry).toHaveBeenCalledExactlyOnceWith(true);
 expect(retry).toBeDisabled();
 rerender(<CreatorSearchView {...props} search={{...task,status:'stopping',stage:'complete'}}/>);
 expect(screen.queryByRole('heading',{name:'Complete'})).not.toBeInTheDocument();
});
it('retains previously loaded results after a read failure but disables selection',()=>{
 const candidate=candidateFixture();
 render(<CreatorSearchView {...props} search={{...task,status:'partial',stage:'complete'}} error={{code:'network_error',message:'Could not refresh.',retryable:true}} candidates={[candidate]} people={[{candidate_id:candidate.id,creator_id:candidate.creator_id,platform:'youtube',profile_status:'failed',email_status:'missing'}]}/>);
 expect(screen.getByRole('region',{name:'Creator matches'})).toBeVisible();
 expect(screen.getByRole('checkbox',{name:/Select/})).toBeDisabled();
 expect(screen.getByText('Not evaluated')).toBeVisible();expect(screen.getByText('Could not refresh.')).toBeVisible();
});
it('keeps strong fit separate from missing email and exposes the existing creator',()=>{
 const candidate=candidateFixture();const result:any={candidate_id:candidate.id,creator_id:candidate.creator_id,name:'Creator 1',platform:'youtube',fit_group:'strong_fit',match_brief:{summary:'Fits the atmospheric games audience.',limitations:[]},evidence:[],stale:false,identity_changed:false};
 render(<CreatorSearchView {...props} current search={{...task,status:'completed',stage:'complete',counts:{...task.counts,evaluated:68,matched:1}}} candidates={[candidate]} results={[result]} people={[{candidate_id:candidate.id,creator_id:candidate.creator_id,platform:'youtube',profile_status:'ready',email_status:'missing'}]}/>);
 expect(screen.getByText('Strong fit')).toBeVisible();expect(screen.getByText('Email not found')).toBeVisible();expect(screen.getByText('Fits the atmospheric games audience.')).toBeVisible();expect(screen.getByRole('button',{name:'View Creator 1'})).toBeVisible();expect(screen.queryByRole('tab',{name:'Candidates'})).not.toBeInTheDocument();
});
