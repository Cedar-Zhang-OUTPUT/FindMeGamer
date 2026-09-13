import { useEffect, useId, useRef, useState } from 'react';
import type { SlotValues } from '../../../shared/drafts';
import { evidenceFields, evidenceWriteUnknown, loadEvidenceContext, reconcileEvidence, saveEvidenceStages,
  type EvidenceAPI, type EvidenceAttempt, type EvidenceContext, type EvidenceFields, type EvidenceScope } from './inlineEvidence';

export interface InlineEvidenceProps {
  api: EvidenceAPI; scope: EvidenceScope; draftId: string; workId: string | null; active: boolean; disabled: boolean;
  values: SlotValues; valuesValid: boolean;
  connectionEpoch: number;
  onPreserve(id: string, values: SlotValues, expected: EvidenceAttempt): Promise<boolean>; onSaved(id: string): void;
  onBusy(value: boolean): void; onDirty(value: boolean): void; onOpenWork(): void;
}
type Session = {
  connectionEpoch: number;
  context: EvidenceContext; workId: string; fields: EvidenceFields;
  dirty: boolean; attempt?: EvidenceAttempt; uncertain?: boolean; message?: string;
};
const emptyFields: EvidenceFields = { evidence_excerpt: null, verification_notes: null, source_url: null };
export function InlineEvidenceEditor(props: InlineEvidenceProps) {
  const { api, scope, draftId, workId, active, disabled, values, valuesValid, onPreserve, onSaved, onBusy, onDirty, onOpenWork } = props;
  const prefix = useId(), [sessions, setSessions] = useState<Record<string, Session>>({});
  const [loading, setLoading] = useState(false), [loadError, setLoadError] = useState('');
  const pending = useRef(false), alive = useRef(true), generation = useRef(0), current = useRef(draftId);
  const sessionsRef = useRef(sessions); sessionsRef.current = sessions; current.current = draftId;
  const session = sessions[draftId];
  const seenConnection = useRef(props.connectionEpoch);
  if (seenConnection.current !== props.connectionEpoch) { generation.current++; seenConnection.current = props.connectionEpoch; }
  const connectionChanged = !!session && session.connectionEpoch !== props.connectionEpoch;
  const dirty = Object.values(sessions).some(row => row.dirty || !!row.attempt);
  useEffect(() => { onDirty(dirty); }, [dirty, onDirty]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; }; }, []);
  function put(id: string, row: Session) { if (alive.current) setSessions(old => ({ ...old, [id]: row })); }
  async function load() {
    if (pending.current || connectionChanged) return;
    pending.current = true; setLoading(true); setLoadError('');
    const id = draftId, epoch = generation.current;
    try {
      const context = await loadEvidenceContext(api, scope);
      if (!alive.current || epoch !== generation.current || current.current !== id) return;
      const previous = sessionsRef.current[id];
      if (previous) {
        if (previous.uncertain && previous.attempt) {
          const resolved = reconcileEvidence(previous.attempt, context);
          put(id, { ...previous, context, ...(resolved ? { attempt: resolved, uncertain: false } : {}),
            message: resolved ? 'Saved stage confirmed. Continue to update this draft.' : 'Save still unconfirmed. Your input is retained; no request has been repeated.' });
        } else {
          const work = context.works.find(row => row.id === previous.workId);
          put(id, { ...previous, context, attempt: previous.attempt && work ? { ...previous.attempt, work, selection: context.selection } : previous.attempt,
            ...(!previous.dirty && !previous.attempt && work ? { fields: evidenceFields(work) } : {}),
            message: 'Current evidence loaded. Review your input before continuing.' });
        }
      } else {
        const chosen = context.works.find(row => row.id === workId)
          ?? (context.selection.works.length === 1 ? context.works.find(row => row.id === context.selection.works[0].id) : undefined);
        put(id, { connectionEpoch: props.connectionEpoch, context, workId: chosen?.id ?? '', fields: chosen ? evidenceFields(chosen) : emptyFields, dirty: false });
      }
    } catch { if (alive.current && current.current === id) setLoadError('Could not load work evidence. Your input is retained.'); }
    finally { pending.current = false; if (alive.current) setLoading(false); }
  }
  useEffect(() => { if (active && !session && !disabled) void load(); }, [active, draftId, disabled]);
  const fields = session?.fields ?? emptyFields;
  const lengthsValid = [...(fields.evidence_excerpt ?? '')].length <= 20000 && [...(fields.verification_notes ?? '')].length <= 20000 && [...(fields.source_url ?? '')].length <= 2048;
  const work = session?.context.works.find(row => row.id === session.workId);
  const fieldLocked = disabled || loading || !!session?.attempt || connectionChanged;
  let urlValid = !fields.source_url;
  if (fields.source_url) try { const url = new URL(fields.source_url); urlValid = url.protocol === 'https:' && !!url.hostname && !url.username && !url.password; } catch { /* Inline error below. */ }
  async function save() {
    if (pending.current || disabled || connectionChanged || !session || !work || session.uncertain || !valuesValid || !urlValid || !lengthsValid) return;
    pending.current = true; onBusy(true); setLoading(true);
    const id = draftId, epoch = generation.current, wording = { ...values };
    let next = { ...session, message: 'Saving evidence…', attempt: session.attempt ?? { scope, work, fields: { ...fields }, selection: session.context.selection, stage: 'work' as const } };
    put(id, next);
    try {
      const attempt = await saveEvidenceStages(api, next.attempt, checkpoint => { next = { ...next, attempt: checkpoint }; put(id, next); },
        () => alive.current && epoch === generation.current && current.current === id);
      next = { ...next, attempt, message: 'Evidence saved · updating this draft…' }; put(id, next);
      if (await onPreserve(id, wording, attempt)) {
        put(id, { ...next, context: { selection: attempt.selection, works: next.context.works.map(row => row.id === attempt.work.id ? attempt.work : row) },
          dirty: false, attempt: undefined, uncertain: false, message: 'Evidence and draft saved · wording retained' });
        onSaved(id);
      } else put(id, { ...next, message: 'Evidence saved. Draft update not confirmed; your wording is retained. Check the draft status, then continue.' });
    } catch (error) {
      put(id, { ...next, ...(!evidenceWriteUnknown(error) && next.attempt.stage === 'work' ? {attempt: undefined} : {}), uncertain: evidenceWriteUnknown(error), message: evidenceWriteUnknown(error)
        ? 'Save not confirmed. Check saved changes before continuing.' : 'Save stopped. Your input is retained. Reload evidence and review before continuing.' });
    } finally { pending.current = false; if (alive.current) { setLoading(false); onBusy(false); } }
  }
  return <section className="inline-evidence" aria-label="Shared work evidence">
    <header><h4>Work evidence</h4><span className="draft-editing-note">Shared in Library</span></header>
    {connectionChanged && <p role="alert">Connection changed. This input belongs to the original connection and cannot be submitted here. Copy it before reopening the draft.</p>}
    {loadError && <p role="alert">{loadError}</p>}
    {!session ? <><p role="status">{loading ? 'Loading evidence…' : 'Work evidence unavailable'}</p>
      {!loading && <button type="button" className="text-button" disabled={disabled} onClick={() => void load()}>Load work evidence</button>}</> : <>
      <label htmlFor={`${prefix}-work`}>Source work</label>
      <select id={`${prefix}-work`} value={session.workId} disabled={fieldLocked || (session.dirty && !!session.workId)} onChange={event => {
        const selected = session.context.works.find(row => row.id === event.target.value);
        if (selected) put(draftId, { ...session, workId: selected.id, fields: evidenceFields(selected), dirty: true, message: undefined });
      }}><option value="">Choose an existing work</option>{session.context.works.map(row => <option key={row.id} value={row.id}>{row.content_title || row.work_name || row.source_content_id || 'Untitled work'}</option>)}</select>
      {!work && <button type="button" className="text-button" disabled={fieldLocked} onClick={onOpenWork}>Add a work in Library</button>}
      {work && <>
        {(['evidence_excerpt', 'verification_notes', 'source_url'] as const).map(key => <div key={key}>
          <label htmlFor={`${prefix}-${key}`}>{{ evidence_excerpt: 'Evidence excerpt', verification_notes: 'Verification notes', source_url: 'Source URL' }[key]}</label>
          {key === 'source_url' ? <input id={`${prefix}-${key}`} type="url" value={fields[key] ?? ''} disabled={fieldLocked} onChange={event => put(draftId, { ...session, dirty: true, fields: { ...fields, [key]: event.target.value || null } })} />
            : <textarea id={`${prefix}-${key}`} rows={2} value={fields[key] ?? ''} disabled={fieldLocked} onChange={event => put(draftId, { ...session, dirty: true, fields: { ...fields, [key]: event.target.value || null } })} />}
        </div>)}
        {!urlValid && <p role="alert">Use an HTTPS source URL without login details.</p>}
        {!lengthsValid && <p role="alert">Evidence and notes allow 20,000 characters each; URL allows 2,048.</p>}
        {session.dirty && <details><summary>Compare current saved evidence</summary><dl>
          <dt>Evidence excerpt</dt><dd>{work.evidence_excerpt || 'Not recorded'}</dd>
          <dt>Verification notes</dt><dd>{work.verification_notes || 'Not recorded'}</dd>
          <dt>Source URL</dt><dd>{work.source_url || 'Not recorded'}</dd>
        </dl></details>}
        <p className="draft-editing-note">Updates shared evidence, uses this work for this person, and clears this draft’s confirmations. Keeps your email wording. No model call.</p>
        <div className="draft-editor-actions"><button type="button" className="button secondary" disabled={disabled || loading || connectionChanged || !!session.uncertain || !valuesValid || !urlValid || !lengthsValid} onClick={() => void save()}>
          {loading ? 'Saving…' : session.attempt ? 'Continue saving draft' : 'Save evidence & draft'}</button>
          <button type="button" className="text-button" disabled={disabled || loading || connectionChanged} onClick={() => void load()}>{session.uncertain ? 'Check saved changes' : 'Reload evidence'}</button>
          {session.attempt && !session.uncertain && <button type="button" className="text-button" disabled={disabled || loading || connectionChanged}
            onClick={()=>put(draftId,{...session,attempt:undefined,dirty:true,message:'Earlier acknowledged changes remain saved. Review and edit this evidence before saving again.'})}>Edit evidence again</button>}
        </div>
      </>}
      {session.message && <p role="status">{session.message}</p>}
    </>}
  </section>;
}
