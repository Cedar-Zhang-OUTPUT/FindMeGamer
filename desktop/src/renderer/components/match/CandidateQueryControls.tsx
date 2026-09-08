import type { CandidateEvidenceFilter, CandidateQueryOptions, CandidateSort } from '../../../shared/match';

type RequiredCandidateOptions = Required<CandidateQueryOptions>;

const EVIDENCE_OPTIONS: { value: CandidateEvidenceFilter; label: string }[] = [
  { value: 'all', label: 'All evidence' },
  { value: 'current_game', label: 'Current game' },
  { value: 'reference_game', label: 'Reference games' },
  { value: 'related_content', label: 'Other recorded content' },
  { value: 'none', label: 'Evidence unknown' },
];
const SORT_OPTIONS: { value: CandidateSort; label: string }[] = [
  { value: 'relevance', label: 'Relevance' },
  { value: 'followers', label: 'Followers' },
  { value: 'recent_publish', label: 'Recently published' },
  { value: 'recent_added', label: 'Recently added' },
];

export function CandidateQueryControls({ value, filteredTotal, queryTotal, current, loading, disabled = false, onChange }: {
  value: RequiredCandidateOptions;
  filteredTotal: number;
  queryTotal: number;
  current: boolean;
  loading: boolean;
  disabled?: boolean;
  onChange: (next: RequiredCandidateOptions) => void;
}) {
  const previous = `${filteredTotal} previous candidate result${filteredTotal === 1 ? '' : 's'}`;
  const count = current
    ? `${filteredTotal} matching of ${queryTotal} discovered`
    : loading ? `Refreshing filtered results · ${previous}` : `Filtered results unavailable · ${previous}`;
  return <div className="candidate-query-controls" aria-label="Candidate filters and order">
    <div className="candidate-query-fields">
      <label>Evidence<select aria-label="Evidence" disabled={disabled} value={value.evidence} onChange={event => onChange({ ...value, evidence: event.target.value as CandidateEvidenceFilter })}>
        {EVIDENCE_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select></label>
      <label>Order<select aria-label="Order" disabled={disabled} value={value.sort} onChange={event => onChange({ ...value, sort: event.target.value as CandidateSort })}>
        {SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select></label>
    </div>
    <span className="candidate-query-count" role="status">{count}</span>
  </div>;
}
