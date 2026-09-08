# Fourth backend unit: Activity / durable Discovery

Base: 0153a38. Scope: internal stable Demo; fixture providers, real HTTP/task/DB
path. No client, production, paid API, SMTP, AI ranking or selection workflow.
Source: PRD revision 751 P3/P4, review sections 4/8. Main backend checkout is
explicitly assigned to this unit; stable frontend 18090 is not touched.

## Contract / decisions

- Activity belongs to an existing Game, with name and selected reference IDs.
  Creation freezes game detail and selected reference objects. A query freezes
  Activity source snapshot and conditions; changed conditions mean a new query.
- POST /api/v2/activities; GET list/detail; POST /{id}/queries starts a first
  batch. GET /api/v2/discovery/queries/{id} and /results read durable state.
  POST /queries/{id}/continue creates another bounded batch; POST /stop stops
  further pages. POST writes require Idempotency-Key. Results never auto-selected.
- Query input: providers list of DiscoveryRequest without cursor, filters,
  batch_target default100 max100, result_limit default600 max600,
  batch_request_budget default20 max40, batch_scan_budget default1000 max2000,
  total_request_budget default120 max240, total_scan_budget default6000 max12000.
  At least one provider; unique platform. Twitch/Instagram preserved unavailable.
- Filters: countries (ISO codes) + include_unknown_country; languages (content
  codes/text) + include_unknown_language; follower_ranges [{minimum,maximum}]
  inclusive union + include_unknown_followers; contact any/available/missing.
  Empty country/language/range means unrestricted and includes unknown. Specific
  filters exclude unknown unless explicitly included. Unknown region text is
  stored in pending_country_labels and never applied as a verified condition.
- Accounts import into shared Library by stable platform/account ID, preserving
  manual fields, successful AI analysis, contacts, identity revisions and old
  evidence. No full AI tasks scheduled automatically. Metadata sources are not
  gameplay evidence; source works remain unverified.
- One batch task loops one provider page at a time. DB reservation before I/O;
  no DB transaction spans network. Atomic page import + candidate dedup + cursor
  advance. Per-query global result cap; a provider page may end a batch slightly
  above target (at most one provider page), never exceed result_limit.
- Durable page attempts reserve request/scan budgets. Normal duplicate delivery
  cannot call provider twice while lease active. Expired in-flight attempts become
  outcome_unknown and pause; explicit continue requires acknowledge_unknown=true
  and consumes another bounded budget. Never silently retry unknown paid calls.
- Stop preserves already-returned and in-flight results in their own query, with
  selected=false. No next page once stop requested. Continue while in-flight is
  rejected until completion or expired lease is safely invalidated.
- Failures preserve all prior results and profiles. Provider exhaustion, partial
  failures, missing connection, unsupported sources and budgets stay explicit.
  Relevance order is provider discovery order, not an AI score/rank claim.
- Current0009 -> new0010 migration, maintenance window only. Old tables untouched.

## Task boundaries and acceptance

1. Root: HTTP schemas/API, idempotent activity/query creation and controls,
   frozen source snapshots, authenticated status/results and integration tests.
2. Worker/storage implementer: new Activity/Query/Batch/Attempt/Candidate models,
   migration0010, durable task runtime and bounded interruption/duplicate guards.
3. Library/filter implementer: transaction-local safe import plus pure basic
   filtering; tests preserve manual/rebind/analysis/contact/source identities.
4. Root: integrated HTTP -> fixture gateway -> task -> DB -> shared Library test,
   append duplicate pages, stop/continue, failure preservation, migration, full
   regression, one independent bounded review, commit and handoff.

Interfaces between 1/2 are fixed in schemas/activity.py and storage model brief;
2 calls 3's import/filter functions within the successful page transaction.
No overlapping file ownership except explicit coordinated wiring.

## Progress

- PRD P3/P4 and review4/8 read; scoped contract prepared.
- HTTP/schema, worker/storage, and Library/filter implementation complete.
- TDD observed for Activity creation, durable runtime/import, usage/unknown read
  state and shared Library manual-edit reflection. Scoped integration tests pass.
- Full initial regression: 2,010 passed; three expected contract baseline failures
  (new migration head, operations, generated OpenAPI) updated and 50 relevant tests
  subsequently passed. Final full regression: 2,019 passed, no skips (real Redis
  enabled), one pre-existing deprecation warning. Black19 and diffcheck pass.
- Independent review found provider language `und` treated as known; fixed with
  three failing regression cases (`und`, `UND`, `zxx`) then 19 import/filter tests
  passing. Final delta review complete: no unresolved in-scope blockers.
- Ruling: conservative request/scan reservations are not refunded for successful
  short pages; actual known usage is reported separately. This prioritizes bounded
  spend over maximizing a batch's quota; it may stop scanning earlier than the
  provider's actual charge alone would require.
- Ruling: result order is discovery order, no AI relevance claim; evidence-based
  ranking/filtering remains the later matching unit, while raw work evidence stays
  unverified here. No selection or sending workflow is included.
- All four task boundaries completed; local commit/handoff, no push/deployment.
