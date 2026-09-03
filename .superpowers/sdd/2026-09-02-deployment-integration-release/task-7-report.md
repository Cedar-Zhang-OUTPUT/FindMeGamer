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
