import { useEffect, useId, useRef, useState } from 'react';
import type { DraftView, SlotValues, TemplateVersion } from '../../../shared/drafts';
import type { PublicError } from '../../../shared/bridge';
import { EmailDocument } from './EmailDocument';
import { SLOT_KEYS, SLOT_LABELS, templatePreviewHTML } from './templateText';
import './draftEditor.css';
export interface DraftEditorProps {
  draft: DraftView; busy: boolean; current: boolean;
  previewTemplate?:TemplateVersion|null;previewLoading?:boolean;previewError?:PublicError|null;onReloadPreview?():void;
  onSave(values: SlotValues): Promise<boolean>; onRefresh(): void|Promise<boolean>; onRetry(): void;
  onOpenSource(section: 'overview' | 'contacts' | 'works'): void; onDirtyChange?(dirty: boolean): void;onUseCurrentTemplate?():void;
}
type EditSession = { before: DraftView; initial: SlotValues; values: SlotValues };
const text = (value: unknown): string => typeof value === 'string' ? value : '';
function initialValues(draft: DraftView): SlotValues {
  return draft.values ? { ...draft.values } : { firstName: text(draft.input.public_name), channelName: text(draft.input.channel_name), reference: text(draft.input.reference), observation: '' };
}
function isDirty(session: EditSession): boolean { return SLOT_KEYS.some(key => session.initial[key] !== session.values[key]); }
function filled(value: string): boolean {
  return value.length > 0 && value.length <= 600 && value === value.trim() && !/[\x00-\x1f\x7f<>{}]/.test(value)
    && !/\[(?:first name|channel name|reference game\s*\/\s*video|unfilled[^\]]*|specific observation[^\]]*)\]/i.test(value);
}
const statusLabel: Record<DraftView['status'], string> = { pending: 'Queued', running: 'Generating…', succeeded: 'Draft complete', failed: 'Generation failed', needs_repair: 'Needs sources' };
const missingLabel: Record<string, string> = { not_selected: 'Selection removed', identity_changed: 'Account changed',
  public_name_unconfirmed: 'Confirm public name', channel_name_missing: 'Channel name', reference_missing: 'Referenced work', observation_evidence_missing: 'Recorded observation' };
const repairSource:Partial<Record<string,'overview'|'works'>>={public_name_unconfirmed:'overview',channel_name_missing:'overview',reference_missing:'works',observation_evidence_missing:'works'};

