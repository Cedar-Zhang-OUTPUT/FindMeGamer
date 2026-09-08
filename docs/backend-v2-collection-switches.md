# Shared collection switches

Internal Demo increment based on accepted backend8cabb11 and coordinator4bb9d78.
The original PRD751 P15 Settings placeholder is extended by the user's explicit
cloud-shared collection-switch decision. This is not a new service or credentials UI.

## Contract

Authenticated GET `/api/v1/settings/collection` returns `items` for youtube, x,
twitch, instagram. PUT `/api/v1/settings/collection/{platform}` accepts
`{"enabled":false}` (strict boolean), persists only that shared policy value and
returns all items. It does not dispatch anything or clear credentials.

Each item separates `enabled`, `implemented`, `credentials_configured` and
`availability`: disabled, not_implemented, missing_connection, configured_unverified.
Possessing credentials is not proof of provider permission or successful live access.
YouTube/X default on; Twitch/Instagram default off and unimplemented even if toggled on.
Per-query platform selection remains independent: both it and the global policy apply.

## Bounded pause semantics

The root coordinator explicitly approved existing **bounded atomic collection units**
instead of interrupting each individual HTTP request. A Discovery page can contain
search plus channel-detail requests; a Creator source fetch can contain bounded
YouTube pages/video details. An already-started unit may complete and persist.
Check before the next page/source acquisition phase. UI must say “Pause after the
in-flight collection finishes”, not imply immediate cancellation of network traffic.

Discovery retains saved candidates, source outcomes and continuation cursors. A
disabled supported platform carries `blocked_reason=collection_disabled` alongside
its original provider status. Other selected enabled providers keep running. If no
eligible provider remains, the query pauses with a clear reason rather than reporting
exhaustion or fake successful zero matches. Preset-only queries now pause with
`no_available_sources`. Settings re-enable does not dispatch: explicit existing
continue creates the next batch using the saved cursor.

Analyze checks before Creator handle resolution/new job insertion, worker claim,
Creator start, fresh source fetch and the following new visual/contact acquisition
wave. Source checkpoints already written survive the pause and are reused. Existing
Game Analyze and Library-only matching/evaluation are independent of these switches.

The four existing Analysis statuses are retained. Administrative pause adds a
durable `collection_paused` marker and typed public `waiting_reason`:

- `collection_disabled`: the Creator channel is disabled; no resume available.
- `explicit_resume_required`: enabled again but the paused task awaits the user.
- null: not paused. `resume_available` exposes the action explicitly.

An underlying queued/running status is not a failure; UI must prioritize waiting_reason
over its generic spinner. Authenticated POST `/api/v1/jobs/analysis/{job_id}/resume`
requires Idempotency-Key, clears the pause only while enabled, and dispatches the
same job/checkpoints. Replayed successful resume requests do not redispatch. A queue
publication failure restores the pause so the explicit same-key retry can recover.
Ordinary worker retries/duplicate deliveries cannot silently resume a paused task.

Scheduled due selection excludes disabled YouTube **before** its limit, so overdue
Creators cannot starve Games. It leaves source data and original due dates intact.
Switch updates do not backfill or replay jobs; subsequent ordinary scheduler ticks
continue applying the existing schedule to enabled sources. Already-paused active
jobs still require explicit resume and are not replaced by the scheduler.

## Storage and boundaries

Migration0013→0014 adds `shared_settings.collection_enabled` (JSON map with default
fallbacks) and `analysis_jobs.collection_paused` (false). It preserves intervals,
secrets, Profiles, works, selection/batch history and queued job identities. Maintenance
deployment may stop services. No rolling-worker or corrupted-database compatibility.

No frontend, real local stack,18090, cloud, keys, provider calls, SMTP, push or deploy
was changed. Tests use fmg-v2-tests and synthetic provider transport. Final full
regression with realRedis passed2140 tests, with3 explicitly deferred skips and one
existing Starlette deprecation warning, in162.29s. No failures. This includes the
current0013→0014 preservation test and18 new tests across settings, Discovery,
Analyze, source-checkpoint recovery and migration. One bounded independent integrated
read-only review returned ready with no substantive blocker. No real-provider or
whole-product/SMTP completion is claimed by these isolated results.

Three historical live-migration tests are explicitly deferred/skipped: current
runtime mutations on database0003 during migration; frozen old-writer overlap; and
the three-party old-writer/poll/migration cycle. These contradict the user's explicit
maintenance-window boundary. No old-ORM/rolling compatibility was added to satisfy
them. Current0013→0014 migration preservation remains a mandatory test. The earlier
Handle tests now allow the new read-only policy query before provider resolution,
while continuing to assert no database transaction spans that network operation.
