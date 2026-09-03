# Deployment Task 3 Implementer Report

## Baseline and scope

- Immutable base: `35999a7dfa8db4190f87b86190c513513183f0fd`.
- HEAD matched the base and the worktree was clean before the first edit.
- Created only `ops/backup_postgres.sh`, `ops/restore_rehearsal.sh`,
  `ops/tests/test_backup_scripts.sh`, the two specified systemd units, and this
  required report.
- No Compose service was started. No PostgreSQL, S3, AWS, EC2, IAM, systemd,
  `/etc`, or `/opt` state was read or mutated. Live-path coverage used local
  command fakes and disposable temporary directories only.

## Strict TDD evidence

The complete behavioral test was the only repository file created before the
production scripts. Its first run discovered the test and failed specifically
because the requested executable did not exist:

```text
$ bash -n ops/tests/test_backup_scripts.sh && bash ops/tests/test_backup_scripts.sh
env: .../ops/backup_postgres.sh: No such file or directory
$ echo $?
127
```

After the first minimal implementation, the focused test passed. Inspection of
the Task 10 release command then exposed a real cross-task contract: sudo
preserves the S3 settings but not host-side PostgreSQL variables because the
database identity belongs to the `postgres` container. Removing those host
variables from the test produced a second deterministic RED before that
production behavior changed:

```text
$ bash ops/tests/test_backup_scripts.sh
backup: POSTGRES_DB is required
$ echo $?
1
```

The scripts were then changed to expand `POSTGRES_USER`, `POSTGRES_DB`, and the
restore connection inside the container. Focused GREEN passed after the change
and again during the final regression gate:

```text
$ bash ops/tests/test_backup_scripts.sh
backup scripts test: PASS
```

The test executes dry-run plans and live control flow against strict local
Docker/AWS/date/Git/SHA fakes. It covers argument/config rejection, deterministic
regular/pre-migration object construction, command ordering, both encrypted
Region-scoped uploads, exact one-URI live stdout, no URI after upload failure,
temporary artifact cleanup, matching checksum download and verification before
database creation, repository/restored Alembic comparison, all six required
table queries, and isolated database cleanup after success and simulated
`pg_restore` failure. The fakes never contact an external service.

## Implementation

### Backup

- Requires and validates the configured S3 bucket, Region, normalized
  slash-terminated backup prefix, and the sole optional `--pre-migration`
  argument before constructing commands.
- Uses a UTC timestamp, current 12-character Git commit identity, and explicit
  regular/pre-migration marker for each object name.
- Creates a private validated `mktemp -d`, streams
  `pg_dump --format=custom --no-owner --no-acl` from the exact Compose
  `postgres` service, and removes local artifacts through an EXIT trap.
- Uses `sha256sum` with a portable `shasum -a 256` fallback. It uploads the dump
  and matching `.sha256` object with `--sse AES256`, an explicit Region, and the
  EC2 role credential path; no static AWS credential is accepted or added.
- Routes progress and external command output to stderr. Only after the dump,
  hash, and both uploads succeed does live stdout receive exactly one final S3
  dump URI, preserving Task 10 command substitution.

### Restore rehearsal

- Accepts exactly one `.dump` URI in the configured bucket, derives only its
  matching `.sha256` URI, downloads both into a private temporary directory,
  and compares a validated stored digest with a locally calculated SHA-256
  before any database command.
- Uses maintenance database `postgres` only to create and drop the literal
  isolated database `find_me_gamer_restore_test`. It additionally refuses a
  container configuration that names that isolated database as production.
- Sends the dump only to `pg_restore --dbname find_me_gamer_restore_test` with
  `--exit-on-error --no-owner --no-acl`. No restore, rename, overwrite, connect,
  or DROP operation targets `find_me_gamer` or an operator-provided database.
- Compares restored `alembic_version` with the single repository Alembic head,
  then queries numeric counts from `game_profiles`, `creator_profiles`,
  `analysis_jobs`, `match_tasks`, `outreach_campaigns`, and `deliveries`.
- The database-created fence and EXIT trap drop only the exact rehearsal
  database after both success and post-create failure. Success is reported only
  after restore, schema/table verification, and cleanup all succeed.

### Scheduling and dry-run

- The root oneshot service uses `/opt/find-me-gamer`, the protected
  `/etc/find-me-gamer/app.env`, and the exact installed backup script.
- Its independent timer has exact `OnCalendar=daily` and `Persistent=true`; no
  unit was installed, enabled, or started in this task.
- Dry-run uses fixed inert timestamp/commit defaults (with test-only overrides)
  and deterministic shell-escaped planned commands. It performs no Docker,
  PostgreSQL, AWS, S3, Git, or systemd action.

## Verification

- `bash -n` for both production scripts and the focused test: exit 0.
- Focused backup/restore behavioral test: PASS twice after the final container
  environment correction.
- Existing Compose structure and Task 2 bootstrap regressions: PASS; Compose
  rendered assertions returned true and bootstrap reported PASS.
- Exact timer/service wiring assertions: PASS.
- Exact scope, executable modes, secret/static-credential scan, destructive
  target scan, generated dump/checksum artifact scan, and `git diff --check`:
  PASS.
- ShellCheck is not installed on this development host, so its conditional
  gate could not run.

## Security and destructive-target evidence

- No script logs an environment value, database password, AWS credential,
  object contents, or checksum payload. PostgreSQL credentials remain inside
  the Compose-managed container environment.
- Every operator/config value used by a command is validated and quoted. S3
  commands use argv boundaries rather than evaluated command strings.
- Production cleanup paths are generated by `mktemp`, checked against their
  exact `/tmp/find-me-gamer-{backup,restore}.*` namespace, and passed after
  `--` to removal.
- The only production `DROP DATABASE` text is
  `DROP DATABASE IF EXISTS "find_me_gamer_restore_test";`. The success and
  failure tests both observe exactly one such cleanup and explicitly reject a
  production-database DROP.
- A failed dump, hash, checksum comparison, upload, restore, migration check,
  table check, or cleanup exits nonzero and cannot print a success URI/message.

## Self-review

- Task 1 integration uses only Compose service `postgres`; Task 2 integration
  uses only the protected environment and EC2 role. The service is independent
  of Celery.
- Backup reads the production database name only inside the database container.
  Restore database arguments are constants, and the S3 object name cannot
  affect a local path or SQL target.
- Alembic verification derives the current repository head from the API image
  rather than freezing today's migration revision into operations code.
- Restore cleanup is armed only after CREATE succeeds, so a failed CREATE cannot
  destroy a pre-existing database owned by another rehearsal.
- The implementation stays within host script/unit scope and does not alter
  Compose, application code, migrations, IAM, or prior Task 1–2 files.

## Commit handoff

The commit subject is exactly `ops: back up and restore postgres`. The immutable
commit hash is supplied after commit because including a commit's own hash in
its contents would change that hash.

## Concerns

ShellCheck is unavailable on this host. Bash syntax, deterministic dry-run,
fake-backed live control flow, existing operations regressions, and static
safety gates all pass; no other scoped concern remains.
