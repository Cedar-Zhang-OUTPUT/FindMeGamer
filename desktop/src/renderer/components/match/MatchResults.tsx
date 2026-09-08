import type { CandidateSort, CandidateView, EvaluationResult, KnownEvaluationEvidence } from '../../../shared/match';
import type { JsonObject, JsonValue } from '../../../shared/library';
import { analyzedDate, Artwork, EmptyState, friendlyLabel, Icon, Loading } from '../Primitives';
import './matchResults.css';

type CreatorSection = 'overview' | 'contacts' | 'works';
type OpenCreator = (id: string, section?: CreatorSection) => void;
export interface CandidateOutreachControl {isSelected:(candidate:CandidateView)=>boolean;disabled:boolean;onToggle:(candidate:CandidateView)=>void}

interface CandidateResultsProps {
  candidates: CandidateView[];
  total: number;
  loading: boolean;
  stale?: boolean;
  sort?: CandidateSort;
  onLoadMore: () => void;
  onOpenCreator: OpenCreator;
  selection?: { ids: readonly string[]; disabled: boolean; onToggle:(id:string)=>void };
  outreach?:CandidateOutreachControl;
}

interface EvaluationResultsProps {
  results: EvaluationResult[];
  total: number;
  loading: boolean;
  onLoadMore: () => void;
  onOpenCreator: OpenCreator;
  onOpenExternal?: (url: string) => void;
}

const NUMBER_FORMAT = new Intl.NumberFormat('en');
const PLATFORM_NAMES: Record<string, string> = { youtube: 'YouTube', x: 'X', twitch: 'Twitch', instagram: 'Instagram' };
const FIT_GROUP_NAMES: Record<EvaluationResult['fit_group'], string> = {
  strong_fit: 'Strong fit', potential_fit: 'Potential fit', limited_fit: 'Limited fit', unranked: 'Unranked',
};

function textValue(value: JsonValue | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function numberValue(value: JsonValue | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function booleanValue(value: JsonValue | undefined): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function stringList(value: JsonValue | undefined): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())) : [];
}

function platformName(value: string): string {
  return PLATFORM_NAMES[value.toLocaleLowerCase()] || friendlyLabel(value);
}

function safeHTTPS(value: string | null): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password;
  } catch { return false; }
}

function creatorName(candidate: CandidateView): string {
  const creator = candidate.creator;
  return creator?.name || creator?.public_name || creator?.handle || creator?.source_identity.account_id || 'Current creator';
}

function snapshotName(candidate: CandidateView): string {
  return textValue(candidate.account.display_name) || textValue(candidate.account.handle) || candidate.account_id;
}

function formatDuration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return null;
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = whole % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
    : `${minutes}:${String(remainder).padStart(2, '0')}`;
}

