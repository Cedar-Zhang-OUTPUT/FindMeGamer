import {SelectionActions,scopedSelection} from '../SelectionActions';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CreatorAPI, WorkDetail } from '../../../shared/creators';
import type { Preparation, PreparationContact, PreparationWork, SelectionUpdate } from '../../../shared/outreach';
import { analyzedDate, friendlyLabel } from '../Primitives';
import './preparationEditor.css';

export interface PreparationEditorProps {
  preparation: Preparation;
  creators: Pick<CreatorAPI, 'works'>;
  active: boolean;
  busy: boolean;
  current?: boolean;
  onSave: (data: SelectionUpdate) => Promise<boolean>;
  onOpenCreator: (id: string, section?: 'overview' | 'contacts' | 'works') => void;
  onOpenExternal: (url: string) => void;
  onRefresh: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  evaluationChoices?: ReadonlyArray<{ id: string; label: string }>;
}

type ContactChoice = 'none' | `current:${string}` | `observed:${string}`;
interface PreparationDraft {
  contact: ContactChoice;
  confirmPublicName: boolean;
  workIds: string[];
  evaluationRunId: string | null;
}
interface EditSession { observed: Preparation; draft: PreparationDraft }
interface WorkLoad {
  creatorId: string;
  items: WorkDetail[];
  total: number;
  nextOffset: number;
  loading: boolean;
  error: string | null;
  opened: boolean;
}

const WORK_PAGE_SIZE = 100;
const contactKey = (preparation: Preparation): ContactChoice => preparation.selected_contact
  ? preparation.contact_status === 'eligible' ? `current:${preparation.selected_contact.id}` : `observed:${preparation.selected_contact.id}`
  : 'none';
const preparationKey = (preparation: Preparation) => `${preparation.id}:${preparation.revision}:${preparation.context_token}`;
const unique = (values: string[]) => [...new Set(values)];
const same = (left: string[], right: string[]) => left.length === right.length && left.every((value, index) => value === right[index]);
const workName = (work: WorkDetail) => work.content_title || work.work_name || work.source_content_id || 'Untitled work';

function draftFrom(preparation: Preparation): PreparationDraft {
  return {
    contact: contactKey(preparation), confirmPublicName: preparation.public_name_confirmed,
    workIds: unique([...preparation.works.map(work => work.id), ...preparation.missing_work_ids]),
    evaluationRunId: preparation.evaluation_run_id,
  };
}

function draftChanged(observed: Preparation, draft: PreparationDraft): boolean {
  const initial = draftFrom(observed);
  return draft.contact !== initial.contact || draft.confirmPublicName !== initial.confirmPublicName
    || !same(draft.workIds, initial.workIds) || draft.evaluationRunId !== initial.evaluationRunId;
}

function payload(observed: Preparation, draft: PreparationDraft): SelectionUpdate {
  const initial = draftFrom(observed);
  const data: SelectionUpdate = { expected_revision: observed.revision, context_token: observed.context_token };
  if (draft.contact !== initial.contact) data.contact_id = draft.contact === 'none' ? null : draft.contact.slice(draft.contact.indexOf(':') + 1);
  if (draft.confirmPublicName !== initial.confirmPublicName) data.confirm_public_name = draft.confirmPublicName;
  if (!same(draft.workIds, initial.workIds)) data.work_ids = [...draft.workIds];
  if (draft.evaluationRunId !== initial.evaluationRunId) data.evaluation_run_id = draft.evaluationRunId;
  return data;
}

function safeHTTPS(value: string | null): value is string {
  if (!value) return false;
  try { const parsed = new URL(value); return parsed.protocol === 'https:' && Boolean(parsed.hostname) && !parsed.username && !parsed.password; }
  catch { return false; }
}

function contactMeta(contact: PreparationContact) {
  return `${contact.purpose || 'No purpose'} · ${friendlyLabel(contact.source_type)} · ${friendlyLabel(contact.status)}`;
}

function ContactSource({ contact, onOpenExternal }: { contact: PreparationContact; onOpenExternal: (url: string) => void }) {
  const sourceUrl = contact.source_url;
  return <details className="preparation-source"><summary>Source details for {contact.email}</summary><dl>
    <div><dt>Source</dt><dd>{friendlyLabel(contact.source_type)}</dd></div>
    <div><dt>Validation</dt><dd>{friendlyLabel(contact.validation_state)}</dd></div>
    <div><dt>Identity revision</dt><dd>{contact.identity_revision}</dd></div>
  </dl>{safeHTTPS(sourceUrl) ? <button type="button" className="text-button" aria-label={`Open source for ${contact.email}`} onClick={() => onOpenExternal(sourceUrl)}>Open source</button> : null}</details>;
}

