# Small YouTube/X smoke harness — preparation only

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

## Live phase — not authorized or executed by this preparation

The coordinator must first obtain permission for these exact tiny requests and
X credit consumption. Afterwards provide one **explicitly chosen**, user-owned,
non-symlink **0600** JSON file with exactly two fields:

```json
{"youtube": "<YouTube Data API key>", "x": "<X app-only Bearer token>"}
```

Do not paste keys into chat, commit the file, or put tokens in CLI arguments.
No credential file is read in fixture mode; supplying one is rejected. Live mode
requires all three flags: `--live --acknowledge-provider-costs --credentials-file`.
The tool never searches the Keychain, existing service databases, cloud secrets,
shell environment or production configuration for missing values.

```sh
# Only after explicit authorization; this command has NOT been run during setup.
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
The live phase proves only small discovery/Library access, not full AI analysis,
large pagination coverage, email delivery or production readiness.

## Preparation evidence

Fixture dry-run `fmg-discovery-smoke-168935c3` passed with a real Celery Worker:
YouTube search 1 + channels 1; X search 1; one Library account each. Both provider
responses offered continuation tokens; no follow-up request occurred. Containers
and database volumes were removed after the run. No real provider calls or user
credentials were accessed. Unit tests also exercise live guards using explicitly
synthetic temporary credentials, without network I/O.
