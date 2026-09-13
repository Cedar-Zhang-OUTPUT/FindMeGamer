import { workFixture } from './creator-fixtures';

// Exact source_fields shape emitted by creator_library_sync.py / metadata_observation.
// Synthetic content; the schema and field relationships mirror the actual producer.
export const metadataObservation = {
  text: 'used this description for your video: “A quiet station and a sudden reveal.”.',
  evidence_kind: 'metadata',
  source_url: 'https://www.youtube.com/watch?v=fixture-video',
  excerpt: 'A quiet station and a sudden reveal.',
  source_field: 'description',
};
export function metadataWorkFixture() {
  return { ...workFixture(), origin: 'source' as const, source_url: metadataObservation.source_url,
    content_title: 'Station review', evidence_excerpt: null, verification_notes: null,
    source_fields: { content_title: 'Station review', language: 'en', language_source_field: 'snippet.defaultAudioLanguage',
      content_id: 'fixture-video', source_url: metadataObservation.source_url, published_at: null,
      collected_at: '2026-09-13T00:00:00+00:00', metrics: [{ name: 'views', value: 250 }],
      content_type: 'unverified', work_name: null, game_id: null, verification_notes: null,
      evidence_excerpt: null, timestamp_seconds: null, outreach_observation: { ...metadataObservation } } };
}
