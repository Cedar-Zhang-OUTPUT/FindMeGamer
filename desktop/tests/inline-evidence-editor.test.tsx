// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InlineEvidenceEditor, type InlineEvidenceProps } from '../src/renderer/components/match/InlineEvidenceEditor';
import { preparationFixture } from './outreach-fixtures';
import { workFixture } from './creator-fixtures';
import { draftValues } from './drafts-fixtures';
afterEach(cleanup);
function fixture() {
  let work = workFixture(); const selection = preparationFixture({ creator_id: work.creator_id, works: [] });
  const api = { creators: { works: vi.fn(async () => ({ ok: true, data: { items: [work], total: 1, offset: 0, limit: 100 } })),
    updateWork: vi.fn(async ({data}: {data:object}) => { work = {...work,...data,revision:work.revision+1}; return { ok: true, data: work }; }) },
    outreach: { selection: vi.fn(async () => ({ok:true,data:selection})), update: vi.fn(async()=>({ok:true,data:{...selection,revision:selection.revision+1,works:[work]}})) } };
  const props: InlineEvidenceProps = { api: api as unknown as InlineEvidenceProps['api'], scope: { activityId: selection.activity_id, selectionId: selection.id, creatorId: work.creator_id },
    draftId: 'draft1', workId: null, active: true, disabled: false, values: {...draftValues, observation: 'Unsaved wording'}, valuesValid: true, connectionEpoch: 0,
    onPreserve: vi.fn(async()=>true), onSaved: vi.fn(), onBusy: vi.fn(), onDirty: vi.fn(), onOpenWork: vi.fn() };
  return { api, props, work };
}
describe('inline work evidence UI', () => {
  it('offers existing work without navigation and sends the exact unsaved email wording after evidence saves', async () => {
    const f=fixture(); render(<InlineEvidenceEditor {...f.props}/>);
    fireEvent.change(await screen.findByRole('combobox',{name:'Source work'}),{target:{value:f.work.id}});
    fireEvent.change(screen.getByRole('textbox',{name:'Evidence excerpt'}),{target:{value:'Observed scene'}});
    fireEvent.change(screen.getByRole('textbox',{name:'Verification notes'}),{target:{value:'Checked the source'}});
    fireEvent.click(screen.getByRole('button',{name:'Save evidence & draft'}));
    await waitFor(()=>expect(f.props.onSaved).toHaveBeenCalledWith('draft1'));
    expect(f.props.onPreserve).toHaveBeenCalledWith('draft1',f.props.values,expect.objectContaining({stage:'draft'}));
    expect(f.props.onOpenWork).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox',{name:'Evidence excerpt'})).toHaveValue('Observed scene');
  });
  it('retains evidence after a rejected save and does not refresh a draft', async () => {
    const f=fixture(); f.api.creators.updateWork.mockRejectedValueOnce({code:'conflict'}); render(<InlineEvidenceEditor {...f.props}/>);
    fireEvent.change(await screen.findByRole('combobox',{name:'Source work'}),{target:{value:f.work.id}});
    fireEvent.change(screen.getByRole('textbox',{name:'Evidence excerpt'}),{target:{value:'Keep this'}});
    fireEvent.click(screen.getByRole('button',{name:'Save evidence & draft'}));
    expect(await screen.findByText(/Save stopped/)).toBeVisible();
    expect(screen.getByRole('textbox',{name:'Evidence excerpt'})).toHaveValue('Keep this');
    expect(f.props.onPreserve).not.toHaveBeenCalled();
  });
  it('retains separate evidence input when switching between draft people', async()=>{
    const f=fixture(); const view=render(<InlineEvidenceEditor {...f.props}/>);
    fireEvent.change(await screen.findByRole('combobox',{name:'Source work'}),{target:{value:f.work.id}});
    fireEvent.change(screen.getByRole('textbox',{name:'Evidence excerpt'}),{target:{value:'First person input'}});
    view.rerender(<InlineEvidenceEditor {...f.props} draftId="draft2" workId={f.work.id}/>);
    await waitFor(()=>expect(screen.getByRole('textbox',{name:'Evidence excerpt'})).toHaveValue(''));
    view.rerender(<InlineEvidenceEditor {...f.props}/>);
    expect(screen.getByRole('textbox',{name:'Evidence excerpt'})).toHaveValue('First person input');
  });
  it('keeps rejected input editable and blocks cached input after credential changes',async()=>{
    const f=fixture(); f.api.creators.updateWork.mockRejectedValueOnce({code:'request_invalid'});
    const view=render(<InlineEvidenceEditor {...f.props}/>);
    fireEvent.change(await screen.findByRole('combobox',{name:'Source work'}),{target:{value:f.work.id}});
    fireEvent.change(screen.getByRole('textbox',{name:'Evidence excerpt'}),{target:{value:'Rejected input'}});
    fireEvent.click(screen.getByRole('button',{name:'Save evidence & draft'}));
    await screen.findByText(/Save stopped/);
    expect(screen.getByRole('textbox',{name:'Evidence excerpt'})).toBeEnabled();
    view.rerender(<InlineEvidenceEditor {...f.props} connectionEpoch={1}/>);
    expect(screen.getByRole('textbox',{name:'Evidence excerpt'})).toHaveValue('Rejected input');
    expect(screen.getByRole('button',{name:'Save evidence & draft'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'Reload evidence'})).toBeDisabled();
  });
});
