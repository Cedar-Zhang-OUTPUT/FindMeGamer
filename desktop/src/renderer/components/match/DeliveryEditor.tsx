import { useEffect, useId, useRef, useState } from 'react';
import type { Delivery, DeliveryResolution, SendBatch } from '../../../shared/sending';
import { EmailDocument } from './EmailDocument';
import { SLOT_KEYS, SLOT_LABELS } from './templateText';
import { analyzedDate } from '../Primitives';
import './sendingWorkspace.css';
export interface DeliveryEditorProps { batch: SendBatch; current: boolean; busy: boolean; onRetry(id: string): void | Promise<boolean>; onResolve(id: string, data: DeliveryResolution): Promise<boolean>; onDirtyChange(value: boolean): void }
type Verification = { attempt: number; note: string; outcome: '' | DeliveryResolution['outcome'] };
const dirty = (session: Verification) => !!session.note || !!session.outcome;
const text = (value: unknown): string => typeof value === 'string' ? value : '';
function stateLabel(row: Delivery): string {
  if (row.state === 'sent') return row.resolution.outcome === 'sent' && row.resolution.attempt === row.attempt ? 'Recorded as sent' : 'Accepted by SMTP';
  return { queued: 'Queued', sending: 'Submitting to SMTP', failed: 'Failed', unknown: 'Outcome unknown' }[row.state];
}
const errors: Record<string, string> = { smtp_outcome_unknown: 'Verify the submission result before any retry.', smtp_rejected: 'SMTP rejected this email.',
  smtp_temporarily_unavailable: 'SMTP was temporarily unavailable.', smtp_preparation_failed: 'The email could not be submitted.',
  sending_account_changed: 'The sending account changed. Review the connection.', submission_verified_not_sent: 'Verified as not sent.' };
