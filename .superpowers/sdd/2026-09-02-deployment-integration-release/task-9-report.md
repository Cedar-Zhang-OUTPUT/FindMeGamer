# Deployment Task 9 report

## Immutable base and scope

- Base: `873de990d22d3d27e125c99396595965cd3e4220`
- Scope: an unchecked 17-scenario human release checklist and a sanitized,
  read-only evidence recorder for the later Task 10 production gate.

## TDD RED

The complete focused contract was written and made executable before the
checklist or recorder existed. It failed for the missing production document:

```text
$ bash ops/tests/test_release_checklist.sh
missing docs/release-checklist.md
task9_RED_exit=1
```

No network, Docker, application, AWS, Keychain, provider, SMTP, password
manager, or production acceptance action was performed.

## GREEN implementation

- `docs/release-checklist.md` contains the 17 exact scenario IDs in binding
  order. Every scenario has the required operator/time/environment/data/steps/
  expected/actual/evidence fields and mutually exclusive unchecked PASS/FAIL
  boxes. The release header and two-person sign-off are also blank and
  unchecked for Task 10.
- The checklist covers real Steam/YouTube cloud Analyze, shared Library and
  failed re-analysis preservation, exact 100-Creator resumable seed completion,
  all three Match stages with hidden numeric ranking, cloud continuation,
  controlled NetEase individual/batch delivery and response outcomes,
  duplicate prevention, offline recovery, macOS 14/26 paths, isolated restore,
  and external master-key recovery custody. Safe data and stop/rollback
  boundaries are explicit.
- `ops/record_release_evidence.sh` accepts only a semantic version plus the
  documented non-secret routing environment. It validates the exact local
  archive/checksum/checklist/restore inputs before capture, rejects sensitive
  environment inputs, and invokes only bounded read-only SSH, public GET, and
  local release-verification commands.
- Remote Compose commands use `/etc/find-me-gamer/app.env` only as the exact
  `--env-file`; nothing sources or evaluates it. Captured commit, service
  status/health, Alembic revision, health JSON, trust checks, archive digest,
  restore summary, and checklist snapshot are converted through exact schemas
  into nine sanitized files.
- Live evidence is built under a private temporary directory beneath
  `release/evidence/`, cleaned on every failure, and atomically renamed only
  after all validation. Existing destinations are refused. Dry-run creates no
  directories and prints only the nine confined planned paths, a safe purpose,
  and PASS.

## Focused and failure evidence

The final focused suite passed twice:

```text
$ /bin/bash ops/tests/test_release_checklist.sh
PASS: exact unchecked 17-scenario checklist contract
PASS: fake-backed sanitized atomic evidence recorder contracts
PASS: release checklist and evidence recorder
$ /bin/bash ops/tests/test_release_checklist.sh
PASS: exact unchecked 17-scenario checklist contract
PASS: fake-backed sanitized atomic evidence recorder contracts
PASS: release checklist and evidence recorder
```

The fake live path uses argv-recording curl, SSH, remote Docker, and release
verification commands. Production code—not a fake—validates and publishes the
evidence. Covered failures include unsafe version/origin/SSH/credential input,
missing or mismatched release input, incomplete checklist, restore path escape
and symlink, malformed/secret-bearing/unhealthy command output, command
failure/timeout, existing destination preservation, and exact temporary cleanup.
No arbitrary captured output appears in an error.

Explicit dry-run evidence:

```text
$ FMG_DRY_RUN=1 ops/record_release_evidence.sh 0.1.0
release/evidence/0.1.0/deployed-commit.txt
release/evidence/0.1.0/compose-services.json
release/evidence/0.1.0/alembic-revision.txt
release/evidence/0.1.0/health-live.json
release/evidence/0.1.0/health-ready.json
release/evidence/0.1.0/release-artifact.txt
release/evidence/0.1.0/release-verification.json
release/evidence/0.1.0/restore-summary.json
release/evidence/0.1.0/release-checklist.md
PLAN: read-only deployed commit, Compose status, migration revision, public health, release trust, restore summary, and checklist snapshot
PASS
```

The command left no `release/evidence/` directory and did not change the
workspace.

## Regression and static gates

- Task 1–8 Compose, bootstrap, backup, S3, deploy, smoke/seed, integration
  contract, and release-script fake-backed tests all passed.
- Both new scripts pass `bash -n` under macOS `/bin/bash` 3.2.57 and have mode
  0755. ShellCheck and shfmt are not installed.
- Exact scope, 17-ID/result structure, path confinement, non-mutating command,
  secret/private-key, email, response-token, destructive-target, generated
  artifact, and `git diff --check` gates passed.
- No real checklist scenario was run or marked, and no real SSH, curl, Docker,
  app, AWS, Keychain, provider, SMTP, notarization, password-manager, or network
  action was performed.

No binding concerns remain.
