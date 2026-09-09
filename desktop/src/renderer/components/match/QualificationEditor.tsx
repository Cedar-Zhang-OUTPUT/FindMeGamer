import { useId, useState } from 'react';
import type { CompositionView } from '../../../shared/drafts';
import type { Exclusion, Qualification } from '../../../shared/sending';
import { EmailDocument } from './EmailDocument';
import { SLOT_KEYS, SLOT_LABELS } from './templateText';
import './sendingWorkspace.css';
export interface QualificationEditorProps {
  qualification: Qualification | null; composition: CompositionView; exclusions: Exclusion[]; current: boolean; busy: boolean;
  onExclusionsChange(value: Exclusion[]): void; onCheck(): void; onSend(): void; onRepairDraft(id: string): void; onOpenSettings?(): void; onUseCurrentTemplate?():void;
}
const missingLabels: Record<string, string> = {
  sender_identity_missing:'Set a sender name in Email settings, then create new drafts.',template_context_changed:'Game or sender details changed. Create new drafts with the current template.',
  email_not_selected: 'Choose a contact email.', email_changed: 'Review the changed contact.', email_invalid: 'Record a valid contact email.', email_missing: 'Record a contact email.',
  draft_sources_changed: 'Refresh changed draft sources.', draft_not_complete: 'Complete this draft.', sender_facts_unconfirmed: 'Confirm the sender facts.', smtp_not_configured: 'Configure the sending account.',
  template_game_mismatch: 'Choose a template for this game.', duplicate_recipient_email: 'Resolve the shared recipient address.', already_invited: 'Review the existing invitation.',
  public_name_unconfirmed: 'Confirm the public name.', observation_evidence_missing: 'Record evidence for the observation.', reference_missing: 'Choose the referenced work.',
  channel_name_missing: 'Record the channel name.', identity_changed: 'Review the creator identity.', not_selected: 'Restore this prepared person.',
};
const text = (value: unknown): string => typeof value === 'string' ? value : '';
export function QualificationEditor({ qualification, composition, exclusions, current, busy, onExclusionsChange, onCheck, onSend, onRepairDraft, onOpenSettings,onUseCurrentTemplate }: QualificationEditorProps) {
  const prefix = useId();
  const [selectedId, setSelectedId] = useState(composition.drafts[0]?.id ?? null);
  const [editedAgainst, setEditedAgainst] = useState<Qualification | null | undefined>(undefined);
  const q = qualification?.composition_id === composition.id && qualification.activity_id === composition.activity_id ? qualification : null;
  const selected = composition.drafts.find(row => row.id === selectedId) ?? composition.drafts[0];
  const nameOf = (row: CompositionView['drafts'][number], index: number) => text(row.input.channel_name) || text(row.input.public_name) || `Person ${index + 1}`;
  const selectedIndex = selected ? composition.drafts.indexOf(selected) : -1;
  const name = selected ? nameOf(selected, selectedIndex) : '';
  const member = q?.members.find(item => item.draft_id === selected?.id && item.recipient_snapshot_id === selected?.recipient_snapshot_id);
  const excluded = exclusions.find(item => item.draft_id === selected?.id);
  const validExclusions = exclusions.length <= 600 && new Set(exclusions.map(item => item.draft_id)).size === exclusions.length
    && exclusions.every(item => composition.drafts.some(row => row.id === item.draft_id) && item.reason.trim().length > 0 && item.reason.length <= 1000);
  const fullMembership = !!q && q.total_count === composition.recipient_count && q.members.length === composition.drafts.length
    && composition.recipient_count === composition.drafts.length && new Set(q.members.map(item => item.draft_id)).size === q.members.length
    && composition.drafts.every(row => q.members.some(item => item.draft_id === row.id && item.recipient_snapshot_id === row.recipient_snapshot_id));
  const sameExclusions = !!q && validExclusions && exclusions.length === q.excluded_count
    && q.members.filter(item => item.status === 'excluded').length === exclusions.length
    && exclusions.every(item => q.members.some(m => m.draft_id === item.draft_id && m.status === 'excluded' && m.exclusion_reason === item.reason.trim()));
  const checked = current && fullMembership && sameExclusions && editedAgainst !== qualification;
  const eligible = q?.members.filter(item => item.status === 'eligible') ?? [];
  const ready = checked && q?.send_ready && q.eligible_count === eligible.length && eligible.length > 0 && q.repair_count === 0
    && eligible.length + q.excluded_count === q.total_count && !!q.sender.address
    && eligible.every(item => !item.missing_fields.length && !item.blocking_delivery_id && !!item.recipient_email && !!item.html && !!item.text && !!item.values);
  function updateExclusions(value: Exclusion[]) { if (busy) return; setEditedAgainst(qualification); onExclusionsChange(value); }
  function toggle(checked: boolean) {
    if (!selected) return;
    updateExclusions(checked ? [...exclusions.filter(item => item.draft_id !== selected.id), { draft_id: selected.id, reason: '' }] : exclusions.filter(item => item.draft_id !== selected.id));
  }
  function reason(value: string) {
    if (!selected) return;
    updateExclusions(exclusions.map(item => item.draft_id === selected.id ? { ...item, reason: value } : item));
  }
  return <section className="qualification-editor" aria-label="Review recipients">
    <header className="qualification-heading"><div><h2>Review {composition.recipient_count} recipients</h2>
      <p role="status">{checked && q ? `${q.eligible_count} ready · ${q.repair_count} need repair · ${q.excluded_count} excluded` : q ? 'Recheck required' : 'Recipients not checked'}</p></div>
      {onOpenSettings && <button type="button" className="text-button" disabled={busy} onClick={onOpenSettings}>SMTP settings</button>}
    </header>
    <dl className="sending-identity"><div><dt>From</dt><dd>{q?.sender.name && <strong>{q.sender.name}</strong>}<span>{q?.sender.address || 'Not configured'}</span></dd></div>
      <div><dt>Reply-To</dt><dd>{q?.sender.reply_to || 'Not set'}</dd></div></dl>
    <div className="qualification-layout">
      <nav className="qualification-roster" aria-label="Recipients"><ol>{composition.drafts.map((row, index) => {
        const item = q?.members.find(m => m.draft_id === row.id && m.recipient_snapshot_id === row.recipient_snapshot_id);
        const localExclusion = exclusions.some(exclusion => exclusion.draft_id === row.id);
        const status = localExclusion ? 'Excluded' : item?.status === 'eligible' ? 'Ready' : item?.status === 'needs_repair' ? 'Needs repair' : item?.status === 'excluded' ? 'Recheck required' : 'Not checked';
        return <li key={row.id}><button type="button" aria-current={row.id === selected?.id ? 'true' : undefined} disabled={busy} onClick={() => setSelectedId(row.id)}>
          <strong>{nameOf(row, index)}</strong><span>{item?.recipient_email || 'No recorded email'}</span><small>{status}</small>
        </button></li>;
      })}</ol></nav>
      <div className="qualification-selected">
        {selected && <><header className="qualification-person-heading"><h3>{name}</h3><button type="button" className="text-button" disabled={busy} onClick={() => onRepairDraft(selected.id)}>Repair draft</button></header>
          <div className="qualification-exclusion"><label><input type="checkbox" checked={!!excluded} disabled={busy} onChange={event => toggle(event.target.checked)} />Exclude {name}</label>
            {excluded && <label htmlFor={`${prefix}-reason`}>Exclusion reason for {name}<textarea id={`${prefix}-reason`} rows={2} maxLength={1000} value={excluded.reason} disabled={busy}
              required aria-invalid={!excluded.reason.trim() || excluded.reason.length > 1000} onChange={event => reason(event.target.value)} /></label>}
            {excluded && !excluded.reason.trim() && <small className="qualification-error">Add a reason to exclude this person.</small>}
          </div>
          {!!member?.missing_fields.length && <ul className="qualification-missing">{member.missing_fields.map(field => <li key={field}>{missingLabels[field] ?? (field.startsWith('email_') ? 'Review the recorded contact email.' : 'Review this draft’s recorded sources.')}</li>)}</ul>}
          {member?.missing_fields.includes('sender_identity_missing')&&onOpenSettings&&<button className="button secondary" disabled={busy} onClick={onOpenSettings}>Email settings</button>}
          {member?.missing_fields.some(field=>['sender_identity_missing','template_context_changed'].includes(field))&&onUseCurrentTemplate&&<button className="button secondary" disabled={busy} onClick={onUseCurrentTemplate}>Use current template</button>}
          {member?.subject && <h4 className="qualification-subject">{member.subject}</h4>}
          {member?.html ? <EmailDocument html={member.html} /> : <p className="qualification-empty">{q ? 'Complete the draft to preview its email.' : 'Check recipients to review the exact email.'}</p>}
          {member && <details className="qualification-sources"><summary>Sources, identity and sender facts</summary>
            <dl><div><dt>Account</dt><dd>{text(member.identity.platform)} · {text(member.identity.account_id) || 'Not recorded'}</dd></div>
              <div><dt>Draft version</dt><dd>{member.revision}</dd></div>
              <div><dt>Sender facts</dt><dd>{(['following', 'enjoyed', 'liked'] as const).map(key => <span key={key}>{key === 'following' ? 'Following' : key === 'enjoyed' ? 'Enjoyed the work' : 'Liked the details'}: {member.sender_facts[key] === true ? 'confirmed' : 'not confirmed'}</span>)}</dd></div>
              {SLOT_KEYS.map(key => { const raw = member.slot_sources[key], source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
                return <div key={key}><dt>{SLOT_LABELS[key]}</dt><dd>{member.values?.[key] ?? 'Not filled'}{text(source.source_url) && <span>{text(source.source_url)}</span>}
                  {text(source.evidence_excerpt) && <blockquote>{text(source.evidence_excerpt)}</blockquote>}{text(source.verification_notes) && <span>{text(source.verification_notes)}</span>}</dd></div>;
              })}
              {member.blocking_delivery_id && <div><dt>Existing invitation</dt><dd>{member.blocking_delivery_id}</dd></div>}
            </dl>
          </details>}
        </>}
      </div>
    </div>
    <footer className="qualification-actions"><button type="button" className={`button ${ready ? 'secondary' : 'primary'}`} disabled={busy || !validExclusions || !composition.drafts.length} onClick={onCheck}>Check recipients</button>
      {ready && <div className="qualification-send"><span>Emails cannot be recalled after submission.</span><button type="button" className="button primary" disabled={busy} onClick={onSend}>Send {eligible.length} {eligible.length === 1 ? 'email' : 'emails'}</button></div>}
    </footer>
  </section>;
}
