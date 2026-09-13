# Creator repairs and Deep Match diagnostics — internal Demo

## Evidence and bounded changes

Run `6431d87a-2d9d-4cd9-9b49-ba48c6dbf754` ended partial on September 13:
14 successful / 8 failed Profiles. Failed terminal nodes were two repeated list
overflows, four schema-repair JSON failures, one presentation citation-kind error,
and one commercial citation-structure error. The terminal model calls all reported
`finish_reason=stop`, not token exhaustion.

- Ten-video map lists now permit 20 distinct supported values / 8 evidence items,
  matching the full Profile bounds. Reducers retain their 3-item summary limits.
  The 32,000-byte aggregate output guard and source-evidence validation remain.
  No automatic list truncation, evidence deletion or fabricated data.
- Creator map/reducer/brief repair receives the complete previous output up to
  32,000 UTF-8 bytes. Larger output is omitted entirely with a complete-regeneration
  instruction using the original input. Previously the observed ~10–12 KB output
  was cut at 8,192 characters, producing an invalid JSON fragment in the repair
  conversation. Synthetic fixtures reproduce and prevent that input defect.
  We do not claim the missing historical raw responses prove a particular JSON
  syntax error; malformed new responses still fail closed. No permissive parser,
  `eval`, extra model retry or generic Game/Discovery repair change.
- For an **exact** supplied intermediate reference whose catalog permits only
  `ai_inference`, canonicalize its existing kind/source_type labels to that unique
  triplet. Reference, observation, values, confidence and evidence membership stay
  unchanged. Unknown/ambiguous references are never guessed or repaired by lookup.
  All catalog checks still run. Normalizations emit a count and call UUID only.
- All reducers receive explicit citation targets, including visual/commercial
  intermediates. Existing bounded second-stage binding repair now handles all
  reducer dimensions and rejects any non-identity change, including nested audience
  observations, values or evidence membership/order. Successful node keys and
  checkpoint recovery semantics are unchanged.

## Deep Match: diagnostics, not speculative policy relaxation

The three failed Deep Match steps in evaluation
`412a1dfe-91b7-45f7-adfb-51c5b0340334` actually logged
`evaluation_narrative_invalid`. The first monitoring filter omitted the pre-existing
`evaluation_step_failed` event; subsequent fixed-window reads established that
subcode. It is not a supported-evidence or ID failure. Raw rejected text was never
persisted, so the exact offending phrase remains unknown.

This release preserves narrative/ID/evidence decisions. It adds:

- search / evaluation-run / step / candidate UUID context, plus original Creator
  analysis-job and creator UUIDs when linked to a search;
- explicit per-thread context propagation and step start/finish status;
- model-call UUID correlation through initial/repair and semantic rejection;
- `evaluation_business_rejected` with fixed subcode and, for narrative rejection,
  code-owned field and rule (`url`, `contact`, `timestamp`, `viewing_term`), without
  the offending text, URL, contact, prompt or response;
- schema-success vs business-acceptance distinction. Public errors are unchanged.

The existing broad viewing-term restriction can reject a negated limitation;
tests document this current behavior and verify a legitimate limitation without
those terms remains accepted. No unsupported claim is silently allowed. The new
field/rule diagnostics will identify the user's next real failure precisely.

## Verification and preserved work

TDD reproduced the three Creator defects before implementation and a missing deep
semantic event before adding diagnostics. Final targeted regression: **284 passed**
(one existing Starlette/AnyIO deprecation warning). One bounded independent review.
No real-model requests or paid validation were made.

Production read-only check at 11:14:37 UTC verified all 8 failed jobs' checkpoints:
64 successful nodes reusable; all 14 completed Profiles remain intact. Missing
stages total 6 video batches, 26 reducers and 8 briefs. Source, visual and contact
checkpoints exist for every failed job and remain within the 30-day recovery bound.
The nominal Profile retry work is therefore 40 stage calls, plus only any existing
bounded schema/evidence repairs. This is not a fixed billing quote or success
guarantee. Contact checkpoints are reused; no repeat Gemini research is expected
solely to recover these Profile nodes.

Existing evaluation has successful screening of 14 items, selecting 3; those
three deep steps failed and no rank/Match Brief was published. Preserve all records.

## Release and retry boundary

Deploy the reviewed commit with idle guards, a fresh backup, known schema 0023,
before/after fingerprints of all tables and config, health and synthetic-only
checks. No data reset, configuration change, SMTP action or client release.

**Do not trigger any live retry at deployment.** Heartbeat remains paused. The user
will manually click Retry unfinished work and explicitly notify the coordinator.
That existing operation automatically resumes evaluation after Profile/email work:
it preserves successful screening/deep/rank steps, screens only newly usable items,
and requeues failed evaluation steps. Before a later manual Deep Match retry, first
check whether this automatic continuation is active or has already completed.
Only the coordinator may schedule the conditionally authorized later retry, after
the user's notification and duplicate-work checks. Never run it concurrently with
the automatic continuation; never send outreach email as part of verification.
