import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { decodeDraft, decodeComposition } from '../src/main/drafts-validation';
import { decodeQualification } from '../src/main/sending-validation';
import { draftFixture, draftIds } from './drafts-fixtures';

function withMetadata(metadata: Record<string, any>) {
  const draft = structuredClone(draftFixture());
  const work = { ...(draft.input.work as object), ...metadata };
  draft.input.work = work;
  draft.slot_sources.reference = work;
  draft.slot_sources.observation = work;
  draft.input.slot_sources = structuredClone(draft.slot_sources);
  return draft;
}
const metadata = { game_id: draftIds.game, relation: 'current_game', evidence_status: 'recorded_evidence', evidence_tier: 'current_game' };
describe('evidence priority snapshot compatibility', () => {
  it('preserves historical seven-field sources', () => expect(decodeDraft(draftFixture())).toEqual(draftFixture()));
  it.each(['current_game', 'reference_game', 'related_content', 'unverified'])('preserves %s evidence metadata', tier => {
    const draft = withMetadata({ ...metadata, evidence_tier: tier });
    expect(decodeDraft(draft)).toEqual(draft);
  });
  it('accepts absent work metadata as explicit nulls with unverified tier', () => {
    expect(() => decodeDraft(withMetadata({ game_id: null, relation: null, evidence_status: null, evidence_tier: 'unverified' }))).not.toThrow();
  });
  it.each([{ game_id: 'invalid' }, { relation: 'invented' }, { evidence_status: 'viewed' }, { evidence_tier: 'trusted' }, { secret: 'unexpected' }])('rejects invalid or unknown metadata %j', patch => {
    expect(() => decodeDraft(withMetadata({ ...metadata, ...patch }))).toThrow();
  });
  it('rejects partially supplied new metadata', () => expect(() => decodeDraft(withMetadata({ evidence_tier: 'unverified' }))).toThrow());
});

const fixturePath = process.env.FMG_EVIDENCE_CONTRACT_DIR;
describe.skipIf(!fixturePath)('actual backend 29fe65b synthetic API snapshots', () => {
  const read = (name: string) => JSON.parse(readFileSync(`${fixturePath}/${name}.json`, 'utf8'));
  it.each(['draft', 'unverified-draft'])('decodes actual %s without rewriting it', name => { const raw = read(name); expect(decodeDraft(raw)).toEqual(raw); });
  it('decodes actual composition', () => { const raw = read('composition'); expect(decodeComposition(raw)).toEqual(raw); });
  it('decodes actual qualification', () => { const raw = read('qualification'); expect(decodeQualification(raw)).toEqual(raw); });
});
