# Match frontend fixture

This is a separate, test-only environment for packaged Electron Match E2E. Each instance runs an explicitly accepted backend revision from a `git archive` snapshot, with PostgreSQL, Redis, and an actual Celery worker. The default remains `cad55656a9a15ef183c6e0ba4ba608bd61a7a1b5` / `20260908_0012`; a separate instance can now select the accepted collection-switch revision below. It never mounts the changing repository backend. The existing `fmg-frontend-http` environment on port 18090 is unrelated.

## Current running instance

- API origin: `http://127.0.0.1:53251`
- Docker project: `fmg-match-frontend-5c41f8e32153`
- Dedicated queue: `match-frontend-5c41f8e32153`
- Private directory: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private`
- Private client file: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private/client.json`

Read `base_url` and `workspace_key` from that file inside the E2E process. The file also provides `game_id`, `reference_work_ids`, `backend_revision`, and `queue`. Never paste its contents into chat, logs, traces, screenshots, or committed files. The directory is mode 0700; generated keys and client/ownership files are mode 0600. Keys are random synthetic credentials, unrelated to Keychain or existing environments. There are no real provider credentials.

The seeded Game is **Moonseed Garden Together**, with a meaningful description, tags, and a synthetic cooperative gardening reference. Successful smoke Activities and matched results remain available for inspection. E2E should create its own Activity with the seeded Game. The shared Library contains six synthetic creators and eight distinct works after smoke.

## Real boundaries and expected behavior

The API authenticates normally, stores synthetic provider secrets through the accepted settings API, and dispatches real planning, discovery, and evaluation tasks. Workers use the accepted YouTube, X, and DeepSeek gateways and actual HTTP to strict loopback fixture servers. No successful task, repository write, application route, or business output is mocked.

API and worker run identical fixture configuration. YouTube and X each return two pages with repeated accounts/authors and content; the final page has no cursor. One creator per platform has unknown followers; X audience country remains unknown. The model fixture handles the accepted `SearchPlanOutput`, `EvaluationScreenOutput`, `EvaluationMatchBrief`, and `EvaluationRankOutput` schemas. It uses supplied candidate/work IDs; Brief confidence remains `limited`, viewing stays false, and numeric ranking stays internal.

All app, worker, PostgreSQL, and Redis containers are attached only to the Docker internal network. Docker Desktop does not publish internal-network ports, so a fixed-target relay exposes the discovered loopback port and forwards API paths only to `api:8000`. Its ingress network disables IP masquerading. The relay has no credentials or private mounts. Application HTTP transports additionally reject destinations outside the four explicit fixture endpoints before opening a connection. No Beat, SMTP service, external provider fallback, real upstream calls, or production control route is used. Settings connection-probe routes and unrelated enrichment routes are deliberately unsupported by the fixture.

## Commands

Run from the repository root. Existing-instance commands always require its exact owned private directory:

```sh
python3 integration/match_frontend/manage.py status --directory /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private
python3 -m unittest discover -s integration/match_frontend -p 'test_*.py' -v
python3 integration/match_frontend/manage.py smoke --directory /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private
python3 integration/match_frontend/manage.py failures --directory /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private
```

`start` without a directory creates another uniquely named environment with fresh private credentials and a pinned source archive. `start --directory …` resumes the exact owned instance; read the client file again because Docker may allocate a new port. `stop --directory …` stops only that project's services, retaining its database and credentials. Keep the current environment running until the coordinator/user asks to stop. No global cleanup command is provided.

## Deterministic controls

Controls live only in this fixture's private `state/control.json`; they are shared by API and worker and are not application endpoints. Use the CLI to update the file atomically. Every invocation resets unspecified fields to `none`.

```sh
python3 integration/match_frontend/manage.py control --directory /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private --source-fail x
python3 integration/match_frontend/manage.py control --directory /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private --model-fail planning
python3 integration/match_frontend/manage.py control --directory /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private --hold youtube
python3 integration/match_frontend/manage.py control --directory /var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-huhrse5v/private
```

