import { useEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../shared/bridge';
import type { JsonValue, ProfileDetail as Profile, ProfileSummary } from '../../shared/library';
import { analyzedDate, Artwork, ErrorNotice, friendlyLabel, Icon, Loading } from './Primitives';

function FieldValue({ value, depth = 0 }: { value: JsonValue; depth?: number }) {
  if (value === null) return <span className="muted">Not available</span>;
  if (typeof value === 'boolean') return <span>{value ? 'Yes' : 'No'}</span>;
  if (typeof value === 'string' || typeof value === 'number') return <span className="field-text">{String(value) || 'Not available'}</span>;
  if (Array.isArray(value)) return value.length ? <ul className="field-list">{value.map((item, index) => <li key={index}><FieldValue value={item} depth={depth + 1}/></li>)}</ul> : <span className="muted">None recorded</span>;
  const entries = Object.entries(value);
  if (!entries.length) return <span className="muted">None recorded</span>;
  // Deep source structures remain available without producing a hundred nested columns.
  if (depth > 3) return <pre className="source-text">{JSON.stringify(value, null, 2)}</pre>;
  return <dl className={`field-grid depth-${Math.min(depth, 2)}`}>{entries.map(([key, item]) => <div key={key}><dt>{friendlyLabel(key)}</dt><dd><FieldValue value={item} depth={depth + 1}/></dd></div>)}</dl>;
}

export function ProfileDetail({ api, summary, onBack }: { api: DesktopBridge; summary: ProfileSummary; onBack: () => void }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<PublicError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [externalError, setExternalError] = useState<PublicError | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    let cancelled = false;
    setProfile(null); setError(null);
    void api.library.detail({ kind: summary.kind, id: summary.id }).then(result => {
      if (cancelled) return;
      if (result.ok) setProfile(result.data); else setError(result.error);
    }, () => { if (!cancelled) setError({ code: 'bridge_unavailable', message: 'The profile could not be loaded.', retryable: true }); });
    return () => { cancelled = true; };
  }, [api, summary.id, summary.kind, attempt]);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [summary.id]);
  const shown = profile ?? summary;
  async function openSource(url: string) {
    setExternalError(null);
    try { const result = await api.openExternal(url); if (!result.ok) setExternalError(result.error); }
    catch { setExternalError({ code: 'open_failed', message: 'This link could not be opened.', retryable: false }); }
  }
  return <div className="profile-detail">
    <button className="text-button back-button" onClick={onBack}><Icon name="arrow"/>Back to {summary.kind}</button>
    <section className="profile-identity" aria-label="Profile identity">
      <Artwork url={shown.artworkUrl} name={shown.name} kind={shown.kind} large/>
      <div className="identity-main"><span className="eyebrow">{shown.kind === 'creators' ? 'YouTube creator' : 'Steam game'}</span><h1 ref={heading} tabIndex={-1}>{shown.name}</h1><span className="source-id">{shown.sourceId}</span></div>
      {shown.canonicalUrl && <button className="button secondary source-button" onClick={() => void openSource(shown.canonicalUrl)}>Open {shown.kind === 'creators' ? 'channel' : 'store'}<Icon name="external"/></button>}
      <div className="profile-metrics">{shown.kind === 'creators' && <div><span>Subscribers</span><strong>{shown.subscribers === null ? 'Not available' : new Intl.NumberFormat('en').format(shown.subscribers)}</strong></div>}<div><span>Analyzed</span><strong>{analyzedDate(shown.updatedAt)}</strong></div>{shown.favorite && <div><span>Collection</span><strong><Icon name="collection"/>Saved</strong></div>}</div>
    </section>
    {externalError && <ErrorNotice error={externalError}/>}
    {error ? <ErrorNotice error={error} onRetry={() => setAttempt(previous => previous + 1)}/> : !profile ? <Loading label="Loading profile…"/> : <>
      <div className="detail-overview">
        <section className="profile-brief" aria-label="Overview"><h2>Overview</h2><p className="profile-summary">{profile.summary || 'No summary recorded.'}</p>{profile.tags.length > 0 && <ul className="tags" aria-label="Tags">{profile.tags.map((tag, index) => <li key={`${tag}-${index}`}>{tag}</li>)}</ul>}{profile.manualNotes && <div className="manual-notes"><h3>Workspace notes</h3><p>{profile.manualNotes}</p></div>}</section>
        {profile.kind === 'creators' && <section className="contact-section" aria-label="Contacts"><h2>Contacts <span className="count">{profile.contacts.length}</span></h2>{profile.contacts.length ? <ul className="contacts">{profile.contacts.map((contact, index) => <li key={`${contact.email}-${index}`}><strong className="contact-email">{contact.email}</strong><div className="contact-meta"><span className="small-badge">{contact.purpose || 'Purpose not recorded'}</span><span>{friendlyLabel(contact.validationState)}</span></div><div className="contact-source">{contact.sourceUrl ? <button className="text-button" onClick={() => void openSource(contact.sourceUrl!)}>{friendlyLabel(contact.source)}<Icon name="external"/></button> : <span>{friendlyLabel(contact.source)}</span>}</div></li>)}</ul> : <p className="muted">No contacts recorded.</p>}</section>}
      </div>
      <section className="profile-records" aria-label="Profile records"><h2>Profile records</h2>{profile.groups.filter(group => Object.keys(group.data).length > 0).map(group => <details className="record-group" key={group.id}><summary>{group.label}</summary><div className="record-content"><FieldValue value={group.data}/></div></details>)}<details className="record-group source-record"><summary>All source fields</summary><div className="record-content"><FieldValue value={profile.raw}/></div></details></section>
    </>}
  </div>;
}
