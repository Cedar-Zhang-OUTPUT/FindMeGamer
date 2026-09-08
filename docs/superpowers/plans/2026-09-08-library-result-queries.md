# Library and candidate read-query implementation plan

> **For agentic workers:** Use executing-plans inline, TDD, one fixed-scope
> independent integrated review. Backend only; shared main checkout ownership remains.

**Goal:** Deliver P4/P12 complete server-side read filtering/sorting and useful rows
without changing human choices, evidence, provider state or saved records.

**Architecture:** Extend existing query parameters and typed read projections; use
small shared pure query helpers for current work evidence, timestamps and deterministic
sort keys. Apply all predicates/sorting to the full matched collection BEFORE slicing
pagination, following existing internal-Demo Library materialization. No new tables,
jobs, AI, acquisition or mail. Named saved subsets form the next independent unit.

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy/PostgreSQL; current migration0014 unchanged.

**Spec:** Original PRD751 reread as user on2026-09-08, P4
`doxcnMNjfwkPP5JxG3Mbmm0zAih`, P12.1 `doxcnkgDcoK3VnFeAJHLD8cggpg`, P12.2
`doxcn0s8PwNCYyQCwhVYnSeKRtc`; root handoff. Original full menus included in these
sections, so no inferred menu labels from implementation or prototype.

## Global constraints

- Internal stable Demo, not public scale; no current-version migration needed.
- Preserve existing defaults for old clients; new UI passes explicit PRD choices.
- Unknown sort values after known; stable UUID tie-breaker; never sort only one page.
- P4 evidence groups do not claim a title match proves playing or sender watching.
- Archived identity works do not classify a rebound current identity.
- No source writes, selections, named sets, provider/AI/SMTP/real stack/frontend changes.
- TDD plus one bounded review; deferred historical migration tests remain3.

## Task1: Library query contract

Files: schemas/creator_library.py and library_v2.py; repositories/creator_library.py
and library_v2.py; routes/creator_library.py and library_v2.py; new
repositories/library_queries.py; tests/integration/test_library_query_options.py.

GET Creators adds repeated `platforms` and `languages`, inclusive OR within a field
and AND across fields; old singular platform/language remain accepted. New `sort`
values relevance/followers/recent_publish/recent_added plus legacy name. Explicit
language text remains supported, not restricted to the15 presets. Relevance without
an Activity means deterministic search relevance, not a fabricated game-fit score.
Creator projection adds created_at/updated_at, up to3 recent current-identity work
summaries, latest published time and active current-email/contact status counts.

GET Games adds `website_status=all|available|missing` and `sort=name|recent_updated|
recent_added`. Website uses the existing effective website_url projection, including
its accepted legacy source fallback; an explicit empty manual override stays missing.
Game rows expose created_at/updated_at; incomplete games remain in all results.

- [x] Red tests: create more matches than page size; assert `sort=followers&limit=1`
  returns global maximum, unknown last; OR platform/language filters apply before total.
- [x] Green typed parameters and pure stable full-set filtering/sorting; read metadata
  from effective sources/manual overrides without changing them.
- [x] Red/green recent-publication summary includes only current identity, current
  contact state and updated time; Game website filters plus three sort choices.

## Task2: P4 evidence and order

Files: schemas/activity.py; api/routes/activity.py; new repositories/candidate_queries.py;
tests/integration/test_candidate_query_options.py.

GET query/results adds `evidence=all|current_game|reference_game|related_content|none`
and `sort=relevance|followers|recent_publish|recent_added|added` (legacy added default).
Evidence is current identity work with recorded excerpt AND verification notes,
classified by explicit game_id, exact declared reference work_name, else related.
No evidence means unknown, not never played. Multiple relation categories can apply.
Latest completed evaluation provides hidden score only when current; missing/stale
evaluation falls behind known values with a visible availability state, no numericrank.
Followers/latest publication come from current effective identity; unknown/rebound last.

- [x] Red tests: full-query filtering before pages, explicit current/ref/other/none,
  title-only work remains none, no selection/query/provider changes after sort/filter.
- [x] Green read repository plus typed evidence/availability metadata and hidden
  existing evaluation ordering. No evaluation run or model call is created.
- [x] Red/green ordering: followers/date/newest global, deterministic ties, missing
  last, relevance uses existing evaluation and does not change human selections.

## Task3: delivery

- [x] Update OpenAPI generated contract, focused tests then fullrealRedis suite:
  `docker compose -p fmg-v2-tests -f backend/compose.test.yaml run --rm --no-deps
  -e REAL_REDIS_URL=redis://redis-test:6379/0 test pytest -q --tb=short -x`.
- [x] One independent read-only integrated review; fix only substantiated blockers.
- [x] Write docs/backend-v2-query-options.md with PRD trace/compatibility/test proof;
  explicit-path local commit; notify root/frontend. Do not stage coordinator documents.

Self-check: covers exact five/four/three menu counts and necessary Library row data;
saved named sets, Steam parsing and outreach are explicitly subsequent independent units.

Verification: full2152passed/3previouslydeferred/0failed in169.34s. One independent
integrated review ready/no blocker; minor test combinations recorded in handoff.