function CandidateDetails({ candidate }: { candidate: CandidateView }) {
  const account = candidate.account;
  const filterNotes = candidate.filter_notes;
  const unknownFields = stringList(filterNotes.unknown_fields);
  const pendingCountries = stringList(filterNotes.pending_country_labels);
  const failedFilters = stringList(filterNotes.failed_filters);
  const contactAvailable = booleanValue(filterNotes.contact_available);
  const evidenceStatus = textValue(filterNotes.evidence_status);
  const description = textValue(account.description);
  const handle = textValue(account.handle);
  const profileURL = textValue(account.profile_url);
  const location = textValue(account.location_text);
  const collectedAt = textValue(account.collected_at);
  const metadataComplete = booleanValue(account.metadata_complete);

  return <details className="match-details">
    <summary>Discovery details</summary>
    <div className="match-details-body">
      <section aria-label="Discovered account snapshot">
        <h4>Discovered account snapshot</h4>
        {description ? <p className="match-detail-copy">{description}</p> : null}
        <dl className="match-detail-grid">
          <div><dt>Source account ID</dt><dd>{candidate.account_id}</dd></div>
          <div><dt>Identity revision</dt><dd>{candidate.identity_revision}</dd></div>
          {handle ? <div><dt>Handle</dt><dd>{handle}</dd></div> : null}
          {location ? <div><dt>Source location text</dt><dd>{location}</dd></div> : null}
          {collectedAt ? <div><dt>Discovered</dt><dd>{analyzedDate(collectedAt)}</dd></div> : null}
          {metadataComplete !== null ? <div><dt>Snapshot metadata</dt><dd>{metadataComplete ? 'Complete' : 'Partial'}</dd></div> : null}
          {profileURL ? <div><dt>Source profile</dt><dd className="match-raw-value">{profileURL}</dd></div> : null}
        </dl>
      </section>
      <section aria-label="Filter notes">
        <h4>Filter notes</h4>
        <div className="match-note-groups">
          {unknownFields.length > 0 ? <div><strong>Unknown fields</strong><ul className="match-inline-list">{unknownFields.map(value => <li key={value}>{friendlyLabel(value)}</li>)}</ul></div> : null}
          {pendingCountries.length > 0 ? <div><strong>Unconfirmed country labels</strong><ul className="match-inline-list">{pendingCountries.map(value => <li key={value}>{value}</li>)}</ul></div> : null}
          {failedFilters.length > 0 ? <div><strong>Filter issues</strong><ul className="match-inline-list">{failedFilters.map(value => <li key={value}>{friendlyLabel(value)}</li>)}</ul></div> : null}
          {contactAvailable !== null ? <span className="match-note-chip">{contactAvailable ? 'Contact available' : 'No valid active email recorded'}</span> : null}
          {evidenceStatus ? <span className="match-note-chip">{friendlyLabel(evidenceStatus)} discovery evidence</span> : null}
        </div>
      </section>
      <section aria-label="Current Library record">
        <h4>Current Library record</h4>
        {candidate.creator ? <div className="match-current-record"><span><strong>{creatorName(candidate)}</strong><small>{platformName(candidate.creator.source_identity.platform)} · {candidate.creator.source_identity.account_id}</small></span></div> : <p className="muted">Current creator record unavailable.</p>}
      </section>
    </div>
  </details>;
}

const CANDIDATE_EVIDENCE_NAMES: Record<NonNullable<CandidateView['evidence_groups']>[number], string> = {
  current_game: 'Current game evidence', reference_game: 'Reference game evidence', related_content: 'Other recorded content',
};

function CandidateEvidence({ candidate, sort }: { candidate: CandidateView; sort?: CandidateSort }) {
  const groups = candidate.evidence_groups;
  const relevance = sort === 'relevance' && candidate.relevance_status
    ? candidate.relevance_status === 'available' ? 'Relevance available'
      : candidate.relevance_status === 'stale' ? 'Relevance outdated' : 'Relevance unavailable'
    : null;
  if (groups === undefined && !relevance) return null;
  return <div className="match-candidate-evidence" aria-label="Candidate evidence">
    {groups?.length ? groups.map(group => <span className="match-note-chip" key={group}>{CANDIDATE_EVIDENCE_NAMES[group]}</span>)
      : groups ? <span className="match-note-chip">Evidence unknown</span> : null}
    {relevance ? <span className={`match-note-chip relevance ${candidate.relevance_status}`}>{relevance}</span> : null}
  </div>;
}

