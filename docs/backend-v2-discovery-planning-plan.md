# Game-driven discovery planning — bounded implementation ledger

Baseline: 205c541. PRD revision 751 P2.1/P3 re-read on 2026-09-08.
Existing Activity freezes effective Game and chosen reference records; QueryCreate
requires provider-native query strings. No accepted game-driven planner exists.

## Global constraints

Internal stable Demo only. Backend-only; no desktop/macOS, no deployment/push/SMTP,
no 18090 modifications. No additional live YouTube/X requests. Preserve coordinator
review document. TDD, one bounded independent integrated review; defensive Minor
is deferred, ordinary E2E, lost/duplicate data, secrets/SSRF and current migration
failures block. Read project DeepSeek configuration only for an authorized minimal
model smoke. No arbitrary URL acquisition/tools or credentials in model input.

## Contract

POST /api/v2/activities/{id}/discovery-plans (Idempotency-Key): mode preview|discover,
platforms youtube|x (unique), keywords, filters, existing query budget fields.
Returns 202 plan_id/status. GET same collection lists plans; GET
/api/v2/discovery/plans/{id} returns snapshot, status, validated output, safe error,
retryable, query_id. POST /api/v2/discovery/plans/{id}/retry uses Idempotency-Key,
only failed/expired attempts, never creates another query for a successful plan.
Discover automatically creates a single existing DiscoveryQuery/first batch after
successful planning within submitted budgets. Preview never dispatches discovery.
Old explicit providers route remains. Conditions changes mean a new immutable plan
and query snapshot; Activity's selected Game/reference snapshot remains frozen.

## Task 1: Bounded model planning adapter

Owner: one implementation subagent. Files only new
backend/app/discovery/planning.py, backend/app/schemas/discovery_plan_output.py,
backend/tests/unit/test_discovery_planning.py.

Implement `generate_plan(source_snapshot: dict, conditions: dict, *, gateway,
model: str) -> SearchPlanOutput` using existing DeepSeekGateway.complete_structured,
max_tokens=2048 and English system prompt, frozen data as untrusted JSON user data.
Schema strict extra forbid: summary (1..1500), rationale (1..1500), queries (1..2)
each {platform: youtube|x, terms: list 1..3 of safe keyword phrases 1..100 chars}.
No URLs, control chars, operator injection, secret/baseURL/tool keys; allow Unicode
letters/digits/space/apostrophe/hyphen so game proper names survive. Validate unique
platforms exactly equal requested platforms after schema parsing. Provide
`provider_queries(output)` returning {platform: native query}: quote each phrase,
join with spaces, append fixed `-is:retweet` for X. No other model-selected operators.
Only selected effective Game name/description/tags/developer/languages/release date
and selected reference name/reason/similarities, plus requested filters/keywords
enter prompt. No URLs, opaque source/manual metadata or contacts; no URL fetch.
Name alone is allowed, summary explicitly limited facts. If no name/description/tags
in Game, raise a safe `PlanningInputError` with code `game_context_required` before
model I/O; reference-only/URL-only is not enough to invent Game facts. English
instructions, unknown fields stay unknown, content keywords are not watched proof.
TDD real gateway with httpx.MockTransport: success, prompt isolation, name-only,
URL-only no call, invalid platforms/duplicates/length/terms rejected, timeout and
truncated output propagated. Existing gateway has at most one schema repair call;
do not add retries or alter global gateway behavior. No subagents or commits.

## Task 2: Persistent authenticated execution

Owner: main. Add one Activity-linked plan table and migration 0011, strict HTTP
input/output contracts, Celery plan task using one lease and DB locks with no I/O
transaction held. Persist queued/running/ready/failed, safe errors, immutable source
and conditions, attempt/version guard, query_id unique. Duplicate task delivery has
no repeated model I/O; lost/stale completion cannot overwrite retry/newer state.
Retry explicitly handles timeout/failed and expired running, not automatically.
Discover publishes query+batch+plan success atomically; redispatch saved batch safe
on replay/retry after broker failure. Reuse existing encrypted DeepSeek config and
text model selection; profile data is never updated by planning. Include plan_id
link in generated query snapshot. Tests API→real model adapter fixture→saved plan→
discovery provider fixture→Library, preview, idempotency, failure preserving old plan,
snapshot changes, missing model config, retry/lease, and current migration.

## Task 3: Verify and handoff

Related regressions, full backend suite once with real Redis, OpenAPI export,
one bounded independent review and fix only blockers. Optional one live DeepSeek
planning invocation in isolated process using synthetic Game context; never collect
provider data. Record model/status and cost only if observable. Commit this unit.

## Preflight and rulings

| Pair/task | Interface or consistency | Result |
| --- | --- | --- |
| 1 / 2 | generate_plan(snapshot, conditions, gateway, model) -> typed output | Narrow agreed interface; Task 1 has no DB writes |
| 2 / 3 | One accepted migration and exported authenticated routes | Dedicated backend test DB only |
| 1 | Strict output + safe query compilation | AI cannot choose endpoints/platforms beyond selection |
| 2 | Discover auto-start vs preview | Mode persisted; no additional approval page |
| 3 | Stable Demo scope vs review expansion | Only user-defined blockers fixed |

Ruling: Name-only Game input is sufficient; URL-only without effective semantic
Game context fails with actionable error — PRD permits name-only and coordinator
forbids inferring facts from URLs — cost if wrong: adjust minimum-context rule.
Ruling: Use server-compiled safe keyword phrases rather than unrestricted model
query syntax — excludes model-provided operators/endpoints while retaining native
provider query strings — cost: advanced query operators stay on explicit route.
Ruling: Use existing shared branch/workspace authorized by coordinator; no worktree
switch or cleanup — main backend is exclusive and frontend isolated — cost: preserve
all unrelated edits carefully. Single integrated review follows user scope cap.

Progress: Tasks 1/2 implemented. Model adapter 16 tests pass; API/runtime 13 and
current migration 1 pass. Actual DeepSeek minimal synthetic-input validation:
one HTTP200, valid two-platform plan, zero provider discovery requests.
Independent integrated review: spec PASS / quality PASS, no blocker.
Deferred Minor: source text can contain embedded URLs/contact text even though
dedicated URL/contact fields are omitted; no acquisition or credential exposure.
Documentation narrowed to the actual guarantee, no speculative text-sanitizer added.
Full suite first pass: 2047 passed, two expected contract manifests stale (0010 head
and operation list); updated to 0011 + four planning operations. Related70 tests
passed, then final full suite with real Redis: 2049 passed, zero failures/skips,
one existing Starlette deprecation warning (137.42 seconds). OpenAPI deterministic
export and diff checks passed. Unit ready for single local commit; no push/deploy.
