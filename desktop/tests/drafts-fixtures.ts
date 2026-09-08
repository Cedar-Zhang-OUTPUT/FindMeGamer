import type { BuiltinTemplate, CompositionView, DraftView, SlotValues, TemplateVersion } from '../src/shared/drafts';
import { gameFixture } from './game-fixtures';
/** Canonical content extracted without rewriting from immutable backend A 5ffd7c47f9f7e91f428449955962b1bed05fe467. */
export const builtinTemplate: BuiltinTemplate = {
  "name": "LIMINAL: Within · original locked",
  "subject": "Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG",
  "fixed_fragments": [
    "<p></p><p>Hi ",
    ",</p><p></p><p>I’m Toki, the game producer at Ontology Play, an independent studio from Hong Kong. I’ve been following ",
    ", and I especially enjoyed your video on ",
    ". I liked how you ",
    "</p><p>I’m reaching out because I’d love to invite you to try our game, <b>LIMINAL: Within</b>. The demo is now available on Steam, and you can download it here:</p><p></p><p><b>Demo:</b> https://store.steampowered.com/app/4952700/_/</p><p></p><p><b>LIMINAL: Within </b>is a mix of interactive film and retro pixel-art RPG adventure, which is a pretty unusual combination. In terms of format, it is closest to <b>Dispatch</b>, while its story and subject matter are closer to <b>PARANORMASIGHT: The Seven Mysteries of Honjo</b>. The story follows an investigation into a series of murders, unfolding through multiple characters and interconnected storylines as the player is gradually led toward the truth.</p><p></p><p>The gameplay combines cinematic storytelling with branching choices and QTEs, as well as a substantial pixel-art RPG adventure that lets you step into and explore another part of the story.</p><p></p><p>If you enjoy the game and think it would be a good fit for your audience, we’d love to see you share it on your channel in whatever format feels natural to you—whether that’s a video, a livestream, or even a short mention. There is absolutely no obligation to cover it, though; we’d simply be happy for you to try it, and any feedback would already mean a lot to us. If you have any trouble accessing the demo, just let me know.</p><p></p><p>Thanks for your time, and for the work you put into your channel.</p><p></p><p>Best,</p><p>Toki</p><p>Game Producer, Ontology Play</p><p>Hong Kong</p>"
  ],
  "fixed_hash": "0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93",
  "source_metadata": {
    "kind": "canonical",
    "document_id": "Ieqid5pULoUSqMxOtKTc156xnLe",
    "revision": 69,
    "steam_app_id": "4952700",
    "raw_hash": "6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd"
  },
  "key": "liminal-revision-69",
  "requires_explicit_registration": true
};
export const draftIds = { game: '11111111-1111-4111-8111-111111111111', activity: '22222222-2222-4222-8222-222222222222', template: '33333333-3333-4333-8333-333333333333', composition: '44444444-4444-4444-8444-444444444444', batch: '55555555-5555-4555-8555-555555555555', draft: '66666666-6666-4666-8666-666666666666', selection: '77777777-7777-4777-8777-777777777777', recipient: '88888888-8888-4888-8888-888888888888', request: '99999999-9999-4999-8999-999999999999' };
export const templateVersion: TemplateVersion = { name: builtinTemplate.name, subject: builtinTemplate.subject, fixed_fragments: [...builtinTemplate.fixed_fragments], fixed_hash: builtinTemplate.fixed_hash, source_metadata: { ...builtinTemplate.source_metadata }, id: draftIds.template, game_id: draftIds.game, created_at: '2026-09-08T00:00:00Z' };
export const draftValues: SlotValues = { firstName: 'Ari', channelName: 'Fixture Channel', reference: 'Fixture Story', observation: 'connected the two scenes.' };
const work = { id: draftIds.request, source_url: 'https://example.test/work', content_title: 'Fixture Story', work_name: null, evidence_excerpt: 'Fixture excerpt', verification_notes: 'Fixture verification', timestamp_seconds: 12 };
const slotSources = { firstName: { source_url: 'https://example.test/channel', confirmed: true }, channelName: { source_url: 'https://example.test/channel' }, reference: work, observation: work };
export function draftFixture(overrides: Partial<DraftView> = {}): DraftView {
  return { id: draftIds.draft, composition_id: draftIds.composition, recipient_snapshot_id: draftIds.recipient, selection_id: draftIds.selection, input_order: 0, revision: 0, context_token: 'a'.repeat(64), source_changed: false, status: 'pending', error_code: null,
input: { selection_id: draftIds.selection, identity: { platform: 'youtube', account_id: 'fixture', revision: 0 }, active: true, identity_changed: false, public_name: 'Ari', public_name_confirmed: true, channel_name: 'Fixture Channel', profile_url: 'https://example.test/channel', reference: 'Fixture Story', work, game: gameFixture('Fixture Game', draftIds.game) as unknown as import('../src/shared/library').JsonObject, selected_contact: null, contact_status: 'not_selected', template_version_id: draftIds.template, fixed_hash: builtinTemplate.fixed_hash, sender: { username: 'fixture@example.test', from_name: 'Fixture', reply_to: null }, missing_fields: ['email_not_selected'], slot_sources: slotSources },
    values: null, missing_fields: ['email_not_selected'], slot_sources: structuredClone(slotSources), rendered: null, sender_facts_valid: false, sender_facts: {}, send_ready: false, ...overrides };
}
export function compositionFixture(overrides: Partial<CompositionView> = {}): CompositionView { return { id: draftIds.composition, activity_id: draftIds.activity, recipient_batch_id: draftIds.batch, template_version_id: draftIds.template, created_at: '2026-09-08T00:00:00Z', recipient_count: 1, drafts: [draftFixture()], send_ready: false, ...overrides }; }
