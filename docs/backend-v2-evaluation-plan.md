# Discovery candidate evaluation — bounded plan and ledger

Baseline a71c559. PRD751 P4 read 2026-09-08; old v1 Match stays untouched.

## Global constraints

Internal stable Demo. Backend only, no desktop/macOS/18090/cloud/SMTP/push. No live
YouTube/X calls or X Keychain reads. Only necessary known-project DeepSeek smoke
with tiny synthetic input after fixture checks. TDD + one bounded independent
integrated review; ordinary E2E/duplicates/data loss/Profile overwrite/secrets/SSRF/
current migration block; defensive Minor deferred. Preserve coordinator PRD review.

## Contract and decisions

POST /api/v2/discovery/queries/{id}/evaluations with Idempotency-Key; optional
candidate_ids (1..600 unique) or omit to freeze all currently loaded query members.
GET collection and GET /api/v2/discovery/evaluations/{id} return run/status/usage.
GET .../{id}/results returns ordered paginated candidate evaluations (all frozen
members, including screened-out/failed/unevaluated states, no numeric score/order).
POST .../{id}/retry with Idempotency-Key resets only failed/expired model steps,
optional step_ids; completed steps/briefs never rerun. Active nonexpired steps cause
409. New request key required for each intentional new retry. Snapshot IDs do not
change and later Discovery additions remain outside the run. Never select people.

Per-run steps: screening chunks20 -> chosen candidates deep_match individually ->
ranking chunks20 using common absolute rubric and internal scores; globally sort
by those scores with stable input order ties. At most4 concurrent model steps per
run. Accept up to600 frozen candidates, no old30 limit. All successful child steps
checkpoint immediately. Partial failures preserve successful briefs; explicit retry
resumes only incomplete children. No giant600-person model prompt. No general engine.

States queued/running/completed/partial/failed/no_matches distinguish screening zero
from failure. Public ordered rows include group, brief, evidence state, stale and
identity_changed flags; no score/ordinal/rank. Failed ranking retains explanations
as unranked. Public run usage counts model operations/attempts, not fabricated HTTP
or token/currency counts (existing gateway may make one schema repair per operation).

## Task 1: Model adapter and typed output (one subagent)

Only create backend/app/discovery/evaluation_ai.py,
backend/app/schemas/discovery_evaluation_output.py,
backend/tests/unit/test_discovery_evaluation_ai.py. No other edits/commits/subagents.

`EvaluationAI(gateway)` methods:
- screen(game:dict, candidates:list[dict]) -> EvaluationScreenOutput
- deep(game:dict, candidate:dict) -> EvaluationMatchBrief
- rank(game:dict, briefs:list[dict]) -> EvaluationRankOutput

Input candidates have candidate_id string, creator_brief dict, creator_detail dict,
analysis dict (bounded existing analysis, may empty), works list (known record ID,
title/work_name/content_type/game_id, evidence_excerpt/verification_notes,
timestamp_seconds from existing record), analysis_available bool. Caller supplies
only current-identity snapshot. Screen sees only candidate_id + compact creator_brief;
deep sees complete bounded effective detail/analysis/works (no contact fields),
rank sees candidate_id + previously validated Match Brief. Game is detailed effective
Game Brief from frozen Game and selected references, no URL acquisition. Every
system prompt English; all source text JSON untrusted, not executable instructions.

Strict schemas extra forbid; strings nonblank bounded; IDs strings parsed UUID:
Screen {selected_ids: list[UUID] <=20}; validate unique subset of exact input IDs,
zero legitimate. Deep {candidate_id:UUID, summary:str<=1200, content_fit:str<=1200,
audience_fit:str<=1200, limitations:list[str<=500]1..6, cited_work_ids:list[UUID]<=20,
confidence: limited|supported}; validate exact candidate and work IDs are input,
unique citations. `supported` requires cited existing work with both nonblank
evidence_excerpt and verification_notes, NOT titles/posts/thumbnails alone.
Reject narrative URL/email/timestamp insertion and explicit played/watched/viewing
claims: no sender-watched confirmations exist in this unit. Model text may express
topic/audience suitability only, unknown audience countries stay unknown. Instruct
not to say a creator or sender played/watched, and not to invent facts or citations;
use "recorded evidence" wording only. Metadata-only defaults limited/needs evidence.
Rank {items:[{candidate_id:UUID, score:int0..100}] <=20}; exact unique membership
of supplied briefs; absolute rubric common across batches. 75+strongfit,40+potential,
below40limited derived server-side; model scores never public. No model-chosen URLs,
timestamps, email, arbitrary baseURL/tool fields. Unknown/missing/extra IDs invalid.

