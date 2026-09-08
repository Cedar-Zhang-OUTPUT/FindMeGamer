// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {useState} from 'react';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,describe,expect,it,vi} from 'vitest';
import type {PlanCreate} from '../src/shared/match';
import {DiscoveryConditions} from '../src/renderer/components/match/DiscoveryConditions';
import {defaultConditions,validateConditions} from '../src/renderer/components/match/discoveryConditionState';
afterEach(cleanup);
function Harness({initial=defaultConditions(),submit=vi.fn(),disabled=false}:{initial?:PlanCreate;submit?:()=>void;disabled?:boolean}){
  const [value,onChange]=useState(initial);
  return <><DiscoveryConditions value={value} onChange={onChange} onSubmit={submit} disabled={disabled}/><output data-testid="conditions">{JSON.stringify(value)}</output></>;
}
const payload=()=>JSON.parse(screen.getByTestId('conditions').textContent!) as PlanCreate;
describe('discovery condition values',()=>{
  it('defaults to supported discovery, all unknown values and bounded budgets',()=>{
    expect(defaultConditions()).toEqual({mode:'discover',platforms:['youtube','x'],keywords:[],filters:{countries:[],languages:[],pending_country_labels:[],follower_ranges:[],include_unknown_country:true,include_unknown_language:true,include_unknown_followers:true,contact:'any'},batch_target:100,result_limit:600,batch_request_budget:20,batch_scan_budget:1000,total_request_budget:120,total_scan_budget:6000});
  });
  it('validates platform, text, range and budget limits without confusing zero with unknown',()=>{
    const value=defaultConditions();value.platforms=[];value.keywords=['\n'];value.filters={countries:['USA'],languages:[''],follower_ranges:[{minimum:10,maximum:0}]};value.total_scan_budget=12001;
    expect(validateConditions(value)).toMatchObject({platforms:expect.any(String),keywords:expect.any(String),countries:expect.any(String),languages:expect.any(String),follower_ranges:expect.any(String),total_scan_budget:expect.any(String)});
    expect(validateConditions({...defaultConditions(),filters:{follower_ranges:[{minimum:0,maximum:0}]}})).toEqual({});
    for(const range of [{minimum:null,maximum:null},{minimum:1.5,maximum:2},{minimum:Infinity},{minimum:-1}])expect(validateConditions({...defaultConditions(),filters:{follower_ranges:[range]}})).toHaveProperty('follower_ranges');
    expect(validateConditions({...defaultConditions(),keywords:Array.from({length:21},(_,i)=>String(i))})).toHaveProperty('keywords');
  });
});
describe('DiscoveryConditions',()=>{
  it('keeps quota notice visible, unavailable providers disabled and advanced budgets optional',async()=>{
    const user=userEvent.setup(),submit=vi.fn();render(<Harness submit={submit}/>);
    expect(screen.getByText('Uses model and platform quotas.')).toBeVisible();
    expect(screen.getByRole('checkbox',{name:/Twitch/})).toBeDisabled();expect(screen.getByRole('checkbox',{name:/Instagram/})).toBeDisabled();
    expect(screen.getByLabelText('Batch target')).not.toBeVisible();
    await user.click(screen.getByText('Advanced limits',{selector:'summary'}));
    expect(screen.getByLabelText('Batch target')).toHaveValue(100);
    await user.clear(screen.getByLabelText('Batch request budget'));await user.type(screen.getByLabelText('Batch request budget'),'41');await user.click(screen.getByRole('button',{name:'Find creators'}));
    expect(submit).not.toHaveBeenCalled();expect(screen.getByLabelText('Batch request budget')).toHaveAttribute('aria-invalid','true');
  });
  it('applies languages only on Apply and restores focus and original values on Escape',async()=>{
    const user=userEvent.setup();render(<Harness/>);const trigger=screen.getByRole('button',{name:/Content languages/});await user.click(trigger);
    let dialog=within(screen.getByRole('dialog',{name:'Content languages'}));await user.click(dialog.getByRole('checkbox',{name:'English · en'}));
    expect(payload().filters?.languages).toEqual([]);await user.keyboard('{Escape}');expect(trigger).toHaveFocus();
    await user.click(trigger);dialog=within(screen.getByRole('dialog'));expect(dialog.getByRole('checkbox',{name:'English · en'})).not.toBeChecked();
    await user.click(dialog.getByRole('checkbox',{name:'English · en'}));expect(dialog.getByRole('checkbox',{name:'Include unknown languages'})).not.toBeChecked();
    await user.type(dialog.getByLabelText('Other language'),'Klingon{Enter}');await user.click(dialog.getByRole('button',{name:'Apply'}));
    expect(payload().filters).toMatchObject({languages:['en','Klingon'],include_unknown_language:false,countries:[]});
  });
  it('searches country codes, deduplicates recognized names, keeps pending labels separate and cancels edits',async()=>{
    const user=userEvent.setup();render(<Harness/>);await user.click(screen.getByRole('button',{name:/Country or region/}));let dialog=within(screen.getByRole('dialog'));
    await user.click(dialog.getByRole('button',{name:'North America'}));expect(dialog.getByRole('checkbox',{name:'Include unknown countries'})).not.toBeChecked();
    await user.type(dialog.getByLabelText('Other country or region'),'United States{Enter}');
    await user.type(dialog.getByLabelText('Other country or region'),'Atlantis{Enter}');await user.click(dialog.getByRole('button',{name:'Apply'}));
    expect(payload().filters).toMatchObject({countries:['US','CA'],pending_country_labels:['Atlantis'],include_unknown_country:false});
    await user.click(screen.getByRole('button',{name:/Country or region/}));dialog=within(screen.getByRole('dialog'));await user.type(dialog.getByRole('searchbox'),'JP');
    expect(dialog.getByRole('checkbox',{name:'Japan · JP'})).toBeVisible();expect(dialog.queryByRole('checkbox',{name:'Canada · CA'})).not.toBeInTheDocument();
    await user.click(dialog.getByRole('checkbox',{name:'Japan · JP'}));await user.click(dialog.getByRole('button',{name:'Cancel'}));expect(payload().filters?.countries).toEqual(['US','CA']);
  });
  it('keeps custom-language entry ready for consecutive additions and focuses existing duplicates',async()=>{
    const user=userEvent.setup();render(<Harness/>);await user.click(screen.getByRole('button',{name:/Content languages/}));const dialog=within(screen.getByRole('dialog'));
    const input=dialog.getByLabelText('Other language');await user.type(input,'Klingon{Enter}');await new Promise(resolve=>requestAnimationFrame(resolve));
    expect(input).toHaveFocus();await user.keyboard('Elvish{Enter}');await new Promise(resolve=>requestAnimationFrame(resolve));
    expect(input).toHaveFocus();await user.type(input,'klingon{Enter}');expect(dialog.getByRole('checkbox',{name:'Klingon'})).toHaveFocus();
    await user.click(dialog.getByRole('button',{name:'Apply'}));expect(payload().filters?.languages).toEqual(['Klingon','Elvish']);
  });
  it('traps dialog keyboard focus, restores Any after the final deselection, and prevents disabled edits',async()=>{
    const user=userEvent.setup();const {unmount}=render(<Harness/>);await user.click(screen.getByRole('button',{name:/Country or region/}));const dialog=within(screen.getByRole('dialog'));
    expect(dialog.getByRole('searchbox')).toHaveFocus();await user.tab({shift:true});expect(dialog.getByRole('button',{name:'Apply'})).toHaveFocus();await user.tab();expect(dialog.getByRole('searchbox')).toHaveFocus();
    await user.click(dialog.getByRole('checkbox',{name:'Japan · JP'}));await user.click(dialog.getByRole('checkbox',{name:'Japan · JP'}));
    expect(dialog.getByRole('checkbox',{name:'Any'})).toBeChecked();expect(dialog.getByRole('checkbox',{name:'Include unknown countries'})).toBeChecked();
    await user.click(dialog.getByRole('button',{name:'Apply'}));expect(payload().filters).toMatchObject({countries:[],include_unknown_country:true});
    unmount();const submit=vi.fn();render(<Harness disabled submit={submit}/>);await user.click(screen.getByRole('button',{name:/Content languages/}));await user.click(screen.getByRole('button',{name:'Find creators'}));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(screen.getByRole('checkbox',{name:'YouTube'})).toBeDisabled();expect(submit).not.toHaveBeenCalled();
  });
  it('applies the seven inclusive follower presets as a union',async()=>{
    const user=userEvent.setup();render(<Harness/>);await user.click(screen.getByRole('button',{name:/Followers/}));const dialog=within(screen.getByRole('dialog'));
    for(const label of ['0–999','1,000–9,999','10,000–49,999','50,000–99,999','100,000–499,999','500,000–999,999','1,000,000+'])await user.click(dialog.getByRole('checkbox',{name:label}));
    await user.click(dialog.getByRole('button',{name:'Apply'}));
    expect(payload().filters).toMatchObject({follower_ranges:[{minimum:0,maximum:999},{minimum:1000,maximum:9999},{minimum:10000,maximum:49999},{minimum:50000,maximum:99999},{minimum:100000,maximum:499999},{minimum:500000,maximum:999999},{minimum:1000000,maximum:null}],include_unknown_followers:false});
  });
  it('preserves unknown between concrete follower modes, resets it through Any and validates custom endpoints',async()=>{
    const user=userEvent.setup();render(<Harness/>);await user.click(screen.getByRole('button',{name:/Followers/}));const dialog=within(screen.getByRole('dialog'));
    await user.click(dialog.getByRole('checkbox',{name:'0–999'}));await user.click(dialog.getByRole('checkbox',{name:'Include unknown follower counts'}));
    await user.click(dialog.getByRole('radio',{name:'Custom range'}));expect(dialog.getByRole('checkbox',{name:'Include unknown follower counts'})).toBeChecked();
    await user.click(dialog.getByRole('radio',{name:'Any'}));await user.click(dialog.getByRole('radio',{name:'Custom range'}));expect(dialog.getByRole('checkbox',{name:'Include unknown follower counts'})).not.toBeChecked();
    expect(dialog.getByRole('button',{name:'Apply'})).toBeDisabled();
    await user.type(dialog.getByLabelText('Minimum followers'),'10');await user.type(dialog.getByLabelText('Maximum followers'),'9');expect(dialog.getByRole('button',{name:'Apply'})).toBeDisabled();
    await user.clear(dialog.getByLabelText('Minimum followers'));await user.clear(dialog.getByLabelText('Maximum followers'));await user.type(dialog.getByLabelText('Maximum followers'),'0');await user.click(dialog.getByRole('button',{name:'Apply'}));
    expect(payload().filters?.follower_ranges).toEqual([{minimum:null,maximum:0}]);
  });
  it('keeps keywords literal, removable and bounded without submitting pending chip text',async()=>{
    const user=userEvent.setup(),submit=vi.fn();render(<Harness submit={submit}/>);
    await user.type(screen.getByLabelText('Content keywords'),'cozy games{Enter}');expect(payload().keywords).toEqual(['cozy games']);
    await user.type(screen.getByLabelText('Content keywords'),'story rich');await user.click(screen.getByRole('button',{name:'Find creators'}));expect(submit).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button',{name:'Add keyword'}));await user.click(screen.getByRole('button',{name:'Remove keyword cozy games'}));
    await user.selectOptions(screen.getByLabelText('Business email'),'available');await user.click(screen.getByRole('button',{name:'Find creators'}));expect(submit).toHaveBeenCalledTimes(1);
    expect(payload().filters?.contact).toBe('available');expect(payload().keywords).toEqual(['story rich']);
  });
});
