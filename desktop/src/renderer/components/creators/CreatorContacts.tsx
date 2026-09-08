import { useState } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import type { ContactDetail } from '../../../shared/creators';
import { analyzedDate, ErrorNotice, friendlyLabel, Icon } from '../Primitives';

function safeHTTPS(value: string | null): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password;
  } catch { return false; }
}

export interface CreatorContactsProps {
  api: DesktopBridge;
  contacts: ContactDetail[];
  onEdit: (target: { kind: 'contact'; base?: ContactDetail }) => void;
}

export function CreatorContacts({ api, contacts, onEdit }: CreatorContactsProps) {
  const [externalError, setExternalError] = useState<PublicError | null>(null);
  async function open(url: string) {
    if (!safeHTTPS(url)) return;
    setExternalError(null);
    try {
      const result = await api.openExternal(url);
      if (!result.ok) setExternalError(result.error);
    } catch {
      setExternalError({ code: 'open_failed', message: 'This source link could not be opened.', retryable: false });
    }
  }

  return <section className="creator-section creator-contacts" aria-labelledby="creator-emails-heading">
    <div className="creator-section-heading">
      <h2 id="creator-emails-heading">Email addresses <span className="count">{contacts.length}</span></h2>
      <button className="button primary" onClick={() => onEdit({ kind: 'contact' })}>Add email</button>
    </div>
    <details className="creator-help"><summary>What validation means</summary><p>Validation describes recorded checks; it does not prove mailbox deliverability.</p></details>
    {externalError && <ErrorNotice error={externalError}/>} 
    {contacts.length === 0 ? <p className="creator-empty">No email addresses recorded.</p> : <ul className="creator-contact-list">
      {contacts.map(contact => <li key={contact.id} className={!contact.is_active ? 'is-inactive' : undefined}>
        <div className="creator-card-heading">
          <div><h3>{contact.email}</h3><div className="creator-badges">{!contact.is_current_identity && <span>Previous identity</span>}{!contact.is_active && <span>Hidden</span>}<span>{friendlyLabel(contact.validation_state)}</span>{contact.origin === 'manual' && <span>Manual</span>}</div></div>
          {contact.is_current_identity && <button className="button secondary" onClick={() => onEdit({ kind: 'contact', base: contact })}>{contact.is_active ? `Edit ${contact.email}` : `Edit or restore ${contact.email}`}</button>}
        </div>
        {contact.purpose && <p className="creator-card-purpose">{contact.purpose}</p>}
        <details className="creator-provenance"><summary>Contact details</summary><div className="creator-contact-details"><dl className="creator-detail-grid"><div><dt>Origin</dt><dd>{friendlyLabel(contact.origin)}</dd></div><div><dt>Source type</dt><dd>{friendlyLabel(contact.source_type)}</dd></div><div><dt>Identity revision</dt><dd>{contact.identity_revision}</dd></div><div><dt>Updated</dt><dd>{analyzedDate(contact.updated_at)}</dd></div></dl>{contact.verification_notes && <p className="creator-verification"><strong>Validation notes</strong>{contact.verification_notes}</p>}{contact.source_url && <div className="creator-source-row"><span><strong>Source</strong><span className="creator-raw-value">{contact.source_url}</span></span>{safeHTTPS(contact.source_url) && <button className="text-button" onClick={() => void open(contact.source_url!)} aria-label={`Open source for ${contact.email}`}>Open source<Icon name="external"/></button>}</div>}<details className="creator-raw-details"><summary>Raw fields</summary><div className="creator-provenance-grid"><div><h4>Source fields</h4><pre>{JSON.stringify(contact.source_fields, null, 2)}</pre></div><div><h4>Manual overrides</h4><pre>{JSON.stringify(contact.manual_overrides, null, 2)}</pre></div></div></details></div></details>
      </li>)}
    </ul>}
  </section>;
}
