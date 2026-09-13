// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CreatorClient } from '../src/main/creator-client';
import { CreatorWorks } from '../src/renderer/components/creators/CreatorWorks';
import { InlineEvidenceEditor, type InlineEvidenceProps } from '../src/renderer/components/match/InlineEvidenceEditor';
import { metadataWorkFixture } from './outreach-observation-fixture';
import { preparationFixture } from './outreach-fixtures';
import { draftValues } from './drafts-fixtures';
afterEach(cleanup);
function fixture(){
  const work=metadataWorkFixture();
  const client=new CreatorClient(async request=>({items:[work],total:1,offset:0,limit:Number(('query' in request ? request.query?.limit : undefined)??50)}));
  const creators={works:async(input:Parameters<CreatorClient['works']>[0])=>({ok:true as const,data:await client.works(input)})};
  const selection=preparationFixture({creator_id:work.creator_id,works:[{...work,relation:'related_content',evidence_status:'metadata_only'}]});
  return {work,selection,api:{creators,outreach:{selection:vi.fn(async()=>({ok:true as const,data:selection}))},openExternal:vi.fn()}};
}
it('renders the Works list through the actual client decoder with metadata-only sources',async()=>{
  const f=fixture(),onEdit=vi.fn();
  render(<CreatorWorks api={f.api as never} creatorId={f.work.creator_id} identityRevision={1} active onEdit={onEdit}/>);
  expect(await screen.findByRole('heading',{name:'Station review'})).toBeVisible();
  expect(screen.queryByText(/unsupported Creator response/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Edit Station review'}));
  expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({base:expect.objectContaining({evidence_excerpt:null,verification_notes:null})}));
});
it('loads Edit personalization work evidence without turning metadata suggestions into viewing notes',async()=>{
  const f=fixture(),save=vi.fn(async()=>true);
  const props:InlineEvidenceProps={api:f.api as never,scope:{activityId:f.selection.activity_id,selectionId:f.selection.id,creatorId:f.work.creator_id},
    draftId:'metadata-draft',workId:f.work.id,active:true,disabled:false,values:draftValues,valuesValid:true,connectionEpoch:0,
    onPreserve:save,onSaved:vi.fn(),onBusy:vi.fn(),onDirty:vi.fn(),onOpenWork:vi.fn()};
  render(<InlineEvidenceEditor {...props}/>);
  expect(await screen.findByRole('combobox',{name:'Source work'})).toHaveValue(f.work.id);
  expect(screen.getByRole('textbox',{name:'Evidence excerpt'})).toHaveValue('');
  expect(screen.getByRole('textbox',{name:'Verification notes'})).toHaveValue('');
  expect(screen.getByRole('textbox',{name:'Source URL'})).toHaveValue(f.work.source_url);
  expect(save).not.toHaveBeenCalled();expect(f.selection.sender_watched).toBe(false);
});