export function DeliveryEditor({ batch, current, busy, onRetry, onResolve, onDirtyChange }: DeliveryEditorProps) {
  const prefix = useId();
  const [selectedId, setSelectedId] = useState(batch.deliveries[0]?.id ?? null), [sessions, setSessions] = useState<Record<string, Verification>>({});
  const [pending, setPending] = useState(false), [error, setError] = useState<{ id: string; message: string } | null>(null);
  const inFlight = useRef(false), alive = useRef(true), latestBatch = useRef(batch); latestBatch.current = batch;
  const row = batch.deliveries.find(item => item.id === selectedId) ?? batch.deliveries[0];
  const session = row ? sessions[row.id] ?? { attempt: row.attempt, note: '', outcome: '' } : null;
  const stale = !!row && !!session && session.attempt !== row.attempt;
  const disabled = busy || pending || !current;
  const anyDirty = Object.values(sessions).some(dirty);
  useEffect(() => { onDirtyChange(anyDirty); }, [anyDirty, onDirtyChange]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function edit(patch: Partial<Verification>) {
    if (!row || !session || disabled || stale || row.state !== 'unknown') return;
    setError(null); setSessions(old => ({ ...old, [row.id]: { ...session, ...patch } }));
  }
  function useCurrentAttempt() {
    if (!row || !session || disabled || row.state !== 'unknown') return;
    setSessions(old => ({ ...old, [row.id]: { attempt: row.attempt, note: session.note, outcome: '' } })); setError(null);
  }
  async function record() {
    if (!row || !session || disabled || stale || inFlight.current || row.state !== 'unknown' || !session.outcome || !session.note.trim() || session.note.length > 2000) return;
    const submitted = { ...session }, id = row.id;
    inFlight.current = true; setPending(true); setError(null);
    try {
      const accepted = await onResolve(id, { expected_attempt: submitted.attempt, outcome: session.outcome, source_note: submitted.note });
      if (!alive.current) return;
      if (accepted) setSessions(old => {
        const entry = old[id];
        if (!entry || entry.attempt !== submitted.attempt || entry.note !== submitted.note || entry.outcome !== submitted.outcome
          || latestBatch.current.deliveries.find(item => item.id === id)?.attempt !== submitted.attempt) return old;
        const next = { ...old }; delete next[id]; return next;
      });
      else setError({ id, message: 'The outcome was not recorded. Your verification notes are retained.' });
    } catch { if (alive.current) setError({ id, message: 'The result could not be confirmed. Your verification notes are retained.' }); }
    finally { inFlight.current = false; if (alive.current) setPending(false); }
  }
  async function retry() {
    if (!row || disabled || inFlight.current || !(row.state === 'queued' || row.state === 'failed' && row.retryable)) return;
    const id = row.id; inFlight.current = true; setPending(true); setError(null);
    try { if (await onRetry(id) === false && alive.current) setError({ id, message: 'Dispatch was not confirmed. Read the current delivery.' }); }
    catch { if (alive.current) setError({ id, message: 'Dispatch was not confirmed. Read the current delivery.' }); }
    finally { inFlight.current = false; if (alive.current) setPending(false); }
  }
  const sender = row?.snapshot.sender ?? batch.qualification.sender;
  const verify = !!row && !!session && (row.state === 'unknown' || dirty(session));
  return <section className="delivery-editor" aria-label="Frozen deliveries">
    <header className="delivery-heading"><h2>{batch.deliveries.length} {batch.deliveries.length === 1 ? 'delivery' : 'deliveries'}</h2><span>{analyzedDate(batch.created_at)}</span></header>
    <dl className="sending-identity"><div><dt>From</dt><dd>{sender.name && <strong>{sender.name}</strong>}<span>{sender.address || 'Not recorded'}</span></dd></div><div><dt>Reply-To</dt><dd>{sender.reply_to || 'Not set'}</dd></div></dl>
    <div className="delivery-layout"><nav className="delivery-roster" aria-label="Deliveries"><ol>{batch.deliveries.map(item => <li key={item.id}>
      <button type="button" disabled={disabled} aria-current={item.id === row?.id ? 'true' : undefined} onClick={() => setSelectedId(item.id)}>
        <strong>{item.snapshot.values?.channelName || item.snapshot.recipient_email || 'Recipient'}</strong><span>{item.snapshot.recipient_email || 'No recorded email'}</span><small>{stateLabel(item)}</small>
      </button></li>)}</ol></nav>
      <div className="delivery-selected">{row && <><header className="delivery-person-heading"><h3>{row.snapshot.subject}</h3><p role="status">{stateLabel(row)}</p></header>
        <p className="delivery-recipient">To: {row.snapshot.recipient_email}</p>
        {row.state === 'sent' && row.resolution.outcome !== 'sent' && <p className="delivery-note">SMTP acceptance does not confirm inbox delivery.</p>}
        {row.error_code && <p className="delivery-note">{errors[row.error_code] ?? 'Review the recorded delivery result.'}</p>}
        {row.snapshot.html && <EmailDocument html={row.snapshot.html} title="Frozen email preview" />}
        {(row.state === 'queued' || row.state === 'failed' && row.retryable) && <div className="delivery-actions"><button type="button" className="button primary" disabled={disabled} onClick={() => void retry()}>{row.state === 'queued' ? 'Dispatch queued' : 'Retry delivery'}</button></div>}
        {verify && session && <form className="delivery-verification" onSubmit={event => { event.preventDefault(); void record(); }}>
          <h4>Verify submission outcome</h4>
          {stale && <div className="delivery-stale"><p>This delivery has a newer attempt. Your note is retained; verify the current attempt separately.</p><button type="button" className="button secondary" disabled={disabled || row.state !== 'unknown'} onClick={useCurrentAttempt}>Use current attempt</button></div>}
          {!stale && row.state !== 'unknown' && <p>The delivery state changed. Your verification note is retained.</p>}
          <label htmlFor={`${prefix}-outcome`}>Verified outcome<select id={`${prefix}-outcome`} value={session.outcome} disabled={disabled || stale || row.state !== 'unknown'} onChange={event => edit({ outcome: event.target.value as Verification['outcome'] })}>
            <option value="">Choose verified outcome</option><option value="sent">Sent</option><option value="not_sent">Not sent</option></select></label>
          <label htmlFor={`${prefix}-note`}>Verification source note<textarea id={`${prefix}-note`} rows={3} maxLength={2000} required value={session.note} disabled={disabled || stale || row.state !== 'unknown'} onChange={event => edit({ note: event.target.value })} /></label>
          <p className="delivery-note">Recording not sent does not resend the email.</p>
          <button type="submit" className="button primary" disabled={disabled || stale || row.state !== 'unknown' || !session.outcome || !session.note.trim() || session.note.length > 2000}>Record verified outcome</button>
        </form>}
        {error?.id === row.id && <p role="alert">{error.message}</p>}
        {row.resolution.outcome && <details className="delivery-details"><summary>Recorded verification</summary><dl><div><dt>Outcome</dt><dd>{row.resolution.outcome === 'sent' ? 'Sent' : 'Not sent'}</dd></div>
          <div><dt>Source note</dt><dd>{row.resolution.source_note}</dd></div><div><dt>Recorded</dt><dd>{row.resolution.at}</dd></div><div><dt>Attempt</dt><dd>{row.resolution.attempt}</dd></div></dl></details>}
        <details className="delivery-details"><summary>Frozen sources and identity</summary><dl><div><dt>Account</dt><dd>{text(row.snapshot.identity.platform)} · {text(row.snapshot.identity.account_id)}</dd></div>
          <div><dt>Attempt</dt><dd>{row.attempt}</dd></div>{SLOT_KEYS.map(key => { const raw = row.snapshot.slot_sources[key], source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
            return <div key={key}><dt>{SLOT_LABELS[key]}</dt><dd>{row.snapshot.values?.[key] ?? 'Not filled'}{text(source.source_url) && <span>{text(source.source_url)}</span>}{text(source.evidence_excerpt) && <blockquote>{text(source.evidence_excerpt)}</blockquote>}{text(source.verification_notes) && <span>{text(source.verification_notes)}</span>}</dd></div>;
          })}<div><dt>Fixed content hash</dt><dd>{row.snapshot.fixed_hash}</dd></div></dl></details>
      </>}</div>
    </div>
    <details className="delivery-details delivery-qualification"><summary>Original qualification and exclusions ({batch.qualification.total_count} people)</summary>
      <p>{batch.qualification.eligible_count} included · {batch.qualification.excluded_count} excluded</p><ol>{batch.qualification.members.map(member => <li key={member.draft_id}>
        <strong>{member.values?.channelName || member.recipient_email || 'Recipient'}</strong><span>{member.recipient_email || 'No recorded email'}</span><span>{member.status === 'excluded' ? 'Excluded' : member.status === 'eligible' ? 'Included' : 'Needs repair'}</span>
        {member.exclusion_reason && <p>{member.exclusion_reason}</p>}<span>{member.subject}</span>
      </li>)}</ol>
    </details>
  </section>;
}
