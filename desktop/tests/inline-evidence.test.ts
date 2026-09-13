import { describe, expect, it, vi } from 'vitest';
import { saveEvidenceStages, reconcileEvidence, type EvidenceAPI, type EvidenceAttempt } from '../src/renderer/components/match/inlineEvidence';
import { workFixture } from './creator-fixtures';
import { preparationFixture } from './outreach-fixtures';

function fixture() {
  const work = workFixture(), selection = preparationFixture();
  selection.creator_id = work.creator_id; selection.works = [];
  const attempt: EvidenceAttempt = { scope: { activityId: selection.activity_id, selectionId: selection.id, creatorId: work.creator_id },
    work, selection, fields: { evidence_excerpt: 'Recorded scene', verification_notes: 'Source checked', source_url: 'https://example.test/video' }, stage: 'work' };
  const savedWork = { ...work, ...attempt.fields, revision: work.revision + 1 };
  const savedSelection = { ...selection, revision: selection.revision + 1, works: [{ ...savedWork, relation: 'current_game', evidence_status: 'recorded_evidence' }] };
  const api = { creators: { updateWork: vi.fn(async () => ({ ok: true, data: savedWork })) },
    outreach: { selection: vi.fn(async () => ({ ok: true, data: selection })), update: vi.fn(async (_input: unknown) => ({ ok: true, data: savedSelection })) } };
  return { attempt, api, savedWork, savedSelection, bridge: api as unknown as EvidenceAPI };
}
describe('inline evidence staged writes', () => {
  it('saves shared evidence then selects precisely that work without implied confirmations', async () => {
    const f = fixture(), checkpoint = vi.fn();
    expect((await saveEvidenceStages(f.bridge, f.attempt, checkpoint, () => true)).stage).toBe('draft');
    expect(f.api.creators.updateWork).toHaveBeenCalledWith({ creatorId: f.attempt.scope.creatorId, workId: f.attempt.work.id,
      data: { expected_revision: 1, ...f.attempt.fields } });
    expect((f.api.outreach.update.mock.calls[0][0] as {data:unknown}).data).toEqual({ expected_revision: f.attempt.selection.revision,
      context_token: f.attempt.selection.context_token, work_ids: [f.attempt.work.id] });
    expect(checkpoint.mock.calls.map(([a]) => a.stage)).toEqual(['selection', 'selection', 'draft']);
  });
  it('preserves the acknowledged work stage when selection fails; resume does not patch twice', async () => {
    const f = fixture(); let current = f.attempt;
    f.api.outreach.update.mockRejectedValueOnce({ code: 'access_denied' });
    await expect(saveEvidenceStages(f.bridge, current, a => { current = a; }, () => true)).rejects.toMatchObject({ code: 'access_denied' });
    expect(current.stage).toBe('selection');
    await saveEvidenceStages(f.bridge, current, a => { current = a; }, () => true);
    expect(f.api.creators.updateWork).toHaveBeenCalledOnce();
  });
  it('does not select anything after a work failure or connection change', async () => {
    const f = fixture(); f.api.creators.updateWork.mockRejectedValueOnce({ code: 'creator_write_unknown' });
    await expect(saveEvidenceStages(f.bridge, f.attempt, vi.fn(), () => true)).rejects.toBeTruthy();
    expect(f.api.outreach.update).not.toHaveBeenCalled();
    await expect(saveEvidenceStages(f.bridge, f.attempt, vi.fn(), () => false)).rejects.toThrow();
    expect(f.api.creators.updateWork).toHaveBeenCalledOnce();
  });
  it('requires advanced revision plus exact submitted fields to resolve an uncertain write', () => {
    const f = fixture(); const context = { selection: f.attempt.selection, works: [f.savedWork] };
    expect(reconcileEvidence(f.attempt, context)?.stage).toBe('selection');
    expect(reconcileEvidence(f.attempt, { ...context, works: [{ ...f.savedWork, revision: 1 }] })).toBeNull();
    expect(reconcileEvidence(f.attempt, { ...context, works: [{ ...f.savedWork, evidence_excerpt: 'Someone else' }] })).toBeNull();
  });
});
