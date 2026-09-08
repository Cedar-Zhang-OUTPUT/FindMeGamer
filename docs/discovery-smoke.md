# Small YouTube/X smoke harness

This separate harness pins backend code to
`c8abe9b1a00d16ae6ea65117d1ec20b412befce1`. It does not change business logic,
18090, the normal local service, AWS, or `fmg-v2-tests`.

## Default fixture run

Prerequisites: Docker Compose v2, the existing `backend-test:latest` Python 3.13
dependency image, local Git commit above, and a host Python 3 with standard library.
No provider key, AWS credentials or Keychain access is required.

```sh
python3 -m unittest integration.test_discovery_smoke -v
python3 integration/discovery_smoke.py
```

Each invocation creates a random-named Compose project, independent Postgres and
Redis, random Workspace key/master key, read-only pinned backend worktree, API
on a random **127.0.0.1** port, and a real Celery Worker on a dedicated queue.
No Beat or SMTP is configured; automatic analysis tasks are not submitted.
Local fixture HTTP endpoints run inside the worker and use real provider gateways.
Other provider endpoints are closed loopback; host credentials/proxy environment
is not passed through. This is logical harness isolation, not a network firewall.
Docker's own client configuration can still inject proxy variables; both provider
gateways explicitly use `trust_env=False`, so they do not consume those variables.

The runner submits Game/Activity/query through authenticated HTTP, waits for
Celery execution, reads results back and verifies shared Library identities.
It checks one YouTube search + one channel request and one X request, even when
fixture responses contain next-page cursors. No second page or automatic write
retry is issued. The backend's query budgets enforce the same ceilings.

By default the run's containers and database volumes are removed. Private 0600
client/master/report files and the pinned worktree remain under
`.local/discovery-smoke/<run-id>/` (gitignored); directory mode is 0700. `--keep`
explicitly leaves only this run's containers for inspection; avoid it for live
credentials unless that retention is intentional. No mail history is imported.

## Live phase — explicit authorization required

The coordinator must first obtain permission for these exact tiny requests and
X credit consumption. Afterwards provide one **explicitly chosen**, user-owned,
non-symlink **0600** JSON file containing one or both permitted fields:

```json
{"youtube": "<YouTube Data API key>", "x": "<X app-only Bearer token>"}
```

Do not paste keys into chat, commit the file, or put tokens in CLI arguments.
No credential file is read in fixture mode; supplying one is rejected. Live mode
requires all three flags: `--live --acknowledge-provider-costs --credentials-file`.
The tool never searches the Keychain, existing service databases, cloud secrets,
shell environment or production configuration for missing values.
An omitted platform is explicitly reported as `not_run` / `credential_not_supplied`
with zero HTTP requests; the other platform can finish independently. The operator
must delete the temporary credential handoff file afterwards. The default cleanup
removes the isolated DB volume containing its encrypted copy, not original keys.

```sh
# Only after explicit authorization.
python3 integration/discovery_smoke.py --live --acknowledge-provider-costs \
  --credentials-file .local/approved-discovery-credentials.json
```

YouTube uses one video search page, `page_size=5`, at most two HTTP requests
including channel enrichment. X uses one recent-search page, `page_size=10`,
at most one HTTP request. Default keyword is `indie game`; explicit
`--youtube-query` / `--x-query` can change it. There are no connection-probe calls,
automatic retries, continuation calls or extra requests to fill result counts.
Only permitted credentials are written, encrypted, to the new isolated DB via
Settings HTTP. They are never copied into the pinned source or Docker environment.

Reports contain request counts, result counts and safe categorical failure states,
not tokens, headers, original provider bodies or Creator/email data. Fewer results,
401/403/429 and uncertain outcomes are reported honestly; the runner does not
bypass quotas. `completed` describes completion of the inspection workflow, not
guaranteed provider access. Check each provider's status, issues and usage.
The worker's test-only HTTP observer records one endpoint label and HTTP status
per actual transport call (or `transport_error`); it never records the URL,
query string, headers or response body and never retries. Reports also include
verified Library identity and persisted work counts, plus each batch stop reason.
`target_reached` is distinct from budget exhaustion: both can stop a one-page run,
and the report must not claim a budget stop when the batch stopped at its target.
The live phase proves only small discovery/Library access, not full AI analysis,
large pagination coverage, email delivery or production readiness.

## Preparation evidence

Fixture dry-run `fmg-discovery-smoke-168935c3` passed with a real Celery Worker:
YouTube search 1 + channels 1; X search 1; one Library account each. Both provider
responses offered continuation tokens; no follow-up request occurred. Containers
and database volumes were removed after the run. No real provider calls or user
credentials were accessed. Unit tests also exercise live guards using explicitly
synthetic temporary credentials, without network I/O.

The extended fixture run `fmg-discovery-smoke-aacc409d` additionally verified
three HTTP 200 observations, one persisted work per platform and `target_reached`
stop reasons. Seven targeted unit tests passed; independent bounded review found
no blocker in this reporting-only increment.

## Authorized live evidence — 2026-09-08

Run `fmg-discovery-smoke-d89bf7c3`, pinned backend above, query `Minecraft`:

- YouTube: exactly one search and one channels HTTP request, both 200. Five
  works mapped to four unique accounts; all four Library identities and five
  persisted works verified through HTTP after real Celery execution.
- Query paused with source `more`, batch reason `target_reached`, usage 2 requests /
  5 provider items / 0 unknown requests. No continuation or retry. The hard
  two-request ceiling was reached, but the actual stop reason was the batch target,
  not a claimed budget-exhaustion transition.
- X: not run, zero HTTP requests. Reading the specified project Keychain item
  did not return; the waiting read was terminated without changing the original
  credential. It was omitted from the handoff file. This run does not verify X
  live HTTP-to-Library integration or establish a platform quota/auth failure.
- Temporary credential handoff file removed; isolated containers and DB volumes
  removed. Original project configuration was only read, not changed. No cloud,
  18090, SMTP, model, token-probe, pagination or unrelated service calls.

The final fixture `fmg-discovery-smoke-db7a4d22` passed before this live attempt;
eight targeted unit tests pass including partial-credential handling.
