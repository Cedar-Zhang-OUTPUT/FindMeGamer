# Analyze + collaboration frontend fixture

This **new** isolated instance runs accepted backend
`5706ad76f924991b80ee2a7fb6806528366be5ce` from a `git archive`, with actual database
revision `20260908_0019`. It includes accepted collaboration C and the Analyze
bridges. No existing instance was upgraded, restarted, reset or used for this unit.

- Origin: `http://127.0.0.1:64692`
- Project: `fmg-match-frontend-6df993907ce0`
- Queue: `match-frontend-6df993907ce0`
- Private directory:
  `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-xmmhoufp/private`
- Read `client.json` inside the client/E2E process; never print its key. Its initial
  `game_id` is the separate Match seed. Analyze IDs are in `analyze-report.json`.

Port62611 remains the frontend's separate P7 fixture. The new control window stays
with the backend until the coordinator explicitly hands it to frontend. Do not run
fault checks while frontend is using the instance.

## What is real, and what is synthetic

API authentication, encrypted settings, job creation/polling/retry, Celery worker,
ProductionAnalysisRuntime, source gateways, DeepSeek schema validation, bounded
pipeline concurrency, PostgreSQL checkpoints, publication and filesystem artifacts
are real. No successful business route, task or Profile write is mocked. There is
no Beat in this test stack; this unit does not re-test scheduled execution.

Only upstream responses are synthetic. API and Worker stay on the existing Docker
internal network. The fixed loopback relay, HTTPX destination guard and socket-free
SMTP capture are reused. SMTP remains synthetic and this unit does not send mail.
No actual provider/model calls, credential lookup, Keychain, AWS or production
changes were made. The same safe Match and drafting endpoints remain available.

For this exact backend pin only, the launcher installs the Analyze boundary and
the existing SMTP capture. Older pins keep their behavior. Steam's base changes to
the same strict fixture server. Only accepted literal endpoints are allowed;
unknown schemas, query shapes, identities and credentials fail closed.

The real `VisionImageLoader` receives a synthetic-only resolver and PageTransport.
Only three exact `https://analyze-fixture.example/assets/*.png` URLs are allowed.
The resolver's public address is a validation token, **never a network target**.
The transport actually downloads a complete CRC-valid one-pixel PNG from the local
HTTP fixture. The real loader still checks bounds/MIME/magic bytes and Base64;
the model fixture accepts only those inline bytes. No real DNS, video download,
thumbnail URL delegation to a model, or fake visual pipeline is used. A separate
fixed-image check verifies the download and rejects a real external hostname.

## Synthetic identities and normal operations

| Source | Input | Coverage |
| --- | --- | --- |
| Steam | `https://store.steampowered.com/app/900000001` | One synthetic game, one actual PNG cover download |
| YouTube | `https://www.youtube.com/@analyzefixture` or `/channel/UCanalyzeFixture01` | 11 public videos, two thumbnails, source email |
| X | `https://x.com/i/user/900000001` | Public user + 21 original recent posts, three batches and one reduction |

These are finite fixture identities, not a general source proxy. After the smoke
they already exist; frontend should use those saved Library IDs and `reanalyze`,
not expect a second URL-only duplicate to bind over the existing identity.
The success smoke creates its own initial identities and is intended for a fresh
instance. To repeat the entire first-binding smoke, create a separate instance:

```sh
python3 integration/match_frontend/manage.py start --backend-revision 5706ad76f924991b80ee2a7fb6806528366be5ce
python3 integration/analyze_frontend/smoke.py /exact/new/private/directory
```

The manager's existing `status`, `stop`, Match `smoke` and `failures` commands retain
their explicit owned-directory requirement. Do not run generic failure commands
during someone else's control window. Stops retain database and synthetic keys.

## Fault controls and evidence

Analyze has a separate private `state/analyze-control.json`, not an application
endpoint. Use `control(directory, stage="creator_brief", mode="always"|"once")`
from `integration/analyze_frontend/smoke.py` within an exclusive test window.
Calling `control(directory)` resets to none. Each call assigns a fresh token;
`once` is consumed once per running upstream process (model requests are on the
single actual worker). Restarting that process resets the consumed-token memory.
The smoke restores none in `finally`. This narrow control is not a production API.

Events contain only fixed labels and statuses. In each serialized scenario the
event offset and returned job ID connect counts to the actual task; no prompt,
key, email or full provider response is logged. `analyze-report.json` contains only
public IDs, revision and successful checks. Artifacts remain in the actual
filesystem artifact store inside the worker; PostgreSQL retains checkpoint nodes.

## Verification on 2026-09-08

- TDD: three new missing runtime/pin boundary checks and one missing checkpoint
  count assertion first failed, then passed. All **12 Analyze harness tests** and
  **57 existing Match/outreach harness tests** passed.
- Actual HTTP→API→Celery→PostgreSQL smoke passed all five scenarios on its first
  execution: Steam source-only import (zero model/image calls), manual edit, Analyze
  same UUID/reference preservation; YouTube first handle binding then 11 videos,
  two maps, real thumbnails, four reductions and Brief; X 21 posts, three maps and
  reduction on the original UUID; persistent core Brief503→failed preserving exact
  previous Creator/works, then explicit new-job retry; one Brief503→200 on the same
  job with source/map/visual/reduction counts unchanged.
- The separate actual-loader test initially exposed an ambiguous `fixture` module
  import when launched directly from the Analyze directory. The harness now loads
  the Match fixture by explicit path. The corrected fixed-image loader test passed;
  no production module changed. It asserts exactly one actual asset HTTP event,
  real inline PNG output, and refusal of external/unknown destinations.
- Database readback: five succeeded jobs and one intentionally failed job; all
  three X map nodes plus X source/final, and the expected YouTube source/batch/
  visual/contact/reduction/Brief checkpoint nodes. Queue depth zero, no queued or
  running analysis jobs, Analyze controls none.
- After the path-only harness correction, only this new API/Worker pair was
  restarted. A fresh actual X reanalysis passed on the same UUID with 21 works and
  sample size21; queue remained zero (now six succeeded jobs plus the intentional
  failed job). Earlier instances were not touched.
- One bounded read-only GPT-6 Astra / Medium review: **Accept**, no blocking
  findings. Recorded nonblocking follow-up: the YouTube counter helper checks all
  expected stage/download counts but, unlike the Game/X checks, does not reject
  extra unrelated endpoint labels. No extra review or full backend rerun followed.

This is an isolated real-runtime acceptance against synthetic upstreams, **not**
real X/YouTube permission verification, model-quality acceptance, external SMTP,
packaged frontend GUI acceptance, deployment, or a repeated full backend test suite.
The new instance remains available for frontend Analyze/C integration.
