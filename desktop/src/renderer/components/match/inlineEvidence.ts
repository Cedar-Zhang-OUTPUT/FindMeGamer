import type { DesktopBridge, Result } from '../../../shared/bridge';
import type { WorkDetail } from '../../../shared/creators';
import type { Preparation } from '../../../shared/outreach';

export type EvidenceAPI = Pick<DesktopBridge, 'creators' | 'outreach'>;
export type EvidenceFields = Pick<WorkDetail, 'evidence_excerpt' | 'verification_notes' | 'source_url'>;
export type EvidenceScope = { activityId: string; selectionId: string; creatorId: string };
export type EvidenceContext = { selection: Preparation; works: WorkDetail[] };
export const evidenceFields = (work: WorkDetail): EvidenceFields => ({
  evidence_excerpt: work.evidence_excerpt, verification_notes: work.verification_notes, source_url: work.source_url,
});
export const evidenceMatches = (work: WorkDetail, fields: EvidenceFields) =>
  (Object.keys(fields) as (keyof EvidenceFields)[]).every(key => work[key] === fields[key]);
export function resultValue<T>(result: Result<T>): T { if (!result.ok) throw result.error; return result.data; }
export async function loadEvidenceContext(api: EvidenceAPI, scope: EvidenceScope): Promise<EvidenceContext> {
  const selection = resultValue(await api.outreach.selection({ activityId: scope.activityId, id: scope.selectionId }));
  if (selection.creator_id !== scope.creatorId || selection.id !== scope.selectionId || selection.activity_id !== scope.activityId
    || !selection.active || selection.identity_changed) throw new Error('Recheck this person’s selected account before editing evidence.');
  const works: WorkDetail[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = resultValue(await api.creators.works({ creatorId: scope.creatorId, offset, limit: 100 }));
    if (page.offset !== offset || page.items.some(work => work.creator_id !== scope.creatorId || !work.is_current_identity
      || work.identity_revision !== selection.identity.revision || works.some(old => old.id === work.id)))
      throw new Error('The work list changed. Reload it before saving.');
    works.push(...page.items);
    if (works.length >= page.total) break;
    if (!page.items.length || offset >= 9900) throw new Error('The work list is incomplete. Open Library to review it.');
  }
  return { selection, works };
}

export type EvidenceAttempt = {
  scope: EvidenceScope; work: WorkDetail; fields: EvidenceFields; selection: Preparation;
  stage: 'work' | 'selection' | 'draft';
};
export function evidenceWriteUnknown(error: unknown): boolean {
  return !error || typeof error !== 'object' || !('code' in error)
    || ['save_outcome_unknown', 'creator_write_unknown', 'creator_outcome_unknown', 'outreach_write_unknown', 'outreach_outcome_unknown',
      'network_error', 'invalid_response', 'connection_changed'].includes(String(error.code));
}
/** Each acknowledged stage is recorded before the next mutation. No implicit retries. */
export async function saveEvidenceStages(api: EvidenceAPI, initial: EvidenceAttempt,
  checkpoint: (attempt: EvidenceAttempt) => void, stillCurrent: () => boolean): Promise<EvidenceAttempt> {
  let attempt = initial;
  const check = () => { if (!stillCurrent()) throw new Error('The connection or current task changed. Check the saved records.'); };
  check();
  if (attempt.stage === 'work') {
    if (!evidenceMatches(attempt.work, attempt.fields)) {
      const work = resultValue(await api.creators.updateWork({ creatorId: attempt.scope.creatorId, workId: attempt.work.id,
        data: { expected_revision: attempt.work.revision, ...attempt.fields } }));
      check();
      if (work.id !== attempt.work.id || work.creator_id !== attempt.scope.creatorId || work.revision !== attempt.work.revision + 1
        || !work.is_current_identity || work.identity_revision !== attempt.work.identity_revision || !evidenceMatches(work, attempt.fields))
        throw new Error('The work save could not be confirmed. Check the current record.');
      attempt = { ...attempt, work };
    }
    attempt = { ...attempt, stage: 'selection' }; checkpoint(attempt);
  }
  if (attempt.stage === 'selection') {
    const selection = resultValue(await api.outreach.selection({ activityId: attempt.scope.activityId, id: attempt.scope.selectionId }));
    check();
    if (selection.creator_id !== attempt.scope.creatorId || !selection.active || selection.identity_changed
      || selection.identity.revision !== attempt.work.identity_revision) throw new Error('The selected account changed. Review this person before continuing.');
    attempt = { ...attempt, selection }; checkpoint(attempt);
    if (selection.works.length !== 1 || selection.works[0].id !== attempt.work.id || selection.missing_work_ids.length) {
      const saved = resultValue(await api.outreach.update({ activityId: attempt.scope.activityId, id: attempt.scope.selectionId,
        idempotencyKey: crypto.randomUUID(), data: { expected_revision: selection.revision, context_token: selection.context_token, work_ids: [attempt.work.id] } }));
      check();
      if (saved.id !== selection.id || saved.creator_id !== selection.creator_id || saved.revision !== selection.revision + 1
        || saved.works.length !== 1 || saved.works[0].id !== attempt.work.id || saved.missing_work_ids.length)
        throw new Error('The work selection could not be confirmed. Check the current record.');
      attempt = { ...attempt, selection: saved };
    }
    attempt = { ...attempt, stage: 'draft' }; checkpoint(attempt);
  }
  return attempt;
}

/** Read-only proof after a lost receipt. An unchanged revision never proves a failed write. */
export function reconcileEvidence(attempt: EvidenceAttempt, context: EvidenceContext): EvidenceAttempt | null {
  const work = context.works.find(row => row.id === attempt.work.id);
  if (!work || !evidenceMatches(work, attempt.fields)) return null;
  if (attempt.stage === 'work') return work.revision > attempt.work.revision ? { ...attempt, work, selection: context.selection, stage: 'selection' } : null;
  if (attempt.stage === 'selection') return context.selection.revision > attempt.selection.revision
    && context.selection.works.length === 1 && context.selection.works[0].id === work.id && !context.selection.missing_work_ids.length
    ? { ...attempt, work, selection: context.selection, stage: 'draft' } : null;
  return attempt;
}
