# Deployment Task 7 report

## Scope and base

- Immutable base: `4968c69b5c07c42e59fc9e65ff296cd2458fd8df`
- Scope: production read-only API smoke client, resumable Creator seed operator
  wrapper, synthetic fixtures, focused fake-backed tests, and documentation only.

## TDD RED

The focused fixture/operator contract was created before either production
operator script:

- Command: `bash ops/tests/test_operator_scripts.sh`
- Exit: `1`
- Excerpt: `missing executable ops/smoke_test.sh`

This was an artifact-specific RED; it did not invoke Docker, curl, a provider,
or any production path.

## GREEN implementation

- `ops/smoke_test.sh` accepts one safe HTTPS origin and a private key file. It
  places the key only in a mode-0600 curl configuration inside a mode-0700
  temporary directory, passes only the configuration path to curl, and removes
  the exact temporary files through its installed trap.
- The smoke workflow performs only the required GET requests, validates the
  authoritative response shapes, checks the encoded changed-Jobs cursor, and
  proves that the invalid public response-capability GET does not change the
  canonical campaign snapshot.
- `ops/seed_initial_creators.sh` requires the protected Compose env file and
  private input/report files, unsets all root Compose interpolation keys, and
  supplies the same explicit `--env-file` to every Compose operation. It uses
  only `python -m app.cli.seed_creators`, validates/copies its real resumable
  report, replaces the adjacent report atomically, and removes only the exact
  randomized container paths.
- The checked-in seed is synthetic, contains the exact header and 100 unique
  supported Channel URLs, and is rejected by live mode. The documentation CSV
  is header-only.

## Verification

Focused fake-backed contract, run twice on the final code:

```text
$ bash ops/tests/test_operator_scripts.sh
PASS: exact 100-row synthetic Creator fixture
PASS: fake-backed smoke secrecy and resumable seed workflow
$ bash ops/tests/test_operator_scripts.sh
PASS: exact 100-row synthetic Creator fixture
PASS: fake-backed smoke secrecy and resumable seed workflow
```

The fakes cover the successful smoke and seed/resume flows plus unsafe,
malformed, unhealthy, interrupted, failed-row, Docker/CLI/copy, and cleanup
failures. Their argv recordings prove the Workspace key and protected Compose
values are absent, all seed Compose calls use the exact env file, the public
response GET omits authentication, and cleanup remains exact.

The required seed dry-run passed on the final fixture and printed only the
quoted copy/validation/CLI/report/exact-cleanup plan. It made no Docker or
provider call and created no report:

```text
$ FMG_DRY_RUN=1 bash ops/seed_initial_creators.sh ops/tests/fixtures/creator-seed-100.csv
DRY RUN: synthetic Creator fixture validation passed; no Docker or provider call was made.
```

Task 1–6 operator/Compose regressions all passed:

```text
$ bash ops/tests/test_compose_config.sh
$ bash ops/tests/test_bootstrap_server.sh
PASS: bootstrap server contract
$ bash ops/tests/test_backup_scripts.sh
PASS: backup and restore script contract
$ bash ops/tests/test_s3_configuration.sh
PASS: S3 lifecycle and Instance Role validation contract
$ bash ops/tests/test_deploy_script.sh
PASS: deploy script contract
$ bash integration/run.sh --contract
PASS: integration recovery contract
```

Related backend integration coverage ran against the existing isolated backend
test Postgres/Redis services only:

```text
$ docker compose -f backend/compose.test.yaml run --rm test pytest -q \
    tests/integration/test_seed_creators.py \
    tests/integration/test_session_api.py \
    tests/integration/test_job_polling_api.py \
    tests/integration/test_profiles_api.py \
    tests/integration/test_settings_api.py \
    tests/integration/test_smtp_settings_api.py \
    tests/integration/test_public_responses.py \
    tests/integration/test_campaign_api.py \
    tests/integration/test_match_api.py
226 passed in 17.36s
```

Static and safety gates:

- `bash -n` passed for both new scripts, the focused test, and all existing
  `ops/` and `integration/` shell scripts.
- Exact fixture/header/100-row/uniqueness and header-only documentation checks
  passed; executable modes are 0755 and data/report modes are 0644.
- `git diff --check` passed. Exact-scope inspection contains only the six Task
  7 paths.
- Secret/private-key pattern, process-argument, unsafe `source`/`eval`, broad
  deletion/prune, external-call, and generated-artifact scans passed. There are
  no `__pycache__`, `.pyc`, or `.DS_Store` artifacts in scope.
