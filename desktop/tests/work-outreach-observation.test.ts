import { describe, expect, it, vi } from 'vitest';
import { CreatorClient } from '../src/main/creator-client';
import { decodeWork } from '../src/main/creator-validation';
import { decodePreparation, decodeRecipientBatch } from '../src/main/outreach-validation';
import { metadataObservation, metadataWorkFixture } from './outreach-observation-fixture';
import { preparationFixture, recipientBatchFixture } from './outreach-fixtures';

describe('read-only work outreach observation compatibility', () => {
  it('decodes the real producer shape through Works, preparation and frozen batch consumers',async()=>{
    const work=metadataWorkFixture();
    const request=vi.fn(async()=>({items:[work],total:1,offset:0,limit:50}));
    const page=await new CreatorClient(request).works({creatorId:work.creator_id});
    expect(page.items[0].source_fields.outreach_observation).toEqual(metadataObservation);
    expect(page.items[0].evidence_excerpt).toBeNull();expect(page.items[0].verification_notes).toBeNull();
    const preparation=preparationFixture({creator_id:work.creator_id,works:[{...work,relation:'related_content',evidence_status:'metadata_only'}]});
    expect(decodePreparation(preparation).sender_watched).toBe(false);
    const batch=recipientBatchFixture();
    batch.recipients[0].snapshot=preparation;batch.recipients[0].preparation=preparation;
    expect(decodeRecipientBatch(batch).recipients[0].snapshot.works[0].source_fields.outreach_observation).toEqual(metadataObservation);
  });
  it('preserves historical absence, empty title metadata and nullable URLs',()=>{
    const work=metadataWorkFixture();delete (work.source_fields as Record<string,unknown>).outreach_observation;
    expect(decodeWork(work,work.creator_id).source_fields).not.toHaveProperty('outreach_observation');
    work.source_fields.outreach_observation={...metadataObservation,text:'',excerpt:'',source_field:'title',source_url:null} as never;
    expect(decodeWork(work,work.creator_id).source_fields.outreach_observation).toEqual(work.source_fields.outreach_observation);
  });
  it.each([null,[],{}, {...metadataObservation,extra:'unexpected'}, {...metadataObservation,evidence_kind:'manual_note'},
    {...metadataObservation,source_field:'watched_video'}, {...metadataObservation,text:'x'.repeat(601)},
    {...metadataObservation,excerpt:'x'.repeat(351)}, {...metadataObservation,source_url:'javascript:alert(1)'},
    {...metadataObservation,source_url:'https://example.test/'+ 'x'.repeat(2048)}, {...metadataObservation,excerpt:42}
  ])('rejects malformed or oversized metadata %#',outreach_observation=>{
    const work=metadataWorkFixture();
    expect(()=>decodeWork({...work,source_fields:{...work.source_fields,outreach_observation}},work.creator_id)).toThrow();
  });
  it('never admits provenance into editable fields, overrides or reset fields',async()=>{
    const work=metadataWorkFixture(),request=vi.fn(),client=new CreatorClient(request);
    for(const data of [
      {expected_revision:1,outreach_observation:metadataObservation},
      {expected_revision:1,source_fields:{outreach_observation:metadataObservation}},
      {expected_revision:1,reset_fields:['outreach_observation']},
    ])await expect(client.updateWork({creatorId:work.creator_id,workId:work.id,data:data as never})).rejects.toMatchObject({code:'request_invalid'});
    expect(request).not.toHaveBeenCalled();
    expect(()=>decodeWork({...work,manual_overrides:{outreach_observation:metadataObservation}},work.creator_id)).toThrow();
  });
});
