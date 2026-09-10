import { useEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import type { ContactDetail, CreatorDetail, OtherContact, WorkDetail } from '../../../shared/creators';
import { Artwork, ErrorNotice, friendlyLabel, Icon } from '../Primitives';
import { CreatorContacts } from './CreatorContacts';
import { CreatorWorks } from './CreatorWorks';
import {CreatorInvitationHistory} from './CreatorInvitationHistory';
import './creatorRecord.css';
import {AnalysisInsights} from '../analyze/AnalysisInsights';

type Section = 'profile' | 'emails' | 'works';
type RecordPage = 'profile' | 'invitations';

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
  backLabel?: string;
  onEdit: (target: { kind: 'creator' | 'contact' | 'work' | 'identity'; base?: ContactDetail | WorkDetail }) => void;
  refreshToken?: number;
  initialSection?: Section | 'invitations';
  invitationActivityId?: string;
  onAnalyze?:()=>void;
  onBindYouTube?:()=>void;
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

export function CreatorRecord({ api, creator, onBack, backLabel='Back to creators', onEdit,onAnalyze,onBindYouTube, invitationActivityId, refreshToken = 0, initialSection = 'profile' }: CreatorRecordProps) {
  const [recordPage,setRecordPage]=useState<RecordPage>(initialSection==='invitations'?'invitations':'profile');
  const [emailsOpen,setEmailsOpen]=useState(initialSection==='emails');
  const [worksOpen,setWorksOpen]=useState(initialSection==='works');
  const pageTabs=useRef(new Map<RecordPage,HTMLButtonElement>());
  const [headerError, setHeaderError] = useState<PublicError | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const focusedCreatorId = useRef<string | null>(null);
  const name = creatorName(creator);
  useEffect(() => {
    if (focusedCreatorId.current === creator.id) return;
    focusedCreatorId.current = creator.id;
    title.current?.focus({ preventScroll: true });
  }, [creator.id]);
  async function openProfile() {
    if (!safeHTTPS(creator.profile_url)) return;
    setHeaderError(null);
    try { const result = await api.openExternal(creator.profile_url); if (!result.ok) setHeaderError(result.error); }
    catch { setHeaderError({ code: 'open_failed', message: 'This profile link could not be opened.', retryable: false }); }
  }
  return <article className="creator-record">
    <button className="text-button back-button" onClick={onBack}><Icon name="arrow"/>{backLabel}</button>
    <header className="creator-record-header"><Artwork url={creator.avatar_url} name={name} kind="creators" large/><div className="creator-record-title"><span className="eyebrow">{friendlyLabel(creator.platform)} creator</span><h1 ref={title} tabIndex={-1}>{name}</h1>{creator.handle && <p>{creator.handle}</p>}</div><div className="creator-header-actions">{safeHTTPS(creator.profile_url) && <button className="button secondary" onClick={() => void openProfile()}>Open profile<Icon name="external"/></button>}{onAnalyze&&<button className="button secondary" onClick={onAnalyze}>Analyze creator</button>}{onBindYouTube&&<button className="button secondary" onClick={onBindYouTube}>Bind YouTube channel</button>}</div><dl className="creator-headline-metrics"><div><dt>Followers</dt><dd>{creator.follower_count === null ? 'Followers unknown' : new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(creator.follower_count)}</dd></div><div><dt>Known works</dt><dd>{creator.work_count.toLocaleString('en')}</dd></div></dl></header>
    {headerError && <ErrorNotice error={headerError}/>} 
    <div className="creator-tabs" role="tablist" aria-label="Creator record sections">{(['profile','invitations'] as const).map(page=><button key={page} ref={node=>{if(node)pageTabs.current.set(page,node);else pageTabs.current.delete(page);}} role="tab" id={`creator-page-tab-${page}`} aria-controls={`creator-page-${page}`} aria-selected={recordPage===page} tabIndex={recordPage===page?0:-1} onClick={()=>setRecordPage(page)} onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?'profile':event.key==='End'?'invitations':page==='profile'?'invitations':'profile';setRecordPage(next);pageTabs.current.get(next)?.focus();}}>{page==='profile'?'Profile':'Invitations'}</button>)}</div>
    <div role="tabpanel" id="creator-page-profile" aria-labelledby="creator-page-tab-profile" hidden={recordPage!=='profile'}>
    <div className="creator-information-layout">
      <aside className="creator-resource-groups" aria-label="Contact and work records">
        <details className="creator-resource-group" open={emailsOpen} onToggle={event=>setEmailsOpen(event.currentTarget.open)}>
          <summary role="button" aria-label="Emails" aria-expanded={emailsOpen} aria-controls="creator-email-records"><strong>Emails <span className="count">{creator.contacts.length}</span></strong>{!emailsOpen&&<span>{creator.contacts.find(contact=>contact.is_current_identity&&contact.is_active)?.email??'No current email'}</span>}</summary>
          <div id="creator-email-records"><CreatorContacts api={api} contacts={creator.contacts} onEdit={onEdit}/></div>
        </details>
        <details className="creator-resource-group" open={worksOpen} onToggle={event=>setWorksOpen(event.currentTarget.open)}>
          <summary role="button" aria-label="Known works" aria-expanded={worksOpen} aria-controls="creator-work-records"><strong>Known works <span className="count">{creator.work_count.toLocaleString('en')}</span></strong>{!worksOpen&&<span>{creator.recent_works?.[0]?.work_name||creator.recent_works?.[0]?.content_title||'Saved work records'}</span>}</summary>
          <div id="creator-work-records"><CreatorWorks api={api} creatorId={creator.id} identityRevision={creator.source_identity.revision} active={recordPage==='profile'&&worksOpen} onEdit={onEdit} refreshToken={refreshToken}/></div>
        </details>
      </aside>
      <div className="creator-information-main"><Profile api={api} creator={creator} onEdit={onEdit}/><AnalysisInsights brief={creator.brief} analysis={creator.analysis} sourceStatus={creator.source_status}/></div>
    </div>
    </div>
    <div role="tabpanel" id="creator-page-invitations" aria-labelledby="creator-page-tab-invitations" hidden={recordPage!=='invitations'}><CreatorInvitationHistory key={creator.id} api={api.collaboration} creatorId={creator.id} initialActivityId={invitationActivityId} active={recordPage==='invitations'} embedded/></div>
  </article>;
}