function CandidateCard({ candidate, onOpenCreator, sort, selection, outreach }: { candidate: CandidateView; onOpenCreator: OpenCreator; sort?: CandidateSort; selection?:CandidateResultsProps['selection'];outreach?:CandidateOutreachControl }) {
  const account = candidate.account;
  const name = snapshotName(candidate);
  const handle = textValue(account.handle);
  const avatar = textValue(account.avatar_url);
  const country = textValue(account.country);
  const followers = numberValue(account.follower_count);

  return <article className="match-card match-candidate-card" aria-label={name}>
    {selection&&<label className="saved-list-mark"><input type="checkbox" aria-label={`Include ${name} in saved list`} checked={selection.ids.includes(candidate.id)} disabled={selection.disabled||(!selection.ids.includes(candidate.id)&&selection.ids.length>=600)} onChange={()=>selection.onToggle(candidate.id)}/>Mark for list</label>}
    {!selection&&outreach&&<label className="saved-list-mark"><input type="checkbox" aria-label={`Select ${name} for outreach`} checked={outreach.isSelected(candidate)} disabled={outreach.disabled||candidate.identity_changed} onChange={()=>outreach.onToggle(candidate)}/>Selected for outreach</label>}
    <header className="match-card-header">
      <Artwork url={avatar} name={name} kind="creators"/>
      <div className="match-card-title"><h3>{name}</h3>{handle && handle !== name ? <p>{handle}</p> : null}</div>
      <div className="match-card-actions">{candidate.identity_changed ? <span className="match-badge warning">Account changed</span> : null}{candidate.creator ? <button className="button secondary" onClick={() => onOpenCreator(candidate.creator_id, 'overview')}>{candidate.identity_changed ? 'View current creator' : 'View creator'}</button> : null}</div>
    </header>
    <CandidateEvidence candidate={candidate} sort={sort}/>
    <dl className="match-quick-facts">
      <div><dt>Platform</dt><dd>{platformName(candidate.platform)}</dd></div>
      <div><dt>Country</dt><dd>{country || 'Country unknown'}</dd></div>
      <div><dt>Followers</dt><dd>{followers === null ? 'Followers unknown' : `${NUMBER_FORMAT.format(followers)} followers`}</dd></div>
    </dl>
    {candidate.identity_changed ? <div className="match-identity-warning">This result belongs to the discovered account {candidate.account_id}; treat the current Library identity separately.</div> : null}
    <CandidateDetails candidate={candidate}/>
  </article>;
}

function ResultsFooter({ kind, shown, total, loading, onLoadMore }: { kind: 'candidates' | 'evaluations'; shown: number; total: number; loading: boolean; onLoadMore: () => void }) {
  const hasMore = shown < total;
  return <footer className="match-results-footer">
    <span>{shown} of {NUMBER_FORMAT.format(total)} {kind}</span>
    {hasMore ? <button className="button secondary" disabled={loading} onClick={onLoadMore}>{loading ? `Loading more ${kind}…` : `Load more ${kind}`}</button> : null}
    {loading && !hasMore ? <span role="status">Refreshing {kind}…</span> : null}
  </footer>;
}

export function CandidateResults({ candidates, total, loading, stale = false, sort, onLoadMore, onOpenCreator, selection,outreach }: CandidateResultsProps) {
  if (candidates.length === 0) return loading ? <Loading label="Loading candidates…"/> : <EmptyState title="No candidates found" icon="match"/>;
  return <section className="match-results" aria-label="Candidate results">
    {stale ? <p className="match-stale-results" role="status">Showing {candidates.length} previous candidate result{candidates.length === 1 ? '' : 's'} while the new filter loads.</p> : null}
    <ul className="match-result-list">{candidates.map(candidate => <li key={candidate.id}><CandidateCard candidate={candidate} sort={sort} onOpenCreator={onOpenCreator} selection={selection} outreach={outreach}/></li>)}</ul>
    {stale ? null : <ResultsFooter kind="candidates" shown={candidates.length} total={total} loading={loading} onLoadMore={onLoadMore}/>}
  </section>;
}

function evidenceLabel(status: EvaluationResult['evidence_status']): string {
  if (status === 'recorded_evidence') return 'Recorded evidence · sender viewing not confirmed';
  if (status === 'metadata_only') return 'Metadata only';
  return 'No recorded evidence';
}

function EvidenceItem({ evidence, onOpenExternal }: { evidence: KnownEvaluationEvidence; onOpenExternal?: (url: string) => void }) {
  const title = evidence.content_title || 'Untitled work record';
  const timestamp = formatDuration(evidence.timestamp_seconds);
  const canOpen = Boolean(onOpenExternal) && safeHTTPS(evidence.source_url);
  return <li className="match-evidence-item">
    <div><strong>{title}</strong><span>{friendlyLabel(evidence.relation)} · {evidence.status === 'recorded_evidence' ? 'Recorded evidence' : 'Metadata only'}{timestamp ? ` · ${timestamp}` : ''}</span></div>
    {canOpen ? <button className="text-button" aria-label={`Open source for ${title}`} onClick={() => onOpenExternal!(evidence.source_url!)}>Open source<Icon name="external"/></button> : null}
  </li>;
}