`--source-fail` supports `youtube` or `x` and returns HTTP 503. `--model-fail` supports `all`, `planning`, `screening`, `deep`, or `ranking`, also HTTP 503. `--hold` supports either source or model stage. Each held request lasts at most 15 seconds, below gateway timeout; clearing the control releases it promptly. A `held` event in `state/events.jsonl` confirms that the real HTTP request reached the fixture. Events contain fixed endpoint labels and statuses only.

The accepted backend reports mixed source failure as query `paused`, batch reason `provider_failed`, and the failed source as `failed`, preserving the successful source's results. Clear the fault and explicitly Continue to recover. A model failure requires the accepted plan/evaluation Retry API. Stopping while an actual source page is in flight allows that page to finish atomically, then prevents the next page from starting; prior results remain and Continue resumes.

Controls apply to the whole owned fixture instance. Do not run the failure smoke or change controls while another frontend scenario is using it. The failure smoke restores all controls in a `finally` block. Success and failure reports contain only public IDs, state labels, counts, and revision information.

## Verification evidence

The success smoke checks Game/reference snapshots; actual Flash planning; two pages on each source; six deduplicated accounts and eight Library works; stop/continue identity preservation; actual Flash screening and six Pro deep calls plus Pro ranking; typed limited-evidence Briefs; no automatic selection; no numeric score fields in public evaluation output. Failure smoke covers explicit model retries, source partial failure recovery, and stopping a held actual HTTP page. No full backend suite or real external calls are required.

Validated on 2026-09-08: 10 focused harness tests pass, both actual HTTP smoke commands pass, and PostgreSQL reports `20260908_0012`. The transport guard rejects an external DeepSeek URL before network access. At handoff, Celery active/reserved tasks, dedicated Redis queue length, active batches/plans/evaluations, and in-flight source pages all equal zero; every control is `none`. Public-only reports are retained as `success-report.json` and `failure-report.json` in the private directory. A Docker Desktop control-file rename visibility gap was reproduced and fixed only in the test harness, with a focused regression test.

The coordinator independently repeated all 10 harness tests (3.216 seconds), the success smoke, and the failure smoke on the same date; all completed successfully. Success exercised two pages per platform, six unique creators, eight works, one planning call, one screening call, six deep calls and one ranking call. Failure recovery exercised planning unavailability, a failed X source while preserving YouTube results, failed deep evaluations, and Stop during a held page followed by explicit Continue. These are actual accepted-backend HTTP/worker/database flows against synthetic upstreams, not live provider acceptance.

The instance has now been formally handed to **FindMeGamer 前端优化** for the Match packaged E2E unit. That task owns the fixture control window until it reports completion; the coordinator and other tests must not change global controls concurrently. Leave the instance and the unrelated port-18090 environment intact.

## Separate collection-switch instance

The coordinator created this additional instance on 2026-09-08 for the next Settings/Match collection-switch increment. It does **not** replace or upgrade the original Match instance.

