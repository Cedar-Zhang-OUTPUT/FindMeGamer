import {expect,it,vi} from 'vitest';
import {emptySelectionDraft,mergeSelectionRead,setDesiredSelection,prepareLocalSelection,type LocalPrepareState} from '../src/renderer/components/match/localSelectionPrepare';
import {preparationFixture,recipientBatchFixture} from './outreach-fixtures';
import {settingsBridgeMock,ok} from './settings-fixtures';

const a=preparationFixture(),b=preparationFixture({id:'selection-b',candidate_id:'candidate-b',creator_id:'creator-b'});
function draft(){return mergeSelectionRead(emptySelectionDraft('workspace-a',a.activity_id),[a,b]);}
function ports(initial=[a,b]){
 const api=settingsBridgeMock().outreach;let rows=initial;
 vi.mocked(api.selections).mockImplementation(async()=>ok({items:rows,total:rows.length,offset:0,limit:200}));
 vi.mocked(api.bulk).mockImplementation(async input=>{rows=rows.map(p=>input.data.cancel_selections?.some(c=>c.selection_id===p.id)?{...p,active:false,revision:p.revision+1}:p);return ok({added_selection_ids:[],cancelled_selection_ids:input.data.cancel_selections?.map(c=>c.selection_id)??[]});});
 vi.mocked(api.freeze).mockImplementation(async input=>ok(recipientBatchFixture({request_id:input.data.request_id,recipient_count:input.data.recipients.length,recipients:input.data.recipients.map(c=>{const p=rows.find(p=>p.id===c.selection_id)!;return {id:'recipient-'+p.id,selection_id:p.id,snapshot:p,preparation:p,source_changed:false,current_missing_fields:[]};})})));
 const saved:LocalPrepareState[]=[];const persist=vi.fn(async(state:LocalPrepareState)=>{saved.push(structuredClone(state));});
 return {api,persist,saved,setRows:(value:typeof rows)=>{rows=value;}};
}
it('keeps toggles local, query-independent and immune to background reselection',()=>{
 const api=settingsBridgeMock().outreach;let d=draft();
 for(let n=0;n<50;n++)d=setDesiredSelection(d,{candidateId:a.candidate_id,creatorId:a.creator_id,identity:a.identity,name:a.name,queryId:'query-one'},n%2===0);
 d=mergeSelectionRead(d,[a,b]);
 expect(d.desired).toEqual([b.candidate_id]);expect(d.removed).toContain(a.candidate_id);
 expect(api.bulk).not.toHaveBeenCalled();expect(api.add).not.toHaveBeenCalled();expect(api.cancel).not.toHaveBeenCalled();
 expect(JSON.parse(JSON.stringify(d))).toEqual(d);
 expect(emptySelectionDraft('workspace-b',a.activity_id).desired).toEqual([]);
});
it('persists each write intent first, sends one final bulk and freezes explicit ordered desired IDs',async()=>{
 const p=ports();const d=setDesiredSelection(draft(),{candidateId:a.candidate_id,creatorId:a.creator_id,identity:a.identity,name:a.name,queryId:'q'},false);
 const result=await prepareLocalSelection({stage:'ready',draft:d},p);
 expect(result.stage).toBe('done');expect(p.api.bulk).toHaveBeenCalledTimes(1);expect(p.api.bulk).toHaveBeenCalledWith(expect.objectContaining({data:{add_candidate_ids:[],cancel_selections:[{selection_id:a.id,expected_revision:a.revision}]}}));
 expect(result.draft.members[a.candidate_id].observed).toBeUndefined();expect(result.draft.removed).toContain(a.candidate_id);
 expect(result.draft.members[b.candidate_id].observed).toEqual({selectionId:b.id,revision:b.revision});
 expect(p.api.freeze).toHaveBeenCalledTimes(1);expect(vi.mocked(p.api.freeze).mock.calls[0][0].data.recipients.map(r=>r.selection_id)).toEqual([b.id]);
 expect(p.saved.some(s=>s.stage==='bulk_pending')).toBe(true);expect(p.saved.some(s=>s.stage==='freeze_pending')).toBe(true);
 expect(p.persist.mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(p.api.bulk).mock.invocationCallOrder[0]);
});
it('skips empty bulk and does not treat missing evidence as a blocker',async()=>{
 const incomplete=preparationFixture({public_name_confirmed:false,works:[],evaluation:null,missing_fields:['public_name'],freeze_ready:true});const p=ports([incomplete]);
 const d=mergeSelectionRead(emptySelectionDraft('scope',a.activity_id),[incomplete]);
 expect((await prepareLocalSelection({stage:'ready',draft:d},p)).stage).toBe('done');expect(p.api.bulk).not.toHaveBeenCalled();expect(p.api.update).not.toHaveBeenCalled();
});
it('retains exact bulk key and payload after a lost response and resumes without duplicate freeze',async()=>{
 const p=ports();const normal=vi.mocked(p.api.bulk).getMockImplementation()!;vi.mocked(p.api.bulk).mockImplementationOnce(async input=>{await normal(input);throw Error('lost');});
 const d=setDesiredSelection(draft(),{candidateId:a.candidate_id,creatorId:a.creator_id,identity:a.identity,name:a.name,queryId:'q'},false);
 const unknown=await prepareLocalSelection({stage:'ready',draft:d},p);expect(unknown.stage).toBe('bulk_pending');expect(p.api.freeze).not.toHaveBeenCalled();
 vi.mocked(p.api.bulk).mockResolvedValueOnce(ok({added_selection_ids:[],cancelled_selection_ids:[a.id]}));
 const resumed=await prepareLocalSelection(JSON.parse(JSON.stringify(unknown)),p);expect(resumed.stage).toBe('done');
 expect(vi.mocked(p.api.bulk).mock.calls[0][0]).toEqual(vi.mocked(p.api.bulk).mock.calls[1][0]);expect(p.api.freeze).toHaveBeenCalledTimes(1);
});
it('retains exact freeze identity and never replays bulk on freeze recovery',async()=>{
 const p=ports();vi.mocked(p.api.freeze).mockRejectedValueOnce(Error('lost'));
 const pending=await prepareLocalSelection({stage:'ready',draft:draft()},p);expect(pending.stage).toBe('freeze_pending');
 expect((await prepareLocalSelection(pending,p)).stage).toBe('done');expect(p.api.bulk).not.toHaveBeenCalled();expect(vi.mocked(p.api.freeze).mock.calls[0][0]).toEqual(vi.mocked(p.api.freeze).mock.calls[1][0]);
});
it.each(['deleted','identity','revision'] as const)('preserves local desired on %s conflict without writes',async kind=>{
 const changed=kind==='deleted'?[]:[kind==='identity'?{...a,identity_changed:true}:kind==='revision'?{...a,revision:a.revision+1}:a,b];
 const p=ports(changed),d=draft(),result=await prepareLocalSelection({stage:'ready',draft:d},p);
 expect(result.stage).toBe('conflict');expect(result.draft.desired).toEqual(d.desired);expect(p.api.bulk).not.toHaveBeenCalled();expect(p.api.freeze).not.toHaveBeenCalled();
});
it('does not dispatch when durable checkpoint persistence fails',async()=>{
 const p=ports();p.persist.mockRejectedValueOnce(Error('disk'));const result=await prepareLocalSelection({stage:'ready',draft:draft()},p);
 expect(result.stage).not.toBe('done');expect(p.api.bulk).not.toHaveBeenCalled();expect(p.api.freeze).not.toHaveBeenCalled();
});
it('preserves hidden selections while adding a locally selected candidate from another query',async()=>{
 const p=ports(),newPerson=preparationFixture({id:'selection-c',candidate_id:'candidate-c',creator_id:'creator-c'});
 const d=setDesiredSelection(draft(),{candidateId:newPerson.candidate_id,creatorId:newPerson.creator_id,identity:newPerson.identity,name:newPerson.name,queryId:'query-two'},true);
 vi.mocked(p.api.bulk).mockImplementationOnce(async input=>{expect(input.data).toEqual({add_candidate_ids:[newPerson.candidate_id],cancel_selections:[]});p.setRows([a,b,newPerson]);return ok({added_selection_ids:[newPerson.id],cancelled_selection_ids:[]});});
 const result=await prepareLocalSelection({stage:'ready',draft:d},p);expect(result.stage).toBe('done');
 expect(vi.mocked(p.api.freeze).mock.calls[0][0].data.recipients.map(r=>r.selection_id)).toEqual([a.id,b.id,newPerson.id]);
});
it('does not cancel a concurrently discovered activity selection that was never visible locally',async()=>{
 const p=ports([a,b,preparationFixture({id:'third',candidate_id:'third'})]);
 expect((await prepareLocalSelection({stage:'ready',draft:draft()},p)).stage).toBe('conflict');expect(p.api.bulk).not.toHaveBeenCalled();
});
it('retains committed selection stage and desired choices after a definite freeze conflict',async()=>{
 const p=ports(),d=setDesiredSelection(draft(),{candidateId:a.candidate_id,creatorId:a.creator_id,identity:a.identity,name:a.name,queryId:'q'},false);
 vi.mocked(p.api.freeze).mockResolvedValueOnce({ok:false,error:{code:'selection_context_changed',message:'Changed source',retryable:false}});
 const result=await prepareLocalSelection({stage:'ready',draft:d},p);expect(result.stage).toBe('conflict');expect(result.draft.desired).toEqual([b.candidate_id]);
 if(result.stage==='conflict')expect(result.previous?.stage).toBe('freeze_pending');
 expect(p.api.bulk).toHaveBeenCalledTimes(1);expect(p.api.cancel).not.toHaveBeenCalled();
 expect(await prepareLocalSelection(result,p)).toEqual(result);expect(p.api.freeze).toHaveBeenCalledTimes(1);
});
it('keeps an expired bulk outcome pending and requires recovery without issuing another key',async()=>{
 const p=ports(),d=draft(),input={activityId:a.activity_id,idempotencyKey:'stable',data:{add_candidate_ids:['candidate-c']}};
 const result=await prepareLocalSelection({stage:'bulk_pending',draft:d,input,startedAt:0},{...p,now:()=>86_400_001});
 expect(result.stage).toBe('bulk_pending');expect(result.error?.code).toBe('local_selection_retry_expired');expect(p.api.bulk).not.toHaveBeenCalled();expect(p.api.freeze).not.toHaveBeenCalled();
});