export function DraftEditor({ draft, busy, current, onSave, onRefresh, onRetry, onOpenSource, onDirtyChange,onUseCurrentTemplate,previewTemplate,previewLoading=false,previewError,onReloadPreview }: DraftEditorProps) {
  const prefix = useId();
  const [sessions, setSessions] = useState<Record<string, EditSession>>({});
  const [fieldsOpen,setFieldsOpen]=useState(false);
  const [saving, setSaving] = useState(false), pending = useRef(false), alive = useRef(true);
  const [error, setError] = useState<{ id: string; message: string } | null>(null);
  const [refreshFor, setRefreshFor] = useState<string | null>(null), [chargeFor, setChargeFor] = useState<string | null>(null);
  const session = sessions[draft.id];
  const dirty = !!session && isDirty(session);
  const before = dirty ? session.before : draft;
  const values = dirty ? session.values : initialValues(draft);
  const changed = dirty && (before.revision !== draft.revision || before.context_token !== draft.context_token
    || JSON.stringify(before.input) !== JSON.stringify(draft.input) || before.source_changed !== draft.source_changed);
  const disabled = busy || saving || !current;
  const sourceMissing = draft.missing_fields.filter(field => !field.startsWith('email_'));
  const templateChanged=sourceMissing.includes('template_context_changed');
  const unavailableSlots:Record<keyof SlotValues,boolean>={firstName:sourceMissing.includes('public_name_unconfirmed')||before.input.public_name_confirmed!==true,channelName:sourceMissing.includes('channel_name_missing'),reference:sourceMissing.includes('reference_missing'),observation:sourceMissing.includes('observation_evidence_missing')};
  const savedValues=initialValues(draft);
  const previewValues=Object.fromEntries(SLOT_KEYS.map(key=>[key,!draft.source_changed&&!unavailableSlots[key]&&text(savedValues[key]).trim()?text(savedValues[key]):`${SLOT_LABELS[key]} · unconfirmed`])) as unknown as SlotValues;
  const version = `${draft.id}:${draft.revision}:${draft.context_token}:${draft.status}`;
  const fieldErrors: Partial<Record<keyof SlotValues, string>> = {};
  for (const [key, source] of [['firstName', 'public_name'], ['channelName', 'channel_name'], ['reference', 'reference']] as const) {
    if (!filled(values[key]) || values[key] !== before.input[source]) fieldErrors[key] = `Must match the recorded ${SLOT_LABELS[key].toLowerCase()}. Edit its source to change it.`;
  }
  if (!filled(values.observation) || !values.observation.endsWith('.')) fieldErrors.observation = 'Use filled single-line text, up to 600 characters, ending with a period.';
  const canSave = dirty && !disabled && !changed && !draft.source_changed && !sourceMissing.length && !Object.keys(fieldErrors).length;
  const anyDirty = Object.values(sessions).some(isDirty);
  useEffect(() => { onDirtyChange?.(anyDirty); }, [anyDirty, onDirtyChange]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  function editValue(key: keyof SlotValues, value: string) {
    if (disabled) return;
    setError(null);
    setSessions(previous => {
      const old = previous[draft.id];
      const base = old && isDirty(old) ? old : { before: structuredClone(draft), initial: initialValues(draft), values: initialValues(draft) };
      return { ...previous, [draft.id]: { ...base, values: { ...base.values, [key]: value } } };
    });
  }
  function loadCurrent() {
    if (disabled) return;
    setSessions(previous => { const next = { ...previous }; delete next[draft.id]; return next; });
    setError(null);
  }
  async function save() {
    if (!canSave || pending.current) return;
    pending.current = true; setSaving(true); setError(null);
    const id = draft.id;
    try {
      const saved = await onSave({ ...values });
      if (!alive.current) return;
      if (saved) setSessions(previous => { const next = { ...previous }; delete next[id]; return next; });
      else setError({ id, message: 'Changes were not saved. Your edits are still here.' });
    } catch {
      if (alive.current) setError({ id, message: 'Changes were not saved. Read the current draft before trying again.' });
    } finally {
      pending.current = false;
      if (alive.current) setSaving(false);
    }
  }
  async function refreshSources(){
    if(disabled||pending.current)return;
    const id=draft.id;pending.current=true;setRefreshFor(null);
    try{if(await onRefresh()===true&&alive.current)setSessions(previous=>{const next={...previous};delete next[id];return next;});}
    catch{if(alive.current)setError({id,message:'Refresh not confirmed. Your edits are kept.'});}
    finally{pending.current=false;}
  }
  const unknownGeneration = draft.status === 'failed' && draft.error_code === 'draft_outcome_unknown';
  const sourceDetails = before.input.work;
  const work = sourceDetails && typeof sourceDetails === 'object' && !Array.isArray(sourceDetails) ? sourceDetails : {};

  return <section className="draft-editor" aria-label="Draft email editor">
    <header className="draft-editor-heading">
      <div><h3>{draft.rendered?.subject ?? previewTemplate?.subject ?? 'Personalization draft'}</h3><p role="status">{statusLabel[draft.status]}</p></div>
      <span className="draft-facts-state status-badge">{draft.sender_facts_valid ? 'Confirmations saved' : 'Confirmations needed'}</span>
    </header>
    {draft.source_changed && <p className="draft-editor-warning">{templateChanged?'Template changed · create new drafts':'Sources changed · refresh required'}</p>}
    {unknownGeneration && <p className="draft-editor-warning">Model outcome unknown · retry may repeat a charge</p>}
    {!!sourceMissing.length && <ul className="draft-missing-sources" aria-label="Sources to repair">{sourceMissing.map(field => <li key={field}>{repairSource[field]?<button type="button" disabled={disabled} onClick={()=>onOpenSource(repairSource[field]!)}>{missingLabel[field]} ↗</button>:missingLabel[field] ?? field.replaceAll('_',' ')}</li>)}</ul>}
    <div className="draft-editor-layout">
      <div className="draft-editor-mail">
        {dirty && <p className="draft-editing-note">Saved preview</p>}
        {draft.rendered ? <EmailDocument html={draft.rendered.html} title="Saved email preview" /> : <>
          {previewTemplate?<><p className="draft-editing-note">Original template · highlighted slots are not a send-ready email</p><EmailDocument html={templatePreviewHTML(previewTemplate,previewValues)} title="Template preview — not ready to send"/></>:
            <div className="draft-preview-unavailable" role="status">{previewLoading?'Loading original template…':previewError?.message??'Original template preview unavailable.'}
              {!previewLoading&&onReloadPreview&&<button type="button" className="text-button" onClick={onReloadPreview}>Reload original template</button>}
            </div>}
        </>}
      </div>
      <section className="draft-edit-disclosure">
      <button type="button" className="text-button" aria-expanded={fieldsOpen||dirty} aria-controls={`${prefix}-fields`} disabled={dirty} onClick={()=>setFieldsOpen(value=>!value)}>Edit personalization</button>
      <form id={`${prefix}-fields`} className="draft-fields" hidden={!fieldsOpen&&!dirty} onSubmit={event => { event.preventDefault(); void save(); }}>
        {SLOT_KEYS.map(key => <div className={`draft-field draft-slot-${key}`} key={key}>
          <label htmlFor={`${prefix}-${key}`}>{SLOT_LABELS[key]}</label>
          {unavailableSlots[key]&&<small className="draft-field-error">Confirm the source before editing this slot.</small>}
          {key === 'observation' ? <textarea id={`${prefix}-${key}`} rows={3} value={values[key]} disabled={disabled}
            aria-invalid={dirty&&!!fieldErrors[key]} aria-describedby={dirty&&fieldErrors[key] ? `${prefix}-${key}-error` : undefined} onChange={event => editValue(key, event.target.value)} />
            : <input id={`${prefix}-${key}`} value={values[key]} disabled={disabled} aria-invalid={dirty&&!!fieldErrors[key]}
              aria-describedby={dirty&&fieldErrors[key] ? `${prefix}-${key}-error` : undefined} onChange={event => editValue(key, event.target.value)} />}
          {dirty&&fieldErrors[key] && <small id={`${prefix}-${key}-error`} className="draft-field-error">{fieldErrors[key]}</small>}
          <button type="button" className="draft-source-button" aria-label={`Edit ${SLOT_LABELS[key].toLowerCase()} source`} disabled={disabled} onClick={() => onOpenSource(key === 'firstName' || key === 'channelName' ? 'overview' : 'works')}>Edit source</button>
        </div>)}
        {changed && <p className="draft-editor-warning">The draft changed while you were editing. Your edits are retained; load current values to start from the new version.</p>}
        {error?.id === draft.id && <p role="alert">{error.message}</p>}
        <div className="draft-editor-actions"><button className="button primary" type="submit" disabled={!canSave}>{saving ? 'Saving changes…' : 'Save changes'}</button>
          {dirty && <button className="text-button" type="button" disabled={disabled} onClick={loadCurrent}>Load current values</button>}</div>
      </form>
      </section>
    </div>
    <details className="draft-source-details"><summary>Recorded sources and version</summary>
      <dl><dt>Profile URL</dt><dd>{text(before.input.profile_url) || 'Not recorded'}</dd>
        <dt>Work URL</dt><dd>{text(work.source_url) || 'Not recorded'}</dd>
        <dt>Recorded excerpt</dt><dd>{text(work.evidence_excerpt) || 'Not recorded'}</dd>
        <dt>Verification notes</dt><dd>{text(work.verification_notes) || 'Not recorded'}</dd>
        <dt>Draft revision</dt><dd>{before.revision}</dd>
        <dt>Template version</dt><dd>{text(before.input.template_version_id)}</dd>
      </dl>
      <button className="text-button" type="button" disabled={disabled} onClick={() => onOpenSource('contacts')}>Edit contact source</button>
    </details>
    <div className="draft-editor-actions">
      {templateChanged?(onUseCurrentTemplate&&<button className="button secondary" type="button" disabled={disabled} onClick={onUseCurrentTemplate}>Use current template</button>):<button className="button secondary" type="button" disabled={disabled} onClick={() => setRefreshFor(version)}>Refresh sources</button>}
      {draft.status === 'failed' && <>
        {unknownGeneration && <label className="draft-charge-ack"><input type="checkbox" disabled={disabled} checked={chargeFor === version} onChange={event => setChargeFor(event.target.checked ? version : null)} />I understand another model call may incur a charge.</label>}
        <button className="button secondary" type="button" disabled={disabled || !!sourceMissing.length || draft.source_changed || (unknownGeneration && chargeFor !== version)} onClick={() => { setChargeFor(null); onRetry(); }}>Retry generation</button>
      </>}
    </div>
    {refreshFor === version && <div className="draft-refresh-confirm" role="group" aria-label="Confirm source refresh">
      <p>Clears the four values and sender confirmations. Uses model quota.</p>
      <div className="draft-editor-actions"><button className="button primary" type="button" disabled={disabled} onClick={() => void refreshSources()}>Refresh and clear values</button>
        <button className="text-button" type="button" disabled={disabled} onClick={() => setRefreshFor(null)}>Keep current draft</button></div>
    </div>}
  </section>;
}
