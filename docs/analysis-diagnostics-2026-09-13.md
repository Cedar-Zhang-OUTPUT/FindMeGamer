# Analysis diagnostics — internal Demo

## Scope

Instrumentation only. No model prompt, schema, output repair policy, concurrency,
retry count, budget, checkpoint recovery, email sending, API contract or database
migration changes. One bounded independent review; no remaining blocking findings.

## Events

- `model_call_started` / `model_call_finished`: unique call UUID, provider/model,
  schema, initial/repair (Gemini initial/retry plus attempt number), requested token
  budget, duration, status, finish reason, UTF-8 output bytes and safe token usage.
  Metadata is recorded for ordinary schema/JSON failures, not only length errors.
- Safe validation locations/types: at most 8 details, 12 location segments each.
  Full error count and aggregated reason counts (up to 64 categories) retain errors
  beyond the displayed sample. Raw validator input/messages are excluded.
- `analysis_node_started` / `analysis_node_finished`: source, parallel map/reduce,
  contact, visual and brief. Every failed future is observed before the existing
  deterministic first-error propagation. Failed work is not saved as a checkpoint.
  Checkpoint write failures are separately recorded as `analysis_checkpoint_failed`.
- `analysis_evidence_rejected`: bounded code-owned evidence/contact reason, stage
  attempt and last model call ID. Schema success alone does not imply evidence
  acceptance or successful Profile publication.

Analysis execution binds job UUID, search/creator UUID when linked to a search,
and a SHA-256 canonical creator reference for first-time manual analysis before a
Profile UUID exists. Each executor submission receives a separate `copy_context`.
Calls without available parent context do not fabricate IDs.

No prompts, full model output, Profile bodies, emails, keys, URLs, tokens or raw
exception text are logged by this instrumentation. Raw output remains only in
memory for the pre-existing bounded repair flow. Logs use existing Docker rotation
(10 MB × 5 files per service); no new database table or S3 raw-response retention.
Unknown configured model names are represented as `configured_model`.

## September 13 test reset

Stopped search `33522d47-18cc-4e57-9280-8b66d366442f`, verified drained worker and
broker, then stopped write services. Scope checks proved all occupied business
records belonged to the post-reset LIMINAL test; no colleague data was in scope.

- 41 business tables / 1003 rows removed; settings, secrets and schema fingerprints
  unchanged. Configuration/master-key SHA unchanged.
- 36 acquisition objects copied and verified before exact-manifest deletion;
  deployment probe and all existing backups preserved.
- Frozen database backup: `backups/20260913T095608Z-5ef1cee180ff-pre-migration.dump`
  in bucket `zhangyue-data-493392056671-us-west-2`; downloaded SHA check and
  `pg_restore --list` passed (not a full restore drill).
- Cache backup: `backups/20260913-debug-reset/acquisition/` in the same bucket.
- Root-only operational evidence: `/var/backups/find-me-gamer/20260913-debug-reset`.

## Acceptance

Final targeted regression: **216 passed** (one existing Starlette/AnyIO deprecation
warning). Initial diagnostic test failed before implementation as expected.

Tests cover non-length failures, initial/repair metadata, JSON vs network timeout,
Gemini bounded retries and JSON/schema categories, full error counts beyond eight,
private-content canaries, concurrent context isolation and all parallel failures
with only successful checkpoints retained. Existing worker, recovery, Creator,
Game and X integration regressions are included in the final test run.

Deploy only the reviewed exact commit with maintenance backup and unchanged table
fingerprints. Post-deploy smoke uses in-memory HTTP MockTransport, not real models;
no new search, analysis or email is automatically started. The user starts the next
real test after the empty-state and health checks pass.
