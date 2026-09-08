# Match frontend fixture

This is a separate, test-only environment for packaged Electron Match E2E. It runs the accepted backend revision `cad55656a9a15ef183c6e0ba4ba608bd61a7a1b5` from a `git archive` snapshot, with fresh PostgreSQL migrations through `20260908_0012`, Redis, and an actual Celery worker. It never mounts the changing repository backend. The existing `fmg-frontend-http` environment on port 18090 is unrelated.

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
