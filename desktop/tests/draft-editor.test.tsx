// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { fireEvent, render as renderRaw, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DraftEditor, type DraftEditorProps } from '../src/renderer/components/match/DraftEditor';
import { draftFixture, draftValues, builtinTemplate, templateVersion } from './drafts-fixtures';

afterEach(cleanup);
// Existing field-editing cases explicitly open the now on-demand editor.
const render=(...args:Parameters<typeof renderRaw>)=>{const view=renderRaw(...args);const button=screen.queryByRole('button',{name:'Edit personalization'});if(button)fireEvent.click(button);return view;};
function props(patch: Partial<DraftEditorProps> = {}): DraftEditorProps {
  return { draft: draftFixture({ status: 'succeeded', values: { ...draftValues }, rendered: { subject: 'Saved subject', html: '<p>Saved mail</p>', text: 'Saved mail', fixed_hash: builtinTemplate.fixed_hash } }),
    busy: false, current: true, onSave: vi.fn(async () => true), onRefresh: vi.fn(), onRetry: vi.fn(), onOpenSource: vi.fn(), onDirtyChange: vi.fn(), ...patch };
}
const change = (label: string, value: string) => fireEvent.change(screen.getByRole('textbox', { name: label }), { target: { value } });

describe('source-bound draft editor', () => {
  it.each(['needs_repair','failed'] as const)('shows the actual fixed template rather than a loading skeleton for %s',status=>{
    const p=props({draft:draftFixture({status,rendered:null,values:null,missing_fields:['public_name_unconfirmed','reference_missing','observation_evidence_missing']}),previewTemplate:templateVersion});
    render(<DraftEditor {...p}/>);
    const preview=screen.getByTitle('Template preview — not ready to send');
    expect(preview).toHaveAttribute('srcdoc',expect.stringContaining(builtinTemplate.fixed_fragments[0]));
    expect(preview).toHaveAttribute('srcdoc',expect.stringContaining('Ari'));
    expect(preview).toHaveAttribute('srcdoc',expect.stringContaining('Observation · unfinished'));
    expect(preview).toHaveAttribute('srcdoc',expect.stringContaining('Fixture Channel'));
    expect(preview).not.toHaveAttribute('srcdoc',expect.stringContaining('connected the two scenes.'));
    expect(screen.getByRole('button',{name:'Save changes'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'Edit public name source'})).toBeEnabled();
    expect(document.querySelector('.draft-preview-empty')).toBeNull();
  });
  it.each(['pending','running'] as const)('shows truthful %s status and no fake indefinite skeleton',status=>{
    render(<DraftEditor {...props({draft:draftFixture({status}),previewTemplate:templateVersion})}/>);
    expect(screen.getByText(status==='pending'?'Queued':'Generating…')).toBeVisible();
    expect(screen.getByTitle('Template preview — not ready to send')).toBeVisible();expect(document.querySelector('.draft-preview-empty')).toBeNull();
  });
  it('distinguishes a pending template read, its failure, and saved rendered mail',()=>{
    const p=props({draft:draftFixture({status:'needs_repair'}),previewLoading:true});const view=render(<DraftEditor {...p}/>);
    expect(screen.getByText('Loading original template…')).toBeVisible();
    const reload=vi.fn();view.rerender(<DraftEditor {...p} previewLoading={false} previewError={{code:'access_denied',message:'Template access denied',retryable:false}} onReloadPreview={reload}/>);
    expect(screen.getByText('Template access denied')).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'Reload original template'}));expect(reload).toHaveBeenCalledOnce();
    view.rerender(<DraftEditor {...props()} previewTemplate={templateVersion}/>);expect(screen.getByTitle('Saved email preview')).toBeVisible();expect(screen.queryByTitle('Template preview — not ready to send')).not.toBeInTheDocument();
  });
  it('starts with the email focus and keeps an opened dirty editor expanded',()=>{
    renderRaw(<DraftEditor {...props()}/>);
    expect(screen.queryByRole('textbox',{name:'Observation'})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Edit personalization'}));change('Observation','My pending observation.');
    expect(screen.getByRole('button',{name:'Edit personalization'})).toHaveAttribute('aria-expanded','true');
    expect(screen.getByRole('button',{name:'Edit personalization'})).toBeDisabled();expect(screen.getByRole('textbox',{name:'Observation'})).toHaveValue('My pending observation.');
  });
  it('offers a new current-template flow instead of repeatedly refreshing immutable text',async()=>{
    const onUseCurrentTemplate=vi.fn(),p=props({draft:draftFixture({status:'needs_repair',source_changed:true,missing_fields:['template_context_changed']}),onUseCurrentTemplate});render(<DraftEditor {...p}/>);
    expect(screen.queryByRole('button',{name:'Refresh sources'})).not.toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'Use current template'}));expect(onUseCurrentTemplate).toHaveBeenCalledOnce();expect(p.onRefresh).not.toHaveBeenCalled();expect(p.onSave).not.toHaveBeenCalled();
  });
  it('shows the saved email sandbox and four bound fields without authorizing any write on mount', () => {
    const p = props(); render(<DraftEditor {...p} />);
    expect(screen.getByRole('textbox', { name: 'Public name' })).toHaveValue('Ari');
    expect(screen.getByRole('textbox', { name: 'Channel name' })).toHaveValue('Fixture Channel');
    expect(screen.getByRole('textbox', { name: 'Referenced work' })).toHaveValue('Fixture Story');
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('connected the two scenes.');
    expect(screen.getByTitle('Saved email preview')).toHaveAttribute('sandbox', '');
    expect(screen.getByTitle('Saved email preview')).toHaveAttribute('srcdoc', expect.stringContaining('Saved mail'));
    expect(p.onSave).not.toHaveBeenCalled(); expect(p.onRefresh).not.toHaveBeenCalled(); expect(p.onRetry).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /^send$/i })).not.toBeInTheDocument();
  });

  it('permits manual save without email and preserves legitimate brackets in the observation', async () => {
    const p = props(); render(<DraftEditor {...p} />);
    change('Observation', 'noticed the [optional] path.');
    expect(screen.getByText('Saved preview')).toBeInTheDocument();
    expect(screen.getByTitle('Saved email preview')).toHaveAttribute('srcdoc', expect.stringContaining('Saved mail'));
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(p.onSave).toHaveBeenCalledWith({ ...draftValues, observation: 'noticed the [optional] path.' });
    expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
  });

  it('uses reusable prefill values without requiring source confirmation or creating a human endorsement', () => {
    const draft = draftFixture();
    draft.input.public_name_confirmed = false;
    draft.input.prefill_values = { firstName: 'Hello channel', channelName: 'Fixture Channel', reference: 'A stored video', observation: '' };
    draft.missing_fields = ['public_name_unconfirmed', 'observation_evidence_missing'];
    const p = props({ draft }); render(<DraftEditor {...p} />);
    expect(screen.getByRole('textbox', { name: 'Public name' })).toHaveValue('Hello channel');
    expect(screen.getByRole('textbox', { name: 'Referenced work' })).toHaveValue('A stored video');
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('');
    expect(p.onSave).not.toHaveBeenCalled();
    expect(screen.getByText('Confirmations needed')).toBeInTheDocument();
  });

  it('pre-fills the three recorded sources for a draft without generated values', async () => {
    const p = props({ draft: draftFixture() }); render(<DraftEditor {...p} />);
    expect(screen.getByRole('textbox', { name: 'Public name' })).toHaveValue('Ari');
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('');
    expect(screen.queryByTitle('Saved email preview')).not.toBeInTheDocument();
    change('Observation', 'connected the scenes.');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(p.onSave).toHaveBeenCalledWith({ ...draftValues, observation: 'connected the scenes.' });
  });

  it.each(['Channel name', 'Referenced work'])('allows a per-draft %s override while keeping the shared source separate', label => {
    render(<DraftEditor {...props()} />); change(label, 'Personalized replacement');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    expect(screen.getByRole('button', { name: `Edit ${label.toLowerCase()} source` })).toBeEnabled();
  });

  it('does not carry model-charge acknowledgement into a newer failed attempt', async () => {
    const p = props({ draft: draftFixture({ status: 'failed', error_code: 'draft_outcome_unknown' }) });
    const view = render(<DraftEditor {...p} />);
    await userEvent.click(screen.getByRole('checkbox', { name: /another model call may incur a charge/i }));
    expect(screen.getByRole('button', { name: 'Retry generation' })).toBeEnabled();
    view.rerender(<DraftEditor {...p} draft={{ ...p.draft, revision: 1 }} />);
    expect(screen.getByRole('button', { name: 'Retry generation' })).toBeDisabled();
  });

  it('allows a public-name override without changing its recorded source', async () => {
    const p = props(); render(<DraftEditor {...p} />); change('Public name', 'Arianna');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(p.onSave).toHaveBeenCalledWith({ ...draftValues, firstName: 'Arianna' });
    expect(p.draft.input.public_name).toBe('Ari');
    expect(p.onOpenSource).not.toHaveBeenCalled();
  });

  it.each([''])('allows saving an unfinished first-name value %j', value => {
    render(<DraftEditor {...props()} />); change('Public name', value);
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    expect(screen.getByRole('textbox', { name: 'Public name' })).toHaveAttribute('aria-invalid', 'false');
  });

  it('saves an unfinished observation without requiring final punctuation', () => {
    render(<DraftEditor {...props()} />); change('Observation', 'A detail to finish later');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
  });

  it.each(['<b>Injected.</b>', '[specific observation].', 'Line\nbreak.', 'x'.repeat(601) + '.'])('blocks invalid observation %j', value => {
    render(<DraftEditor {...props()} />); change('Observation', value);
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('keeps source editors available without blocking draft persistence on missing evidence', async () => {
    const p = props({ draft: draftFixture({ status: 'needs_repair', values: draftValues, missing_fields: ['observation_evidence_missing', 'email_not_selected'] }) });
    render(<DraftEditor {...p} />); change('Observation', 'Different detail.');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Edit public name source' }));
    await userEvent.click(screen.getByRole('button', { name: 'Edit referenced work source' }));
    await userEvent.click(screen.getByRole('button', { name: 'Edit contact source' }));
    expect(p.onOpenSource).toHaveBeenNthCalledWith(1, 'overview'); expect(p.onOpenSource).toHaveBeenNthCalledWith(2, 'works'); expect(p.onOpenSource).toHaveBeenNthCalledWith(3, 'contacts');
  });

  it('retains edits across hidden detours and polling; explicit loading is required after revision or context changes', async () => {
    const p = props(); const view = render(<DraftEditor {...p} />); change('Observation', 'My unsaved detail.');
    view.rerender(<DraftEditor {...p} current={false} />);
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('My unsaved detail.');
    const updated = { ...p.draft, revision: 1, context_token: 'b'.repeat(64), values: { ...draftValues, observation: 'New saved detail.' } };
    view.rerender(<DraftEditor {...p} draft={updated} />);
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('My unsaved detail.');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    expect(screen.getByText(/draft changed while you were editing/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Load current values' }));
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('New saved detail.');
    expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
  });

  it('retains one person’s dirty values when the selected person changes and returns', () => {
    const p = props(), view = render(<DraftEditor {...p} />); change('Observation', 'First person edit.');
    view.rerender(<DraftEditor {...p} draft={{ ...p.draft, id: 'other-person' }} />);
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue(draftValues.observation);
    view.rerender(<DraftEditor {...p} />);
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('First person edit.');
  });

  it('preserves failed saves and suppresses a double submit during an unresolved save', async () => {
    let finish!: (saved: boolean) => void;
    const p = props({ onSave: vi.fn(() => new Promise<boolean>(resolve => { finish = resolve; })) });
    render(<DraftEditor {...p} />); change('Observation', 'Keep this change.');
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' })); fireEvent.click(screen.getByRole('button', { name: 'Saving changes…' }));
    expect(p.onSave).toHaveBeenCalledTimes(1); finish(false);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled());
    expect(screen.getByRole('textbox', { name: 'Observation' })).toHaveValue('Keep this change.');
    expect(screen.getByRole('alert')).toHaveTextContent(/not saved/i);
  });

  it('requires explicit refresh confirmation about clearing values and human confirmations', async () => {
    const p = props({ draft: { ...props().draft, source_changed: true } }); render(<DraftEditor {...p} />);
    await userEvent.click(screen.getByRole('button', { name: 'Refresh sources' }));
    expect(p.onRefresh).not.toHaveBeenCalled(); expect(screen.getByText(/keeps saved overrides, discards unsaved edits, and clears confirmations/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Keep current draft' })); expect(p.onRefresh).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Refresh sources' }));
    await userEvent.click(screen.getByRole('button', { name: 'Refresh and keep overrides' })); expect(p.onRefresh).toHaveBeenCalledTimes(1);
  });

  it('requires possible repeated model-charge acknowledgement for an unknown failed generation', async () => {
    const p = props({ draft: draftFixture({ status: 'failed', error_code: 'draft_outcome_unknown' }) }); render(<DraftEditor {...p} />);
    expect(screen.getByRole('button', { name: 'Retry generation' })).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox', { name: /another model call may incur a charge/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Retry generation' })); expect(p.onRetry).toHaveBeenCalledTimes(1);
  });

  it.each(['pending', 'running', 'needs_repair', 'succeeded'] as const)('never offers retry for %s state', status => {
    render(<DraftEditor {...props({ draft: draftFixture({ status, error_code: 'draft_outcome_unknown' }) })} />);
    expect(screen.queryByRole('button', { name: 'Retry generation' })).not.toBeInTheDocument();
  });

  it('gates writes while inactive or busy and reports sender facts only as a read-only state', () => {
    const p = props({ current: false, draft: { ...props().draft, sender_facts_valid: true } }); const view = render(<DraftEditor {...p} />);
    expect(screen.getByRole('textbox', { name: 'Observation' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Refresh sources' })).toBeDisabled();
    expect(screen.getByText('Confirmations saved')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    view.rerender(<DraftEditor {...p} current busy />); expect(screen.getByRole('button', { name: 'Refresh sources' })).toBeDisabled();
  });
});

it('does not flag untouched queued fields or repeat guidance before the user edits',()=>{
  render(<DraftEditor {...props({draft:draftFixture()})}/>);
  expect(screen.queryByText(/Use filled single-line text/)).not.toBeInTheDocument();
  expect(screen.queryByText(/preview will appear/)).not.toBeInTheDocument();
});
it('clears only the explicitly refreshed person’s local edits after an acknowledged refresh',async()=>{
  const p=props({onRefresh:vi.fn(async()=>true)}),view=render(<DraftEditor {...p}/>);
  change('Observation','Unsaved before refresh.');
  await userEvent.click(screen.getByRole('button',{name:'Refresh sources'}));
  await userEvent.click(screen.getByRole('button',{name:'Refresh and keep overrides'}));
  view.rerender(<DraftEditor {...p} draft={{...p.draft,revision:1,values:null,rendered:null,status:'pending'}}/>);
  expect(screen.getByRole('textbox',{name:'Observation'})).toHaveValue('');expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
});
