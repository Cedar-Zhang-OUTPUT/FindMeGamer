# Discovery candidate evaluation

Backend-only internal Demo increment; existing v1 Match is unchanged. Database
revision `20260908_0012` follows `20260908_0011`. Use the agreed maintenance window
for later deployment; this increment does not deploy or change the frontend fixture
server. Existing DeepSeek configuration is reused. No additional provider keys,
acquisition requests, automatic selection, or email sending are introduced.

## API contract

All five endpoints require workspace authentication. The tracked
`backend/openapi.json` contains typed request/response schemas.

| Method/path | Purpose |
| --- | --- |
| POST `/api/v2/discovery/queries/{query_id}/evaluations` | Freeze and evaluate loaded candidates |
| GET `/api/v2/discovery/queries/{query_id}/evaluations` | List this query's evaluation runs |
| GET `/api/v2/discovery/evaluations/{run_id}` | State, child-step progress and usage |
| GET `/api/v2/discovery/evaluations/{run_id}/results` | Ordered candidate evaluations |
| POST `/api/v2/discovery/evaluations/{run_id}/retry` | Explicitly resume failed/expired work |

Both POSTs require `Idempotency-Key`. Create with `{}` to freeze all currently
loaded members, or `{"candidate_ids":["UUID", "UUID"]}` for an explicit subset.
Accepts 1–600 unique IDs belonging to the query. Later Discovery arrivals are not
automatically added. An intentional new run uses a new key.

List/result pagination uses `limit` (default 50, maximum 200) and `offset`.
Results include frozen account identity, typed `match_brief`, `fit_group`, evidence
and stale flags. Numerical scores, rank positions and input ordering are private.
`selected` and `sender_watched` are always false. Model selection for deep evaluation
does **not** represent the user's decision to contact someone.

## Execution and recovery

Screen compact Creator Briefs in groups of 20 using Flash, then evaluate each chosen
creator against the detailed Game Brief using Pro. Deep evaluation uses a bounded
snapshot of existing effective creator fields, analysis and up to 20 known works.
It never fetches new content or invents missing enrichment. Pro ranks successful
Match Briefs in groups of 20 against a shared absolute rubric; the backend merges
private scores, using stable input order for ties. This bounds 100–600 candidate
runs without a giant final prompt. Cross-chunk calibration is less exact than one
global relative ranking; the method version records that deliberate tradeoff.

At most four model steps run concurrently per evaluation. Each success is saved
immediately, so a later failure does not remove an existing Brief. Per-step leases
and ownership tokens prevent duplicate claims and reject late writes. An expired
inference has an unknown outcome and is not automatically rerun: a colleague must
explicitly retry. A retry may incur another model inference charge.

Retry with `{}` for failed/expired steps, or `{"step_ids":["UUID"]}` to choose them.
Successful child steps are retained. Active unexpired work returns 409. A queued or
interrupted run with no active calls can also be resumed. If broker dispatch returns
503, the input was saved: retry the same request and key to dispatch the saved run.

Run states are `queued`, `running`, `completed`, `partial`, `failed`, `no_matches`.
`no_matches` means a successful screening returned no matches, not a model failure.
Failed ranking leaves successful Briefs available with `fit_group=unranked`.
Usage counts logical model operations/attempts and child-step states, **not** actual
HTTP requests, tokens or currency; a gateway schema-repair request may occur within
one logical operation.

## Evidence and stale records

Citation IDs must identify supplied known works. Source URLs and timestamps come
from those records, never model prose. `recorded_evidence` requires an existing
excerpt plus verification notes; metadata alone remains `metadata_only`, and no
works means `unknown`. Even recorded evidence does not confirm that the sender
watched or played anything. Later Outreach must handle that confirmation separately.

Current-game associations use the recorded work's Game ID. Reference-game
associations use its explicitly recorded work name, not keyword similarity in a
post title. Unassociated works remain related content.

Profile/known-work edits mark results `stale`; identity rebinding additionally marks
`identity_changed`. Frozen old-account summaries stay historical rather than being
silently reused for the new account. A candidate already rebound before the run is
created receives no model evaluation of its replacement account. Create a fresh
Discovery/evaluation run when current identities are needed.

## Boundaries

No four-slot email generation, recipient selection, sender-viewing confirmation,
SMTP, new data acquisition or frontend integration in this increment. Those remain
separate units. No public multi-tenant or rolling-upgrade architecture is required.
