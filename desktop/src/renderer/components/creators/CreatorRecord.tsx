import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import type { ContactDetail, CreatorDetail, OtherContact, WorkDetail } from '../../../shared/creators';
import { Artwork, ErrorNotice, friendlyLabel, Icon } from '../Primitives';
import { CreatorContacts } from './CreatorContacts';
import { CreatorWorks } from './CreatorWorks';
import './creatorRecord.css';

type Section = 'profile' | 'emails' | 'works';
const sections: { id: Section; label: string }[] = [{ id: 'profile', label: 'Profile' }, { id: 'emails', label: 'Emails' }, { id: 'works', label: 'Known works' }];

function safeHTTPS(value: string | null): value is string {
  if (!value) return false;
  try { const url = new URL(value); return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password; }
  catch { return false; }
}
function creatorName(creator: CreatorDetail) { return creator.name || creator.public_name || creator.handle || creator.source_identity.account_id || 'Unnamed creator'; }

function OtherContactItem({ contact, onOpen }: { contact: OtherContact; onOpen: (url: string) => void }) {
  return <li><span><strong>{contact.label || 'Contact'}</strong>{contact.value}</span>{safeHTTPS(contact.url) && <button className="text-button" onClick={() => onOpen(contact.url!)}>Open<Icon name="external"/></button>}</li>;
}

export interface CreatorRecordProps {
  api: DesktopBridge;
  creator: CreatorDetail;
  onBack: () => void;
  onEdit: (target: { kind: 'creator' | 'contact' | 'work' | 'identity'; base?: ContactDetail | WorkDetail }) => void;
  refreshToken?: number;
  initialSection?: Section;
}

function Profile({ api, creator, onEdit }: { api: DesktopBridge; creator: CreatorDetail; onEdit: CreatorRecordProps['onEdit'] }) {
  const [externalError, setExternalError] = useState<PublicError | null>(null);
  async function open(url: string) {
    if (!safeHTTPS(url)) return;
    setExternalError(null);
    try { const result = await api.openExternal(url); if (!result.ok) setExternalError(result.error); }
    catch { setExternalError({ code: 'open_failed', message: 'This profile link could not be opened.', retryable: false }); }
  }
  const identity = creator.source_identity;
  const unavailable = identity.platform === 'twitch' || identity.platform === 'instagram';
  return <section className="creator-section creator-profile" aria-labelledby="creator-profile-heading">
    {externalError && <ErrorNotice error={externalError}/>} 
    <section className="creator-profile-card" aria-labelledby="creator-profile-heading"><div className="creator-section-heading creator-profile-heading"><div><h2 className="sr-only" id="creator-profile-heading">Profile</h2>{creator.description && <p>{creator.description}</p>}</div><button className="button primary" onClick={() => onEdit({ kind: 'creator' })}>Edit profile</button></div>{(creator.public_name || creator.languages.length > 0 || creator.country_name || creator.country_code) && <dl className="creator-detail-grid creator-audience">{creator.public_name && <div><dt>Public name</dt><dd>{creator.public_name}<span className="muted creator-confirmation">{creator.public_name_confirmed ? 'Public name confirmed' : 'Public name not confirmed'}</span></dd></div>}{creator.languages.length > 0 && <div><dt>Languages</dt><dd>{creator.languages.join(', ')}</dd></div>}{(creator.country_name || creator.country_code) && <div><dt>Country</dt><dd>{creator.country_name || creator.country_code}</dd></div>}</dl>}</section>
    <details className="creator-account creator-disclosure"><summary aria-label="Account identity"><strong><Icon name="chevron" className="creator-disclosure-chevron"/>Account identity</strong><span>{friendlyLabel(identity.platform)}{unavailable ? ' · Manual metadata' : ''}</span></summary><div className="creator-disclosure-body"><div className="creator-disclosure-actions"><button className="button secondary" onClick={() => onEdit({ kind: 'identity' })}>Change identity</button></div><dl className="creator-detail-grid"><div><dt>Platform</dt><dd>{friendlyLabel(identity.platform)}</dd></div>{identity.account_id && <div><dt>Source account ID</dt><dd>{identity.account_id}</dd></div>}{creator.profile_url && <div><dt>Homepage</dt><dd className="creator-raw-value">{creator.profile_url}</dd></div>}{creator.handle && <div><dt>Handle</dt><dd>{creator.handle}</dd></div>}{identity.canonical_url && <div><dt>Source canonical URL</dt><dd className="creator-raw-value">{identity.canonical_url}</dd></div>}<div><dt>Identity revision</dt><dd>{identity.revision}</dd></div></dl></div></details>
    {(creator.interest_notes || creator.internal_notes || creator.source_notes) && <section className="creator-notes" aria-labelledby="creator-notes-heading"><h2 id="creator-notes-heading">Notes</h2><dl className="creator-detail-grid">{creator.interest_notes && <div><dt>Audience fit</dt><dd>{creator.interest_notes}</dd></div>}{creator.internal_notes && <div><dt>Workspace notes</dt><dd>{creator.internal_notes}</dd></div>}{creator.source_notes && <div><dt>Source notes</dt><dd>{creator.source_notes}</dd></div>}</dl></section>}
    {creator.other_contacts.length > 0 && <section className="creator-other-contacts" aria-labelledby="creator-other-contacts-heading"><h2 id="creator-other-contacts-heading">Other contacts</h2><ul>{creator.other_contacts.map((contact, index) => <OtherContactItem contact={contact} onOpen={url => void open(url)} key={`${contact.label}-${contact.value}-${index}`}/>)}</ul></section>}
    <details className="creator-provenance"><summary>Profile source details</summary><div className="creator-provenance-grid"><div><h4>Source fields</h4><pre>{JSON.stringify(creator.source_fields, null, 2)}</pre></div><div><h4>Manual overrides</h4><pre>{JSON.stringify(creator.manual_overrides, null, 2)}</pre></div></div></details>
  </section>;
}

