# Library union frontend fixture — 2026-09-09

New isolated actual API/Worker/PostgreSQL instance:

- Backend pin `28595d84805137dabbdadd31f26f9fa5b51d988b`, database0019.
- Origin `http://127.0.0.1:56257`.
- Project `fmg-match-frontend-22a23e41318c`, queue `match-frontend-22a23e41318c`.
- Private directory `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-rgunwn5k/private`.
- Read `client.json` in-process for the synthetic workspace key; never print it.
- `union-report.json` contains public test IDs and acceptance evidence.

The source comes from `git archive` of the fixed backend pin. No existing fixture
or production service was modified. Upstream responses alone are synthetic;
real authentication, HTTP gateways, schema checks, queue, discovery publication,
Library merge and evaluation run in the application. No real provider permission,
model-quality or SMTP claim is made. Existing internal Docker network and strict
loopback-only upstream allowlist are reused; no Instagram/Twitch HTTP routes were
introduced. The harness accepts their planning labels for Library-only queries.

## Verified scenarios

1. Pre-seeded YouTube account overlaps the live fixture, plus Twitch and URL-only
   Instagram Library records. Four-platform actual planning/discovery yields8
   unique candidates. Overlap has both library/realtime provenance; unsupported
   live state and complete Library state are separate. Explicit Continue does not
   repeat candidates. URL-only identity is not falsely stale.
2. All8 candidates pass through the same actual evaluation queue. Synthetic model
   responses remain limited-confidence; no sender-viewed claim or auto-selection.
   Expected successful upstream counts: planning1, YouTube search2/channels2, X2,
   screening1, deep8, ranking1. No extra source requests.
3. Disable YouTube live collection: a fresh query still returns its3 Library
   records and `collection_disabled`, with one planning call and **zero provider
   HTTP calls**. The original switch is restored afterwards.
4. Synthetic YouTube source failure alongside X: a fresh query preserves6 Library
   candidates, X reaches exhaustion, YouTube remains explicitly failed and query
   paused. Failure control is restored to none.

Main successful query `175e3079-2850-4aa4-b345-a58fe2bbe7c4`, activity
`9dba9736-ba21-46a3-9dae-da797a4eabcb`, evaluation
`0f89e442-9a62-44b0-8591-0b59778d9b40`.
Disabled query `1ece50c0-5f55-41dc-9f7c-78dbca94b172`; explicit failed-source query
`928d063a-a501-4c96-9c64-77fbc00999ad`.

Harness four-platform regression first returned400, then all57 existing harness
tests passed after expanding only supported planning labels. The first smoke
launcher mistakenly resolved macOS `/var` to `/private/var`, failing the existing
exact owner-path check before any API writes; corrected to preserve the owned
absolute path. All subsequent scenarios passed without application changes.

Frontend now owns this instance; do not run fault controls, stop or reset it during
frontend work. All older instances remain untouched. This pin does **not** yet
include Campaign brief, first-batch selection initialization, or parameterized
unified templates; those are separate follow-up units.
