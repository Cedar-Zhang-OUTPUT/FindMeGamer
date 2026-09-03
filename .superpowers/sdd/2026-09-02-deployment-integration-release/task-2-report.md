# Deployment Task 2 Implementer Report

## Baseline and scope

- Immutable base: `39f8281471a1698846ab9a284639d11f761edfe2`.
- HEAD matched the base and the worktree was clean before the first edit.
- Created only `ops/bootstrap_server.sh`,
  `ops/tests/test_bootstrap_server.sh`,
  `ops/iam/ec2-s3-prefix-policy.json`, `ops/README.md`, and this required
  report.
- No AWS, EC2, IAM, Security Group, Docker production stack, Keychain, `/etc`,
  or `/opt` mutation was performed.

## Strict TDD evidence

The temp-root test was the only file created before production implementation.
It named the missing executable as the intended failure and exercised the real
script rather than inspecting source text.

```text
$ bash ops/tests/test_bootstrap_server.sh
ops/bootstrap_server.sh is required and must be executable
$ echo $?
1
```

After the minimal implementation, the focused script passed. The final focused
gate ran twice consecutively with the same result:

```text
$ bash ops/tests/test_bootstrap_server.sh
bootstrap server test: PASS
$ bash ops/tests/test_bootstrap_server.sh
bootstrap server test: PASS
```

The scenario contains 12 behavioral assertions. It creates only explicit
temporary directories, checks both protected modes, decodes the generated key
to exactly 32 bytes, checks that the generated value is absent from output,
adds an operator marker to `app.env`, deliberately loosens both file modes,
reruns bootstrap, and proves both files remain byte-for-byte identical while
their modes return to `0600`.

## Implementation

- Production mode requires root, Docker Compose v2, `curl`, `jq`, `openssl`,
  AWS CLI v2, and systemd. Directory overrides and prerequisite/input bypasses
  are limited to explicit `--test-mode`.
- The script creates `/etc/find-me-gamer` and `/opt/find-me-gamer`, rejects
  symlink/non-regular protected targets, and installs files atomically with a
  restrictive umask. Production also enforces root ownership on both protected
  files, including safe reruns over existing regular files.
- `master.key` is generated only when absent with 32 cryptographically random
  bytes encoded as base64. Its contents are never printed, and reruns only
  restore mode `0600`.
- `app.env` starts from the repository's inert `.env.example` skeleton and is
  installed only when absent. Production builds the API image before reading
  input, reads a non-empty Workspace Access Key silently, sends plaintext only
  over standard input to the one-off backend hasher, verifies Argon2id-shaped
  output, and writes only the hash. Inherited shell tracing is disabled before
  secret handling. No provider or SMTP secret handling was added.
- The IAM template contains exactly the required S3 read, write, list, and
  lifecycle actions. Its only delete grant is
  `REPLACE_WITH_ACQUISITION_PREFIX/health/*`; backup and general acquisition
  deletion are not granted.
- The operator runbook covers the inert domain and remaining placeholder
  replacement, subnet/Region confirmation, Instance Role identity, EBS-backed
  Docker data, IMDSv2 `HttpTokens=required` and bridged-container hop limit 2,
  Security Group/public-port checks, protected-file recovery, and the exact IAM
  replacement boundary.

## Verification

- `bash -n ops/bootstrap_server.sh` and
  `bash -n ops/tests/test_bootstrap_server.sh`: exit 0.
- Focused bootstrap test: PASS twice consecutively.
- `jq empty ops/iam/ec2-s3-prefix-policy.json`: exit 0.
- Precise IAM assertion: exact six approved actions, exact bucket/prefix
  resources and list conditions, and health-probe-only delete resource: `true`.
- `git diff --check`, exact scope, executable-mode, secret/certificate pattern,
  tracked-artifact, and idempotency checks passed.
- No live credential, private key, generated master-key value, or plaintext
  provider/SMTP secret appears in tracked files or command output.

## Self-review

- Production default paths are exact and cannot be redirected through
  environment overrides; tests use only their disposable root.
- Image preparation completes before secret input. The plaintext is never an
  external-process argument, and only the hasher's stdout is eligible for the
  protected environment file.
- Existing protected contents are never regenerated or replaced. Mode repair
  does not alter bytes.
- The policy has no wildcard action, whole-bucket object resource, backup
  delete, static AWS credential, or IAM attachment operation.
- The script does not start production services or mutate AWS/EC2 state.

## Commit handoff

The commit subject is exactly `ops: bootstrap existing ec2 host`. The immutable
hash is supplied after commit because including a commit's own hash in its
contents would change that hash.

## Concerns

ShellCheck is not installed on this host, so its conditional gate could not
run. Both shell files pass Bash syntax validation and the focused behavioral
test; no other concerns remain within Task 2 scope.