export function CreatorRecord({ api, creator, onBack, onEdit, refreshToken = 0, initialSection = 'profile' }: CreatorRecordProps) {
  const [section, setSection] = useState<Section>(initialSection);
  const [headerError, setHeaderError] = useState<PublicError | null>(null);
  const tabs = useRef(new Map<Section, HTMLButtonElement>());
  const title = useRef<HTMLHeadingElement>(null);
  const focusedCreatorId = useRef<string | null>(null);
  const name = creatorName(creator);
  useEffect(() => {
    if (focusedCreatorId.current === creator.id) return;
    focusedCreatorId.current = creator.id;
    title.current?.focus({ preventScroll: true });
  }, [creator.id]);
  function choose(next: Section, focus = false) { setSection(next); if (focus) tabs.current.get(next)?.focus({ preventScroll: true }); }
  function keyNavigation(event: KeyboardEvent, current: Section) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = sections.findIndex(item => item.id === current);
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? sections.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + sections.length) % sections.length;
    choose(sections[nextIndex].id, true);
  }
  async function openProfile() {
    if (!safeHTTPS(creator.profile_url)) return;
    setHeaderError(null);
    try { const result = await api.openExternal(creator.profile_url); if (!result.ok) setHeaderError(result.error); }
    catch { setHeaderError({ code: 'open_failed', message: 'This profile link could not be opened.', retryable: false }); }
  }
  return <article className="creator-record">
    <button className="text-button back-button" onClick={onBack}><Icon name="arrow"/>Back to creators</button>
    <header className="creator-record-header"><Artwork url={creator.avatar_url} name={name} kind="creators" large/><div className="creator-record-title"><span className="eyebrow">{friendlyLabel(creator.platform)} creator</span><h1 ref={title} tabIndex={-1}>{name}</h1>{creator.handle && <p>{creator.handle}</p>}</div><div className="creator-header-actions">{safeHTTPS(creator.profile_url) && <button className="button secondary" onClick={() => void openProfile()}>Open profile<Icon name="external"/></button>}</div><dl className="creator-headline-metrics"><div><dt>Followers</dt><dd>{creator.follower_count === null ? 'Followers unknown' : new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(creator.follower_count)}</dd></div><div><dt>Known works</dt><dd>{creator.work_count.toLocaleString('en')}</dd></div></dl></header>
    {headerError && <ErrorNotice error={headerError}/>} 
    <div className="creator-tabs" role="tablist" aria-label="Creator record sections">{sections.map(item => <button key={item.id} ref={node => { if (node) tabs.current.set(item.id, node); else tabs.current.delete(item.id); }} type="button" role="tab" id={`creator-tab-${item.id}`} aria-controls={`creator-panel-${item.id}`} aria-selected={section === item.id} tabIndex={section === item.id ? 0 : -1} onClick={() => choose(item.id)} onKeyDown={event => keyNavigation(event, item.id)}>{item.label}</button>)}</div>
    <div role="tabpanel" id="creator-panel-profile" aria-labelledby="creator-tab-profile" hidden={section !== 'profile'}><Profile api={api} creator={creator} onEdit={onEdit}/></div>
    <div role="tabpanel" id="creator-panel-emails" aria-labelledby="creator-tab-emails" hidden={section !== 'emails'}><CreatorContacts api={api} contacts={creator.contacts} onEdit={onEdit}/></div>
    <div role="tabpanel" id="creator-panel-works" aria-labelledby="creator-tab-works" hidden={section !== 'works'}><CreatorWorks api={api} creatorId={creator.id} identityRevision={creator.source_identity.revision} active={section === 'works'} onEdit={onEdit} refreshToken={refreshToken}/></div>
  </article>;
}