- ShellCheck is not installed, so its optional gate was not available.
- No real production API, Creator/provider, AWS, SMTP, SSH, response action,
  production file, or production Docker operation was performed. Existing
  `backend-postgres-test-1` and `backend-redis-test-1` remained healthy.

## Self-review and concerns

The implementation was checked against the actual API route schemas and the
existing seed CLI source/report loader rather than synthetic contracts. Error
paths emit endpoint/status or aggregate counts only and do not dump response
bodies, Creator rows, contacts, notes, secrets, or upstream diagnostics.

No binding concerns remain within the stable company-internal Demo boundary.

## Fix round 1 — operator portability and cleanup

### TDD RED

All four regression contracts were added to
`ops/tests/test_operator_scripts.sh` before their production fixes. The first
focused run against `9b637b9cfa3ce8b5e50de6b271cef2077e44a589` exited nonzero and showed both
host-Python references and the fake curl rejecting the first request because
`--disable` was not its first argument:

```text
$ bash ops/tests/test_operator_scripts.sh
ops/seed_initial_creators.sh:39:  python3 ...
ops/smoke_test.sh:40:python3 ...
AssertionError: smoke: health/live request failed
```

After only the smoke portability/curl isolation change, the same focused test
continued to exit `1` on the new production-coupled live target fixture:

```text
AssertionError: creator-seed: Creator CSV must use the exact header and contain 100 unique supported Channel URLs
task7_fix1_target_RED_exit=1
```

The fixture contains valid `youtube.com` and `www.youtube.com` Handle targets,
an optional trailing slash, and a minimum-length Channel ID. The fake executes
the exact Python validation program passed to the API container, so the old
fixed-22-character validator caused this RED.

The cleanup-failure regression was also isolated with the production cleanup
held at its prior `|| true` behavior. Business/report work succeeded, the fake
failed one exact remove, and the focused test exited `1` at its cleanup return
assertion while confirming all three cleanup calls were attempted:

```text
AssertionError
task7_fix1_cleanup_RED_exit=1
```

### GREEN changes

- The live container validator now mirrors the backend Creator target contract:
  exact HTTPS `youtube.com`/`www.youtube.com` origins without credentials,
  ports, query, or fragment; Channel IDs use `UC[A-Za-z0-9_-]{6,126}` and
  Handles use `@[A-Za-z0-9._-]{3,30}`, both with an optional trailing slash.
  Raw input URLs remain nonempty and unique. The checked-in dry-run fixture
  remains exactly 100 simple Channel URLs.
- Both production scripts now have zero host `python3` dependency. Smoke URL
  validation is conservative Bash, JSON/error/cursor work uses `jq`, and the
  campaign snapshot uses canonical `jq` plus `openssl sha256`. Seed dry-run
  validation uses `awk`, health uses `jq`, and live CSV/report Python remains
  solely inside the existing API container.
- Seed cleanup records failures, still attempts both exact file removals and
  the exact directory removal, emits one safe diagnostic, and converts an
  otherwise successful run to nonzero. Existing failure/signal statuses remain
  nonzero.
- Every curl call begins with `--disable`, explicitly selects GET and HTTPS,
  and disallows redirects. The fake installs a hostile `.curlrc` with a POST
  method and Authorization header and rejects calls lacking the first-argument
  disable; the public invalid-capability GET remains free of the private config
  and all POST behavior.

### Fix verification

Final focused suite, twice:

```text
$ bash ops/tests/test_operator_scripts.sh
PASS: exact 100-row synthetic Creator fixture
PASS: fake-backed smoke secrecy and resumable seed workflow
$ bash ops/tests/test_operator_scripts.sh
PASS: exact 100-row synthetic Creator fixture
PASS: fake-backed smoke secrecy and resumable seed workflow
```

The final seed dry-run passed without a report, Docker, or provider call.
Task 1–6 regression scripts and `integration/run.sh --contract` all passed.
Both new scripts, their focused test, and all existing ops/integration shell
files passed `bash -n`.

The original related backend selection was rerun unchanged against the
existing isolated backend test services:

```text
226 passed in 19.41s
```

Final checks passed for exact Task 7 scope, executable modes, fixture line
counts, `git diff --check`, zero host `python3` references in either production
script, unsafe source/eval, secret/private-key patterns, process arguments,
GET-only/public-no-auth curl calls, exact cleanup/no prune, external calls, and
generated artifacts. ShellCheck remains unavailable. No real API, provider,
production Docker, AWS, SMTP, SSH, public response action, or production file
was touched.

No binding concerns remain after fix round 1.