function workRelation(work: WorkDetail | PreparationWork) {
  if (!('relation' in work)) return 'Known work';
  if (work.relation === 'related_content') return 'Other recorded content';
  return work.relation === 'current_game' ? 'Current game' : 'Reference game';
}

function workEvidence(work: WorkDetail | PreparationWork) {
  if ('evidence_status' in work) return work.evidence_status === 'recorded_evidence' ? 'Recorded evidence' : 'Metadata only';
  return work.evidence_excerpt && work.verification_notes ? 'Recorded evidence' : 'Metadata only';
}

function MissingChips({ fields }: { fields: string[] }) {
  if (!fields.length) return null;
  return <ul className="preparation-chips" aria-label="Missing preparation requirements">{fields.map(field => <li key={field}>{friendlyLabel(field)}</li>)}</ul>;
}

export function PreparationEditor({ preparation, creators, active, busy, current=true, onSave, onOpenCreator, onOpenExternal, onRefresh, onDirtyChange, evaluationChoices = [] }: PreparationEditorProps) {
  const [session, setSession] = useState<EditSession | null>(null);
  const [saving, setSaving] = useState(false), [awaitingKey, setAwaitingKey] = useState<string | null>(null);
  const [workLoad, setWorkLoad] = useState<WorkLoad | null>(null);
  const workRequest = useRef(0), alive = useRef(true), latestPreparation = useRef(preparation);
  latestPreparation.current = preparation;
  const observed = session?.observed ?? preparation, draft = session?.draft ?? draftFrom(preparation);
  const dirty = session ? draftChanged(session.observed, session.draft) : false;
  const changedContext = Boolean(session && preparationKey(session.observed) !== preparationKey(preparation));
  const disabled = !active || busy || !current || saving || awaitingKey !== null;

  useEffect(() => { alive.current = true; return () => { alive.current = false; workRequest.current += 1; }; }, []);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (awaitingKey && preparationKey(preparation) !== awaitingKey) { setSession(null); setAwaitingKey(null); }
  }, [awaitingKey, preparation.id, preparation.revision, preparation.context_token]);

  const changeDraft = useCallback((change: (draft: PreparationDraft) => PreparationDraft) => {
    setSession(current => {
      const base = current ?? { observed: latestPreparation.current, draft: draftFrom(latestPreparation.current) };
      const next = { observed: base.observed, draft: change(base.draft) };
      return draftChanged(next.observed, next.draft) ? next : null;
    });
  }, []);

  const loadWorks = useCallback(async (offset: number) => {
    if (!active || busy) return;
    const creatorId = latestPreparation.current.creator_id, sequence = ++workRequest.current;
    setWorkLoad(current => ({
      creatorId, items: offset && current?.creatorId === creatorId ? current.items : [], total: current?.creatorId === creatorId ? current.total : 0,
      nextOffset: offset, loading: true, error: null, opened: true,
    }));
    try {
      const result = await creators.works({ creatorId, limit: WORK_PAGE_SIZE, offset });
      if (!alive.current || sequence !== workRequest.current) return;
      if (!result.ok) {
        setWorkLoad(current => current?.creatorId === creatorId ? { ...current, loading: false, error: result.error.message } : current);
        return;
      }
      setWorkLoad(current => {
        if (current?.creatorId !== creatorId) return current;
        const items = offset ? [...current.items, ...result.data.items] : result.data.items;
        const byId = new Map(items.filter(item => item.is_current_identity).map(item => [item.id, item]));
        return { creatorId, items: [...byId.values()], total: result.data.total, nextOffset: result.data.offset + result.data.items.length, loading: false, error: null, opened: true };
      });
    } catch {
      if (alive.current && sequence === workRequest.current) setWorkLoad(current => current?.creatorId === creatorId ? { ...current, loading: false, error: 'Known works could not be loaded.' } : current);
    }
  }, [active, busy, creators]);

  async function save() {
    if (!session || !dirty || disabled) return;
    const submitted = session, submittedKey = preparationKey(submitted.observed);
    setSaving(true);
    let accepted = false;
    try { accepted = await onSave(payload(submitted.observed, submitted.draft)); } catch { accepted = false; }
    if (alive.current) {
      setSaving(false);
      if (accepted) {
        if (preparationKey(latestPreparation.current) !== submittedKey) setSession(null);
        else setAwaitingKey(submittedKey);
      }
    }
  }

  function discard(reload: boolean) {
    setSession(null); setAwaitingKey(null);
    if (reload) onRefresh();
  }

  const currentWorks = new Map<string, WorkDetail | PreparationWork>();
  observed.works.forEach(work => currentWorks.set(work.id, work));
  if (workLoad?.creatorId === observed.creator_id) workLoad.items.forEach(work => { if (!currentWorks.has(work.id)) currentWorks.set(work.id, work); });
  const missingIds = draft.workIds.filter(id => !currentWorks.has(id));
  const availableWorks = [...currentWorks.values()];
  const workListOpen = workLoad?.creatorId === observed.creator_id && workLoad.opened;
  const currentEvaluationListed = observed.evaluation_run_id !== null && evaluationChoices.some(choice => choice.id === observed.evaluation_run_id);

  return <section className="preparation-editor" aria-label="Preparation editor">
    <header className="preparation-heading"><div><h3>{observed.public_name || observed.name || observed.identity.account_id}</h3><span>{friendlyLabel(observed.identity.platform)} · {observed.identity.account_id}</span></div><div className="preparation-heading-actions"><button type="button" className="text-button" disabled={!active || busy || saving} onClick={onRefresh}>Refresh preparation</button><button type="button" className="text-button" disabled={!active} onClick={() => onOpenCreator(observed.creator_id, 'overview')}>View creator</button></div></header>
    <MissingChips fields={observed.missing_fields}/>
    {changedContext ? <div className="preparation-context-warning" role="status"><span><strong>Preparation changed</strong> Your edits still use the revision and context you observed.</span><button type="button" className="button secondary" disabled={saving || busy} onClick={() => discard(true)}>Discard edits and reload</button></div> : null}

    <fieldset className="preparation-group preparation-contacts" disabled={disabled}><legend>Email</legend>
      <label className="preparation-choice"><input type="radio" name={`preparation-contact-${observed.id}`} aria-label="None" checked={draft.contact === 'none'} onChange={() => changeDraft(value => ({ ...value, contact: 'none' }))}/><span><strong>None</strong><small>No address selected</small></span></label>
      {draft.contact.startsWith('observed:') && observed.selected_contact ? <label className="preparation-choice observed"><input type="radio" name={`preparation-contact-${observed.id}`} aria-label={`Saved version ${observed.selected_contact.email}`} checked disabled/><span><strong>{observed.selected_contact.email}</strong><small>Saved source · {friendlyLabel(observed.contact_status)}</small></span></label> : null}
      {observed.contact_options.map(contact => {
        const eligible = contact.status === 'eligible', changed = draft.contact.startsWith('observed:') && observed.selected_contact?.id === contact.id;
        const label = changed ? `Current version ${contact.email}` : contact.email;
        return <div className="preparation-contact" key={contact.id}><label className="preparation-choice"><input type="radio" name={`preparation-contact-${observed.id}`} aria-label={label} value={`current:${contact.id}`} checked={draft.contact === `current:${contact.id}`} disabled={!eligible || disabled} onChange={() => changeDraft(value => ({ ...value, contact: `current:${contact.id}` }))}/><span><strong>{contact.email}</strong><small>{contactMeta(contact)}</small></span></label><ContactSource contact={contact} onOpenExternal={onOpenExternal}/></div>;
      })}
      <button type="button" className="text-button preparation-library-link" disabled={!active} onClick={() => onOpenCreator(observed.creator_id, 'contacts')}>View email records</button>
    </fieldset>

    <section className="preparation-group" aria-labelledby={`preparation-name-${observed.id}`}><div className="preparation-group-heading"><h4 id={`preparation-name-${observed.id}`}>Public name</h4>{!observed.public_name ? <button type="button" className="text-button" disabled={!active} onClick={() => onOpenCreator(observed.creator_id, 'overview')}>Edit public name in Creator</button> : null}</div>
      {observed.public_name ? <label className="preparation-check"><input type="checkbox" aria-label={`Confirm “${observed.public_name}” as public name`} checked={draft.confirmPublicName} disabled={disabled} onChange={event => changeDraft(value => ({ ...value, confirmPublicName: event.target.checked }))}/><span>Confirm “{observed.public_name}” as the public name</span></label> : <span className="preparation-empty">No public name recorded</span>}
      <details className="preparation-source"><summary>Name details</summary><dl><div><dt>Saved account</dt><dd>{observed.identity.account_id}</dd></div><div><dt>Identity revision</dt><dd>{observed.identity.revision}</dd></div>{observed.name_confirmed_at ? <div><dt>Confirmed</dt><dd>{observed.name_confirmed_at}</dd></div> : null}</dl></details>
    </section>

    <section className="preparation-group preparation-works" aria-labelledby={`preparation-works-${observed.id}`}><div className="preparation-group-heading"><h4 id={`preparation-works-${observed.id}`}>Known works</h4><button type="button" className="button secondary" disabled={disabled || workListOpen} onClick={() => void loadWorks(0)}>Choose known works</button></div>
      <SelectionActions scope="Loaded works" count={availableWorks.length+missingIds.length} selected={draft.workIds.filter(id=>availableWorks.some(work=>work.id===id)||missingIds.includes(id)).length} disabled={disabled} limitExceeded={scopedSelection(draft.workIds,availableWorks.map(work=>work.id),true,100)===null} onSelect={()=>changeDraft(value=>({...value,workIds:scopedSelection(value.workIds,availableWorks.map(work=>work.id),true,100)??value.workIds}))} onClear={()=>changeDraft(value=>({...value,workIds:scopedSelection(value.workIds,[...availableWorks.map(work=>work.id),...missingIds],false)!}))}/>
      <div className="preparation-work-list">
        {availableWorks.map(work => <label className="preparation-work" key={work.id}><input type="checkbox" aria-label={`Use ${workName(work)}`} checked={draft.workIds.includes(work.id)} disabled={disabled || (!draft.workIds.includes(work.id) && draft.workIds.length >= 100)} onChange={event => changeDraft(value => ({ ...value, workIds: event.target.checked ? [...value.workIds, work.id] : value.workIds.filter(id => id !== work.id) }))}/><span><strong>{workName(work)}</strong><small><span>{workRelation(work)}</span><span>{workEvidence(work)}</span></small></span></label>)}
        {missingIds.map(id => <label className="preparation-work unavailable" key={id}><input type="checkbox" aria-label={`Keep unavailable work ${id}`} checked disabled={disabled} onChange={() => changeDraft(value => ({ ...value, workIds: value.workIds.filter(workId => workId !== id) }))}/><span><strong>Previously chosen work unavailable</strong><small>{id}</small></span></label>)}
      </div>
      {workLoad?.creatorId === observed.creator_id && workLoad.loading ? <span role="status">Loading known works…</span> : null}
      {workLoad?.creatorId === observed.creator_id && workLoad.error ? <div className="preparation-read-error" role="alert"><span>{workLoad.error}</span><button type="button" className="button secondary" disabled={disabled} onClick={() => void loadWorks(workLoad.nextOffset)}>Try works again</button></div> : null}
      {workLoad?.creatorId === observed.creator_id && !workLoad.loading && workLoad.nextOffset < workLoad.total ? <button type="button" className="button secondary" disabled={disabled} onClick={() => void loadWorks(workLoad.nextOffset)}>Load more works</button> : null}
      <button type="button" className="text-button preparation-library-link" disabled={!active} onClick={() => onOpenCreator(observed.creator_id, 'works')}>View all work records</button>
    </section>

    <section className="preparation-group" aria-labelledby={`preparation-evaluation-${observed.id}`}><h4 id={`preparation-evaluation-${observed.id}`}>Evaluation</h4>
      <label className="preparation-select"><span>Match brief</span><select aria-label="Match brief" value={draft.evaluationRunId ?? ''} disabled={disabled} onChange={event => changeDraft(value => ({ ...value, evaluationRunId: event.target.value || null }))}><option value="">None</option>{observed.evaluation_run_id && !currentEvaluationListed ? <option value={observed.evaluation_run_id}>Current saved evaluation</option> : null}{evaluationChoices.map(choice => <option value={choice.id} key={choice.id}>{choice.label}</option>)}</select></label>
      {observed.evaluation ? <><p className="preparation-evaluation-summary">{observed.evaluation.match_brief?.summary || friendlyLabel(observed.evaluation.fit_group)}</p><details className="preparation-source"><summary>Evaluation details</summary><dl><div><dt>Fit group</dt><dd>{friendlyLabel(observed.evaluation.fit_group)}</dd></div><div><dt>Evidence</dt><dd>{friendlyLabel(observed.evaluation.evidence_status)}</dd></div></dl></details></> : <span className="preparation-empty">No evaluation selected</span>}
    </section>

    <footer className="preparation-actions"><button type="button" className="text-button" disabled={!dirty || saving || busy} onClick={() => discard(false)}>Cancel changes</button><button type="button" className="button primary" disabled={!dirty || disabled} onClick={() => void save()}>Save changes</button></footer>
  </section>;
}