function EvaluationDetails({ result, onOpenCreator, onOpenExternal }: { result: EvaluationResult; onOpenCreator: OpenCreator; onOpenExternal?: (url: string) => void }) {
  const brief = result.match_brief;
  if (!brief && result.evidence.length === 0) return null;
  return <details className="match-details match-evaluation-details">
    <summary>Fit and evidence</summary>
    <div className="match-details-body">
      {brief ? <div className="match-brief-details">
        <section><h4>Content fit</h4><p>{brief.content_fit}</p></section>
        <section><h4>Audience fit</h4><p>{brief.audience_fit}</p></section>
        <section><h4>Limitations</h4><ul>{brief.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul></section>
      </div> : null}
      {result.evidence.length > 0 ? <section className="match-evidence" aria-label="Recorded work evidence"><div className="match-evidence-heading"><h4>Work records</h4><button className="text-button" onClick={() => onOpenCreator(result.creator_id, 'works')}>{result.identity_changed ? 'View current creator works' : 'View known works'}<Icon name="chevron"/></button></div><ul>{result.evidence.map(item => <EvidenceItem key={item.work_id} evidence={item} onOpenExternal={onOpenExternal}/>)}</ul></section> : null}
    </div>
  </details>;
}

function EvaluationCard({ result, onOpenCreator, onOpenExternal }: { result: EvaluationResult; onOpenCreator: OpenCreator; onOpenExternal?: (url: string) => void }) {
  const name = result.name || result.account_id;
  return <article className="match-card match-evaluation-card" aria-label={name}>
    <header className="match-card-header evaluation">
      <div className="match-card-title"><span className="eyebrow">{platformName(result.platform)} account</span><h3>{name}</h3><p>{result.account_id}</p></div>
      <div className="match-card-badges">
        <span className={`match-badge fit ${result.fit_group}`}>{FIT_GROUP_NAMES[result.fit_group]}</span>
        <span className={`match-badge evidence ${result.evidence_status}`}>{evidenceLabel(result.evidence_status)}</span>
        {result.stale ? <span className="match-badge warning">Outdated</span> : null}
        {result.identity_changed ? <span className="match-badge warning">Account changed</span> : null}
        {result.needs_enrichment ? <span className="match-badge neutral">Needs enrichment</span> : null}
      </div>
      <button className="text-button" onClick={() => onOpenCreator(result.creator_id, 'overview')}>View current creator<Icon name="chevron"/></button>
    </header>
    {result.identity_changed ? <div className="match-identity-warning">This evaluation describes the frozen account {result.account_id}, not the current Library identity.</div> : null}
    {result.match_brief ? <p className="match-summary">{result.match_brief.summary}</p> : <p className="match-unavailable"><strong>Evaluation unavailable</strong><span>{friendlyLabel(result.status)}</span></p>}
    <EvaluationDetails result={result} onOpenCreator={onOpenCreator} onOpenExternal={onOpenExternal}/>
  </article>;
}

export function EvaluationResults({ results, total, loading, onLoadMore, onOpenCreator, onOpenExternal }: EvaluationResultsProps) {
  if (results.length === 0) return loading ? <Loading label="Loading evaluations…"/> : <EmptyState title="No evaluations available" icon="match"/>;
  return <section className="match-results" aria-label="Evaluation results">
    <ul className="match-result-list">{results.map(result => <li key={result.candidate_id}><EvaluationCard result={result} onOpenCreator={onOpenCreator} onOpenExternal={onOpenExternal}/></li>)}</ul>
    <ResultsFooter kind="evaluations" shown={results.length} total={total} loading={loading} onLoadMore={onLoadMore}/>
  </section>;
}