Reuse DeepSeekGateway.complete_structured. Models screen deepseek-v4-flash,
deep/rank deepseek-v4-pro. max_tokens screen2048,deep4096,rank2048. No retries beyond
existing gateway's bounded repair. Each method rejects >20 screen/rank input before
I/O. Missing analysis does not cause invented enrichment. TDD through actual gateway
with MockTransport: success all3stages, screenedzero, invalid/duplicate/missing IDs,
inventedworks/evidenceupgrade/watchclaim/URLs, metadata-only confidence, oversized
chunks, truncation/timeout. Report focused tests and any binding-interface concerns.

## Task 2: Snapshots, persistence and API/runtime (main)

Add0012three evaluation-specific tables run/items/steps, preserve0011 and v1 history.
Freeze Game/reference/query and currently loaded candidate IDs/current identity
revision/effective creator info/bounded known works. Preexisting identity mismatches
never evaluate new account as old candidate. Fingerprint used data and compare on
read: Profile edits/analysis/work changes stale; identity changes separately flagged.
Model never writes Profiles. Record model names/method version and successful child
outputs. Per-step leases/tokens with short DB locks, no I/O transaction, checkpoint
successes as futures finish. Rank common rubric batches; preserve unranked successes
if one rank call fails. Idempotent API/run-step identities, explicit failed child
retry, expired ownership invalidates late completion. Broker failure saved-run replay.
Steps/results do not contain raw acquired JSON, emails or personal contact fields.
Evidence is derived from exact known work records, metadata != verified gameplay;
sender_watched is always false and not editable here. Reference/current-game relation
only from declared known work association, not a title/keyword inference.

## Task 3: Verify, review, commit

HTTP→actualmodeladapter+HTTPfixture→worker→DB results tests; frozen membership/new
arrivals, duplicate dispatch, loststep/retry, partialfailure oldbrief retention,
identity rebound/stale, metadata unknown evidence, >30/100 candidate chunking,
0011 migration. Full backend regression with realRedis once necessary, OpenAPI and
one bounded review. Tiny synthetic realDeepSeek3-stage smoke if fixturesgreen.
Commit only this unit and notify coordinator safe point for later integration.

## Preflight matrix / rulings

| Tasks | Shared interface | Check |
| --- | --- | --- |
|1/2|EvaluationAI methods and output IDs|defined explicitly, main owns snapshot fields|
|2/3|three tables/routes/workerstates|currentDB0011, no v1 modifications|
|1|limited evidence vs narrativeclaims|IDs validated, server derives evidence status|
|2|checkpoint/retry vs savedsuccess|only failed/expired steps reset, members frozen|
|3|broad review vs internalDemo|only bounded user blockers fixed|

Ruling: Rank chunks with shared absolute rubric then deterministic hidden-score
merge — bounds input/output for100..600 candidates — cost: cross-chunk calibration
less exact than one giant relative ordering; method/version explicitly recorded.
Ruling: Game/Creator briefs are bounded projections of already acquired effective
data, not new enrichment — avoids invented facts/extra acquisition — cost: sparse
sources remain limited/needs evidence instead of deep claims.
Ruling: Evidence may be recorded but sender viewing remains unconfirmed — this unit
has no sender confirmation action — cost: later outreach must independently confirm.

## Verification ledger

- Task1 complete: strict model adapter and 23 focused unit tests, fixture gateway
  HTTP boundary, no provider requests. Implementer report retained under
  `.superpowers/sdd/backend-v2-evaluation-plan/task-1-report.md`.
- Task2 implemented: three tables/current0011 migration, authenticated API,
  immutable snapshots, checkpoint worker/retry and public results.
- Integration red/green: initial missing endpoint/worker failures preceded the
  implementation. Subsequent integrated tests exposed wrapped rank payload versus
  the adapter's direct typed Brief list; minimal fix produced 7/7 passing tests.
  Added normal retry/stale/identity/evidence/auth/membership/claim-cap cases; 20
  passed before the final typed-client-contract addition. That new test first failed
  on an untyped dict field and is fixed with EvaluationMatchBrief response schema.
- Existing OpenAPI export/operation manifest and single-head tests correctly failed
  until the new five operations, exported schema and0012 head were updated.
- One bounded independent integrated read-only review completed: ready, no
  substantiated Demo blocker. No repeated/broadened review cycle.
- Authorized tiny synthetic DeepSeek check: screening, deep and ranking each
  HTTP200; typed outputs valid, confidence limited, no provider discovery calls.
  Screening chose0, so deep/rank were independent adapter checks of the same
  synthetic record, not represented as a live selected-candidate end-to-end run.
  Full100-candidate API/worker/model-HTTP-fixture flow is covered separately.
- Full regression with real Redis: **2094 passed**, zero failed/skipped, one existing
  Starlette dependency deprecation warning; exit0 in159.68s. Includes current0011
  migration, typed OpenAPI deterministic export, oldv1 flows and new evaluation.
  No push/deployment/SMTP or18090 changes. Coordinator PRD review file remains
  outside this commit.