export function PreparationSnapshot({ preparation }: { preparation: Preparation }) {
  const contact = preparation.selected_contact, evaluation = preparation.evaluation;
  return <section className="preparation-snapshot" aria-label="Original preparation snapshot"><div><strong>{preparation.public_name || preparation.name || preparation.identity.account_id}</strong><span>{contact?.email || 'No email selected'}</span></div><dl><div><dt>Chosen works</dt><dd>{preparation.works.length + preparation.missing_work_ids.length}</dd></div><div><dt>Evaluation</dt><dd>{evaluation ? friendlyLabel(evaluation.fit_group) : 'None'}</dd></div></dl>
    <details className="preparation-snapshot-details"><summary>Recorded preparation details</summary><div>
      <section><h4>Name confirmation</h4><dl><div><dt>Status</dt><dd>{preparation.public_name_confirmed ? 'Name confirmed' : 'Not confirmed'}</dd></div><div><dt>Confirmed</dt><dd>{preparation.name_confirmed_at ? analyzedDate(preparation.name_confirmed_at) : 'Not recorded'}</dd></div><div><dt>Identity revision</dt><dd>{preparation.identity.revision}</dd></div></dl></section>
      <section><h4>Chosen contact</h4>{contact ? <><p>{contactMeta(contact)}</p><dl><div><dt>Source URL</dt><dd>{contact.source_url || 'Not recorded'}</dd></div><div><dt>Contact version</dt><dd>{contact.updated_at}</dd></div><div><dt>Identity revision</dt><dd>{contact.identity_revision}</dd></div></dl></> : <p>No email selected</p>}</section>
      <section><h4>Chosen works</h4>{preparation.works.length ? <ul className="preparation-snapshot-records">{preparation.works.map(work => <li key={work.id}><strong>{workName(work)}</strong><span>{workRelation(work)} · {workEvidence(work)}</span><span>Record revision {work.revision} · Identity revision {work.identity_revision}</span>{work.source_url ? <span>{work.source_url}</span> : null}{work.evidence_excerpt ? <blockquote>{work.evidence_excerpt}</blockquote> : null}{work.verification_notes ? <span>{work.verification_notes}</span> : null}</li>)}</ul> : <p>No works chosen</p>}{preparation.missing_work_ids.length ? <div><h5>Unavailable chosen work IDs</h5><ul className="preparation-snapshot-missing">{preparation.missing_work_ids.map(id => <li key={id}>{id}</li>)}</ul></div> : null}</section>
      <section><h4>Recorded evaluation</h4>{evaluation ? <><p>{evaluation.match_brief?.summary || friendlyLabel(evaluation.fit_group)}</p>{evaluation.match_brief ? <dl><div><dt>Content fit</dt><dd>{evaluation.match_brief.content_fit}</dd></div><div><dt>Audience fit</dt><dd>{evaluation.match_brief.audience_fit}</dd></div></dl> : null}{evaluation.evidence.length ? <ul className="preparation-snapshot-records">{evaluation.evidence.map(item => <li key={item.work_id}><strong>{item.content_title || 'Untitled work record'}</strong><span>{friendlyLabel(item.relation)} · {item.status === 'recorded_evidence' ? 'Recorded evidence' : 'Metadata only'}</span>{item.source_url ? <span>{item.source_url}</span> : null}</li>)}</ul> : null}</> : <p>No evaluation selected</p>}</section>
    </div></details><MissingChips fields={preparation.missing_fields}/></section>;
}
