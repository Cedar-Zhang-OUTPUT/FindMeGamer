import { useEffect, useRef, useState } from 'react';
import type { ActivityInvitation, CollaborationUpdate, CooperationState, FollowUpState, ManualActivityResponse } from '../../../shared/collaboration';
import type { Delivery } from '../../../shared/sending';
import { EmailDocument } from './EmailDocument';
import './collaborationWorkspace.css';
import type {ConfirmedCollaborationChange} from './useActivityCollaboration';

export interface CollaborationEditorProps {
  confirmedChange?: ConfirmedCollaborationChange|null;
  invitation: ActivityInvitation; current: boolean; busy: boolean; editable?: boolean;
  onUpdate(data: CollaborationUpdate): Promise<boolean>; onRespond(data: ManualActivityResponse): Promise<boolean>;
  onOpenCreator?(): void; onDirtyChange(value: boolean): void;
}
type Session = {
  mode: 'progress' | 'response'; revision: number;
  base: { follow_up_state: FollowUpState; cooperation_state: CooperationState; notes: string };
  follow_up_state: FollowUpState; cooperation_state: CooperationState; notes: string;
  outcome: '' | 'accepted' | 'declined'; source_note: string; time: string;
};
const followUps: FollowUpState[] = ['not_followed_up', 'follow_up_needed', 'followed_up', 'no_follow_up_needed'];
const cooperation: CooperationState[] = ['not_started', 'in_discussion', 'collaboration_confirmed', 'in_production', 'awaiting_publication', 'published', 'settled', 'closed'];
const label = (value: string) => value.replaceAll('_', ' ');
const stamp = (value: string) => new Date(value).toLocaleString();
const sendingLabel = (delivery: Delivery) => delivery.state === 'sent' ? delivery.resolution.outcome === 'sent' ? 'Recorded as sent' : 'SMTP accepted' : label(delivery.state);
const changed = (session: Session) => session.mode === 'response' ? !!(session.outcome || session.source_note || session.time) : session.notes !== session.base.notes || session.follow_up_state !== session.base.follow_up_state || session.cooperation_state !== session.base.cooperation_state;
function eventTime(value: string): string | null {
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!parts) return null;
  const [year, month, day, hour, minute] = parts.slice(1).map(Number), date = new Date(year, month - 1, day, hour, minute);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day || date.getHours() !== hour || date.getMinutes() !== minute) return null;
  return date.toISOString();
}
export function CollaborationEditor({ invitation: row, current, busy, editable = true, onUpdate, onRespond, onOpenCreator, onDirtyChange, confirmedChange }: CollaborationEditorProps) {
  const [sessions, setSessions] = useState<Record<string, Session>>({});
  const [saving, setSaving] = useState(false), savingRef = useRef(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [mail, setMail] = useState<{ key: string; deliveryId: string } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const key = row.activity_id + ':' + row.selection_id, session = sessions[key];
  const enabled = current && !busy && !saving && editable, stale = !!session && session.revision !== row.revision;
  const dirty = Object.values(sessions).some(changed);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(()=>{if(!confirmedChange)return;const c=confirmedChange,k=c.activityId+':'+c.selectionId;setSessions(all=>{const old=all[k];if(!old||old.revision!==c.revision||old.mode!==(c.kind==='respond'?'response':'progress'))return all;const next={...all};delete next[k];return next;});},[confirmedChange]);
  const patch = (value: Partial<Session>) => setSessions(all => ({ ...all, [key]: { ...all[key], ...value } }));
  const begin = (mode: Session['mode']) => {
    if (!enabled) return;
    setFailure(null);
    setSessions(all => ({ ...all, [key]: { mode, revision: row.revision, base: { follow_up_state: row.follow_up_state, cooperation_state: row.cooperation_state, notes: row.notes }, follow_up_state: row.follow_up_state, cooperation_state: row.cooperation_state, notes: row.notes, outcome: '', source_note: '', time: '' } }));
  };
  const cancel = () => { if (!enabled) return; setSessions(all => { const next = { ...all }; delete next[key]; return next; }); setFailure(null); };
  const rebind = () => {
    if (!enabled || !session) return;
    patch({ revision: row.revision, base: { follow_up_state: row.follow_up_state, cooperation_state: row.cooperation_state, notes: row.notes },
      follow_up_state: session.follow_up_state === session.base.follow_up_state ? row.follow_up_state : session.follow_up_state,
      cooperation_state: session.cooperation_state === session.base.cooperation_state ? row.cooperation_state : session.cooperation_state,
      notes: session.notes === session.base.notes ? row.notes : session.notes,
    });
  };
  const respondedAt = session ? eventTime(session.time) : null;
  const responseValid = !!session && !!session.outcome && !!session.source_note.trim() && session.source_note.length <= 2000 && !!respondedAt;
  const progressValid = !!session && changed(session) && session.notes.length <= 10000;
  async function save() {
    if (!enabled || savingRef.current || stale || !session || !(session.mode === 'response' ? responseValid : progressValid)) return;
    const submitted = session, submittedKey = key;
    savingRef.current = true; setSaving(true); setFailure(null);
    try {
      let ok: boolean;
      if (submitted.mode === 'response') ok = await onRespond({ expected_revision: submitted.revision, outcome: submitted.outcome as 'accepted' | 'declined', source_note: submitted.source_note.trim(), responded_at: respondedAt! });
      else {
        const data: CollaborationUpdate = { expected_revision: submitted.revision };
        if (submitted.follow_up_state !== submitted.base.follow_up_state) data.follow_up_state = submitted.follow_up_state;
        if (submitted.cooperation_state !== submitted.base.cooperation_state) data.cooperation_state = submitted.cooperation_state;
        if (submitted.notes !== submitted.base.notes) data.notes = submitted.notes;
        ok = await onUpdate(data);
      }
      if (ok) setSessions(all => { if (all[submittedKey] !== submitted) return all; const next = { ...all }; delete next[submittedKey]; return next; });
      else setFailure(submittedKey);
    } catch { setFailure(submittedKey); }
    finally { savingRef.current = false; setSaving(false); }
  }
  const preview = historyOpen && mail?.key === key ? row.send_history.find(entry => entry.delivery?.id === mail.deliveryId)?.delivery : null;
  return <section className="collaboration-editor" aria-label="Invitation relationship">
    <header><div><h3>{row.display_name || 'Unnamed creator'}</h3><p>{label(row.invitation_state)} · {label(row.follow_up_state)} · {label(row.cooperation_state)}</p></div>
      {onOpenCreator && <button type="button" disabled={!current || busy || saving} onClick={onOpenCreator}>Open creator</button>}
    </header>
    {!row.selected && <p>Historical relationship · no longer selected</p>}
    {(!session || !editable) ? <div className="collaboration-summary">
      <p>{row.notes || 'No notes'}</p>
      {editable && <div className="collaboration-actions"><button type="button" disabled={!enabled} onClick={() => begin('response')}>Record response</button><button type="button" disabled={!enabled} onClick={() => begin('progress')}>Edit progress</button></div>}
    </div> : <form onSubmit={event => { event.preventDefault(); void save(); }}>
      {stale && <div role="status"><p>Current record is revision {row.revision}. Your edits remain bound to revision {session.revision}.</p><p>Use current version keeps your changes and loads untouched fields. Saving may replace current values in fields you changed.</p><button type="button" disabled={!enabled} onClick={rebind}>Use current version</button></div>}
      <fieldset disabled={!enabled}>
        <legend>{session.mode === 'response' ? 'Record response' : 'Edit progress'}</legend>
        {session.mode === 'response' ? <>
          <label>Response<select value={session.outcome} onChange={event => patch({ outcome: event.target.value as Session['outcome'] })}><option value="">Choose response</option><option value="accepted">Accepted</option><option value="declined">Declined</option></select></label>
          <label>Source note<textarea value={session.source_note} maxLength={2000} onChange={event => patch({ source_note: event.target.value })}/></label>
          <label>Responded at ({Intl.DateTimeFormat().resolvedOptions().timeZone})<input type="datetime-local" value={session.time} onChange={event => patch({ time: event.target.value })}/></label>
          <p className="collaboration-hint">Actual response time in your local zone. Recording acceptance does not change cooperation progress.</p>
        </> : <>
          <div className="collaboration-fields"><label>Follow-up<select value={session.follow_up_state} onChange={event => patch({ follow_up_state: event.target.value as FollowUpState })}>{followUps.map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label>
          <label>Cooperation<select value={session.cooperation_state} onChange={event => patch({ cooperation_state: event.target.value as CooperationState })}>{cooperation.map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label></div>
          <label>Notes<textarea value={session.notes} maxLength={10000} onChange={event => patch({ notes: event.target.value })}/></label>
        </>}
        <div className="collaboration-actions"><button type="submit" disabled={stale || !(session.mode === 'response' ? responseValid : progressValid)}>{session.mode === 'response' ? 'Save response' : 'Save progress'}</button><button type="button" onClick={cancel}>Cancel</button></div>
      </fieldset>
      {failure === key && <p role="status">Save not confirmed. Your inputs are retained.</p>}
    </form>}
    <details><summary>Response sources and history</summary>
      {row.responses.length ? [...row.responses].sort((a, b) => b.revision - a.revision).map(response => <article key={response.id}><strong>{label(response.outcome)}</strong><p data-testid="response-source">{response.source_note}</p><p>Responded at {stamp(response.responded_at)}</p><p>Recorded at {stamp(response.recorded_at)} · revision {response.revision}</p></article>) : <p>No recorded responses</p>}
    </details>
    <details onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary>Sending history</summary>
      <p>{row.sending_state === 'sent' ? 'Sent record · see SMTP or manual evidence below' : label(row.sending_state)}{row.invited_at ? ` · ${stamp(row.invited_at)}` : ''}</p>
      {row.send_history.map((entry, index) => <article key={entry.send_batch_id + ':' + entry.draft_id}>
        <p>{stamp(entry.created_at)} · {entry.delivery ? sendingLabel(entry.delivery) : label(entry.qualification_status)}</p>
        {entry.exclusion_reason && <p>Excluded: {entry.exclusion_reason}</p>}
        {entry.delivery && <><p>To {entry.delivery.snapshot.recipient_email}</p><button type="button" disabled={busy || !current || saving} onClick={() => setMail(mail?.key === key && mail.deliveryId === entry.delivery!.id ? null : { key, deliveryId: entry.delivery!.id })}>{mail?.key === key && mail.deliveryId === entry.delivery.id ? 'Close email' : `View email ${index + 1}`}</button></>}
      </article>)}
      {preview && <div className="collaboration-mail"><p>From {preview.snapshot.sender.name} {preview.snapshot.sender.address}</p><p>Reply-To {preview.snapshot.sender.reply_to || 'Not set'}</p><h4>{preview.snapshot.subject}</h4><EmailDocument html={preview.snapshot.html || ''} title="Frozen sent email"/>{preview.resolution.outcome && <p>Manual resolution: {label(preview.resolution.outcome)} · {preview.resolution.source_note} · {stamp(preview.resolution.at)}</p>}</div>}
    </details>
    <details><summary>Original recipient memberships</summary>{row.memberships.map(member => <article key={member.recipient_snapshot_id}><p>Batch {member.recipient_batch_id} · input {member.input_order} · {stamp(member.created_at)}</p><pre>{JSON.stringify(member.snapshot, null, 2)}</pre></article>)}{!row.memberships.length && <p>No frozen memberships</p>}</details>
    <details><summary>Saved account identity</summary><pre>{JSON.stringify(row.identity, null, 2)}</pre></details>
  </section>;
}