- API origin: `http://127.0.0.1:59414`
- Backend: `b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857`; actual PostgreSQL migration independently read as `20260908_0014`.
- Docker project: `fmg-match-frontend-737717b10d72`; queue: `match-frontend-737717b10d72`.
- Private directory: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-7bmwetos/private`.
- Private client file: the same directory's `client.json`. Credentials and Game/reference IDs are separate; never use the old instance's key or IDs.

To create another fresh instance at this accepted revision:

```sh
python3 integration/match_frontend/manage.py start --backend-revision b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857
```

Only explicitly accepted hashes are supported, not branches or `HEAD`. An existing owned directory cannot change revision; the CLI rejects that operation before starting anything. Existing-instance commands still use its exact private directory, and the default old-revision instance remains operable. Shared private files and controls must not be changed by concurrent tests.

The manager extension was verified with RED→GREEN tests: 14 harness tests pass. One bounded independent read-only review found no blocker. Both actual HTTP success/failure smokes passed against the new instance. An additional real API/worker check confirmed shared GET/PUT persistence without clearing credentials, zero YouTube requests while disabled and two X pages yielding three retained creators, no automatic continuation when re-enabled, explicit Continue adding YouTube to reach six without losing those three, and an enabled Twitch preset remaining `not_implemented`. The test restored YouTube/Twitch policy values; fault controls are at their defaults. The verifier is retained at `/tmp/fmg-collection-b2b15f4.ECWBeS/shared_http_check.py`; it only targets this synthetic instance.

This instance supports the accepted collection settings and persisted Match flow, not successful provider connection probes or actual SMTP delivery. Continue using the separate old Settings fixture for its connection/capture tests. Neither these checks nor the test-only transports satisfy final packaged GUI/Keychain acceptance.

## Separate full-query and named-set instance

The next frontend read-query unit uses another independent instance. No earlier instance was replaced or upgraded.

- API origin: `http://127.0.0.1:65164`.
- Backend: `a852307d6908e671ae1998c9741f19ffe65f5048`; actual database `20260908_0015`.
- Project: `fmg-match-frontend-50b33aac62cf`; queue: `match-frontend-50b33aac62cf`.
- Private directory: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-mjpzjv70/private`.
- Read the separate `client.json` in that directory inside the test process; never print it. Seed Game/reference IDs and synthetic credentials are not shared with earlier instances.

This backend includes collection switches, the full-set query contract, named subsets (`9fe851e`), and comparison-only language aliases. The manager only added this accepted hash/migration pair. A new lifecycle test first failed on the missing allowlist entry, then all 15 harness tests passed (3.278 seconds); one bounded read-only review found no blocker. Old version/owner/credential checks remain unchanged.

Actual HTTP success smoke passed: two pages per platform, six creators, eight works, real planning/screening/deep/ranking worker stages against strict local synthetic HTTP. An additional check at `/tmp/fmg-query-http-a852307.fSEi1a/check.py` verified durable saved-set replay with a new HTTP key, three-member membership and full-subset sorting before paging, read-only restore with unchanged query and zero extra events, all five evidence filters, and `en`/`English`/localized label Library queries. A fresh real worker discovery also retained a manually labeled English creator under the `en` filter. The original manual language layer was restored; a prior evaluation can legitimately be stale after this edit/recollection, so a new UI E2E should create its own Activity/evaluation rather than assume the old smoke evaluation remains current.

The first failure-smoke attempt did not observe the requested planning fault: its planning endpoint returned HTTP 200 and the persisted plan was ready on attempt 1. A subsequent run observed HTTP 503, and all four failure/recovery scenarios passed with the accepted failure codes. This is a test-only control-visibility limitation, not a passing assertion from the first attempt or evidence of a production regression. No application code was changed to mask it. When injecting faults, check the fixed-label fixture events to confirm the requested fault actually reached the request before attributing an unexpected success to the application. Successful failure results remain in this instance's `failure-report.json`.

At handoff the dedicated queue is empty, planning/batch/evaluation active counts are zero, and all controls are `none`. The frontend task owns this new instance's control window after formal handoff. Keep the three earlier environments and their data intact. This is not a provider connection-probe, SMTP, final package, or real-service acceptance environment.

## Prepared drafting model boundary (not yet a running outreach instance)

The local fixture source now additionally recognizes accepted Outreach A's exact
`SlotValues` JSON schema, Flash model, three-message gateway envelope and 2048 output
budget. It copies the three supplied bound names/reference unchanged and derives the
fourth value only from the supplied synthetic evidence excerpt with a final period;
verification notes must be present. It does not generate a full mail, new sources or
sender confirmations. Malformed contracts fail closed; fixed `drafting` event labels
contain no payload or credentials.

`--model-fail drafting` and `--hold drafting` prepare explicit per-stage failure/hold
tests; existing source/planning/evaluation controls remain compatible. No new accepted
revision mapping, private instance, database upgrade, SMTP transport or worker restart
was added with this change. In particular, port65164 remains pinned to0015 and cannot
serve Outreach A's new routes. Create a separate accepted A+B instance only after B
acceptance and a new handoff, keeping the current frontend control window intact.

TDD first produced ten failing assertions across the 26-test suite; implementation
then passed all26 (15 prior +11 new) in8.444s. The coordinator read all three changed
files, checked the accepted gateway/schema seam and repeated all26 successfully in
8.434s. One bounded review, no second broad audit; no Docker/real provider/SMTP/UI
scenario was run for this fixture-source increment. RED/GREEN logs are retained in
`/tmp/fmg-draft-fixture-tdd.kkypwV/`.
