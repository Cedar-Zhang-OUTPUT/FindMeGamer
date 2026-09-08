# Game-driven Discovery planning

This adds the missing P2/P3 server conversion, not Deep Match or Creator analysis.
Existing Activity/Game/Discovery/Library APIs remain supported. English planning
uses the existing encrypted `deepseek` connection and `deepseek-v4-flash` text model.
No additional service, endpoint selector, browser or model tools are introduced.

## Authenticated API

All endpoints require the existing Workspace bearer key. Every POST needs an
`Idempotency-Key`. Replay the same key/body after an uncertain HTTP/broker result;
use a new key for a new intentional operation or changed input.

| Method/path | Behavior |
| --- | --- |
| POST `/api/v2/activities/{id}/discovery-plans` | Persist input and queue planning, 202 `{plan_id,status}` |
| GET `/api/v2/activities/{id}/discovery-plans` | Newest first, `items/total/limit/offset`; limit defaults 50, max 200 |
| GET `/api/v2/discovery/plans/{id}` | Poll plan state and follow `query_id` when available |
| POST `/api/v2/discovery/plans/{id}/retry` | Explicit retry of failed/expired execution; ready plan only redispatches its existing first batch |

Minimal request, after creating an Activity with selected reference IDs:

```json
{
  "mode": "discover",
  "platforms": ["youtube", "x"],
  "keywords": ["gameplay"],
  "filters": {"countries": ["US"], "include_unknown_country": false},
  "batch_target": 100,
  "result_limit": 600,
  "batch_request_budget": 20,
  "batch_scan_budget": 1000,
  "total_request_budget": 120,
  "total_scan_budget": 6000
}
```

`mode` is required: `preview` generates only a saved plan; `discover` also starts
one existing DiscoveryQuery/first batch after success, with no extra approval page.
`platforms` is a unique nonempty subset of youtube/x; Twitch/Instagram cannot be
enabled by model output. Keywords are optional (up to 20, each 100 characters).
All existing filter semantics and budget limits are shared with QueryCreate.
No model-authored filters can replace the user's chosen filters. Country/language
remain independent and are never derived Creator facts.

## States, input ownership and failures

`queued → running → ready|failed`. GET includes immutable `source_snapshot` and
`conditions`, typed `output`, `error_code`, `retryable`, `attempt`, `model`, and
nullable `query_id`. Output is `{summary,rationale,queries,provider_queries}`;
each query is `{platform,terms}` and native query strings are server-compiled.

- The Activity's **effective** Game fields and chosen references are frozen; no
  live Profile reread during model execution. Different filters/keywords produce
  a new plan/query snapshot in the same Activity. To use newly edited Game or
  reference choices, create a new Activity from those effective fields.
- Name-only is accepted. A URL-only Game without name, description or tags fails
  `game_context_required`; no URL is fetched or turned into invented facts.
- Planning writes no Game/Creator Profile fields. A later failed plan does not
  delete or overwrite an earlier ready plan. The list endpoint exposes both.
- `planning_configuration_missing`: configure the existing DeepSeek connection,
  then retry. `planning_model_unavailable`, `planning_model_output_invalid`,
  `planning_model_rejected`, `planning_failed`: explicit retry available, no loop.
- An expired 300-second claim is exposed as failed / `planning_outcome_unknown`;
  only explicit retry can start a new generation. Late results from the old claim
  cannot overwrite it. Active execution retry returns 409.
- Queue unavailable before task dispatch: HTTP 503 `planning_queue_unavailable`,
  saved input retained; replay same key. After a plan/query was saved, discovery
  dispatch failure retains `ready` output/query and sets
  `planning_discovery_queue_unavailable`, `retryable=true`. Retry redispatches the
  same first batch; it does not rerun the model or create another query.
- Each failed-attempt retry is a new intentional POST with a new key. Repeating
  the same retry key only replays that operation, not an unbounded new attempt.

Model input is allowlisted effective text only, with separate untrusted JSON and
English system instructions. Dedicated URL/cover/contact/opaque source metadata
fields and configured service secrets do not enter the prompt. User-authored
description/reference text can itself contain a URL or contact; it remains
untrusted text and is never fetched or used as an endpoint. Structured output has bounded descriptions and
at most three plain keyword phrases per platform; the compiler quotes them and
only appends fixed `-is:retweet` for X. Model-provided endpoints, tools, native
operators or alternative platforms cannot become executable requests.
The existing DeepSeek gateway permits one bounded schema-repair call; planning
adds no network retries. A 2048-token limit applies per model call.

Discovery pages use the existing gateway and budgets, up to 50 YouTube / 100 X
items per page, limited by submitted scan budgets (X requires at least 10).
Small impossible budgets stop via existing budget states; no budget is increased.
One platform has one active native query. Variants never create extra queries.
The explicit `/activities/{id}/queries` provider-native path remains available.

## Migration and verification

Migration `20260908_0011` adds only `discovery_plans`, linked to Activity and an
optional unique DiscoveryQuery. Upgrade from 0010 preserves existing query data.
Maintenance windows remain supported. Downgrade refuses to drop nonempty planning
records; export/back up intentionally before destructive rollback.

Tests cover authenticated API → actual DeepSeek adapter with model HTTP fixture →
persisted plan → existing worker/provider HTTP fixture → Library, preview without
collection, duplicates/replays, failed output/configuration, stale claims, snapshot
changes and migration. These do not call live YouTube or X.

Authorized minimal model check on 2026-09-08: `deepseek-v4-flash`, one HTTP 200,
synthetic Game name and one-sentence description, two structurally valid platform
plans. No personal data/reference input, no provider discovery/SMTP calls. The
existing gateway does not expose actual monetary cost; none is inferred.

Final backend verification: **2049 passed**, zero failures/skips, using the real
Redis test service; one existing Starlette deprecation warning. Independent review
passed for spec compliance and quality, with no blocking findings. OpenAPI export
was repeated with identical SHA-256. No frontend or production environment changed.
