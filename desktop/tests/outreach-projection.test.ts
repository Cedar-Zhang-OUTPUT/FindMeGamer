import {expect,it,vi} from 'vitest';
import type {Preparation} from '../src/shared/outreach';
import {candidateFixture,CANDIDATE_ID} from './match-fixtures';
import {candidateSelection,visibleSelections,excludedSelections,readCandidateMembership} from '../src/renderer/components/match/outreachProjection';
import {preparationFixture} from './outreach-fixtures';
const selected=(id='selection-one',patch:Partial<Preparation>={}):Preparation=>preparationFixture({id,revision:2,...patch});
it('uses explicit Activity identity, not model selected=false or cross-query candidate ID',()=>{
  const current=candidateFixture(),member=selected();
  expect(candidateSelection(current,[member])).toBe(member);
  expect(candidateSelection({...current,selected:false},[])).toBeUndefined();
  expect(candidateSelection({...current,identity_revision:2},[member])).toBeUndefined();
  expect(candidateSelection({...current,platform:'x'},[member])).toBeUndefined();
  expect(candidateSelection(current,[selected('old',{active:false})])).toBeUndefined();
});
it('cancels only the previous visible projection, never other selected people or late arrivals',()=>{
  const a=candidateFixture(),b={...a,id:'b',account_id:'B'},late={...a,id:'late',account_id:'Late'};
  const one=selected(),two=selected('selection-two',{identity:{platform:'youtube',account_id:'B',revision:1}}),other=selected('other',{identity:{platform:'youtube',account_id:'Other',revision:1}});
  const previous=visibleSelections([a,b],[one,two,other]);
  expect(previous.map(value=>value.id)).toEqual(['selection-one','selection-two']);
  expect(excludedSelections(previous,[b,late])).toEqual([{selection_id:'selection-one',expected_revision:2}]);
  expect(excludedSelections(previous,[b,a])).toEqual([]);
});
it('reads every server-filtered page before deciding exclusion',async()=>{
  const rows=Array.from({length:101},(_,i)=>({...candidateFixture(),id:String(i),account_id:String(i)}));
  const read=vi.fn(async input=>({ok:true as const,data:{items:rows.slice(input.offset,input.offset+100),offset:input.offset,limit:100,total:101}}));
  expect((await readCandidateMembership({candidates:read},'query',{evidence:'current_game',sort:'followers'})).map(value=>value.id)).toEqual(rows.map(value=>value.id));
  expect(read.mock.calls.map(([input])=>input)).toEqual([
    {queryId:'query',evidence:'current_game',sort:'added',offset:0,limit:100},
    {queryId:'query',evidence:'current_game',sort:'added',offset:100,limit:100},
  ]);
});
it('does not turn failed or inconsistent membership reads into an empty match',async()=>{
  const fail=vi.fn(async()=>({ok:false as const,error:{code:'network_error',message:'Offline',retryable:true}}));
  await expect(readCandidateMembership({candidates:fail},CANDIDATE_ID,{evidence:'none',sort:'relevance'})).rejects.toMatchObject({code:'network_error'});
  const broken=vi.fn(async()=>({ok:true as const,data:{items:[],total:1,offset:0,limit:100}}));
  await expect(readCandidateMembership({candidates:broken},CANDIDATE_ID,{evidence:'none',sort:'relevance'})).rejects.toMatchObject({code:'membership_changed'});
});
