# Deployment Task 5 implementation report

## Scope and base

- Immutable base: `8becfa669cbdcd06b60b1b7739e8dd39bb59f777`
- Added `ops/deploy.sh`, `ops/deploy_remote.sh`,
  `ops/tests/test_deploy_script.sh`, and
  `ops/systemd/find-me-gamer.service`.
- Minimally extended `ops/backup_postgres.sh` and its existing focused test for
  the optional `FMG_COMPOSE_ENV_FILE` interface.
- No application, Compose topology, database, lifecycle, IAM, backend, client,
  or existing systemd backup behavior was changed.

All editing used `apply_patch`. No live Docker container, database, HTTP
endpoint, SSH host, AWS/IMDS/S3 service, systemd service, or production file was
accessed.

## TDD evidence

### Genuine RED 1: deployment entry point

The deploy test was written first to exercise the required dry-run, fake live
success/failure flows, remote wrapper, and systemd unit. Against the immutable
base it failed for the intended missing production entry point:

```text
$ bash ops/tests/test_deploy_script.sh
deploy script test: ops/deploy.sh is required and must be executable
$ echo $?
1
```

### Genuine RED 2: nested backup Compose environment

The existing Task 3 focused test was extended before the backup implementation
to require both dry-run and live Compose calls to use one supplied absolute
environment file. Against the immutable base:

```text
$ bash ops/tests/test_backup_scripts.sh
backup scripts test: missing expected text: --env-file <disposable-mode-0600-path>/compose.env
$ echo $?
1
```

### Small RED: explicit detached checkout plan

After the first GREEN, a dry-run behavior assertion required an explicit
detached checkout command rather than prose. It failed for that exact omission:

```text
$ bash ops/tests/test_deploy_script.sh
deploy script test: missing expected text: git -C /opt/find-me-gamer checkout --detach <resolved-commit>
$ echo $?
1
```

The dry-run was then minimally changed to show that deterministic command.

### Small RED: Compose v2 probe uses the protected env-file

The all-Compose assertion was tightened to include the version probe. It
exposed that the probe alone did not yet use the shared global parameters:

```text
$ bash ops/tests/test_deploy_script.sh
deploy script test: Compose command omitted the protected env-file: docker compose version
$ echo $?
1
```

The probe now uses the same `--project-directory` and exact `--env-file` array
as build, stop, data start, migration, full-up, and status. Focused tests then
returned GREEN.

## Implementation

### Locked deployment and safe configuration

`ops/deploy.sh [git-ref]` validates the ref before invoking Git. Production
requires root, the exact `/opt/find-me-gamer` checkout, regular non-symlink
root-owned mode-0600 `/etc/find-me-gamer/app.env` and `master.key`, Git, Linux
`flock`, Docker Compose v2, curl, and date. It takes the nonblocking
`/var/lock/find-me-gamer-deploy.lock` lock before any Git fetch or deployment
mutation, so concurrent deploys fail explicitly and cannot interleave.

The protected dotenv is never sourced or evaluated. A literal line parser
recognizes only exact `SERVICE_DOMAIN`, `FMG_S3_BUCKET`, `FMG_AWS_REGION`, and
`FMG_BACKUP_PREFIX` keys, requires each once, validates their existing safe
shapes, and exports only those four non-secret values. File values replace
conflicting inherited values. Every project Compose command uses one array with
the exact global `--env-file` path; no secret is separately exported, logged,
or placed in argv.

The explicit test mode only permits disposable paths and the current file
owner. Production rejects all path overrides. The environment-free dry-run
always renders the exact production paths and performs no filesystem, lock,
Git, Docker, backup, HTTP, or service action.

### Git and maintenance ordering

The deploy refuses a dirty checkout, fetches/prunes `origin`, resolves an
existing remote ref or exact local commit, checks out the 40-hex commit
detached, and verifies `HEAD`. It never merges, rebases, reset-hards, deletes
local files, or removes volumes.

The runtime order is:

1. build images before maintenance;
2. stop only proxy, API, Worker, and Beat;
3. create/start and health-wait only PostgreSQL and Redis;
4. run the real pre-migration backup with the same protected env-file;
5. run `alembic upgrade head` in one no-dependencies API container;
6. run exactly one full `docker compose up -d`;
7. poll exact `https://${SERVICE_DOMAIN}/health/ready` for at most 120 seconds;
8. print safe Compose status and the exact resolved deployed commit.

A backup or migration failure exits before full-up, leaving application
services stopped while PostgreSQL and Redis remain available. The initial
data-service up uses declared health checks and retains named volumes. A
readiness timeout returns nonzero and prints only `docker compose ps`, never
application logs or protected configuration.

### Task 3 backup compatibility

`FMG_COMPOSE_ENV_FILE` is optional. When present, the backup script requires an
absolute regular non-symlink file and adds only
`--env-file "$FMG_COMPOSE_ENV_FILE"` to its existing Compose command. The
no-argument/`--pre-migration` CLI, S3 settings, custom dump, SHA-256, two
AES256 uploads, single dump-URI stdout, systemd use, dry-run, and temporary
cleanup contracts are unchanged. Existing calls without the variable retain
their prior argv.

### Remote and boot wrappers

`ops/deploy_remote.sh <host> [git-ref]` accepts a deliberately narrow explicit
hostname/user-host form and the same safe ref grammar. It rejects leading
options, whitespace, quotes, and metacharacters before SSH, then makes one SSH
invocation with one quoted remote command in `/opt/find-me-gamer`. It includes
no key, password, environment content, or credential.

The systemd unit uses exact working directory and `EnvironmentFile`, and its
start/stop commands both use the same explicit Compose env-file. It only brings
the existing stack up at boot and stops it at shutdown; it never fetches,
backs up, migrates, checks health, or invokes deploy automatically.

## Test coverage and GREEN

The deploy test invokes the real deployment and backup scripts while replacing
only external effects with strict local fakes. Its complete mode-0600 dotenv
contains literal dollar signs, spaces, and an unquoted command-substitution
canary. It proves:

- the canary is not executed and protected values are not printed;
- all four file values override conflicting inherited values;
- every project Compose call, including nested backup, has the exact same
  env-file path;
- build/stop/data health/backup/migration/full-up/readiness/status ordering;
- initial and existing data-service paths each do exactly one full-up;
- backup and migration failure do not full-up, and backup failure does not
  migrate;
- failed readiness is bounded by the production 120-second deadline, exits
  nonzero, and prints safe status;
- lock contention, dirty checkout, missing ref, and unsafe ref fail before a
  mutating Docker command;
- remote safe quoting and host/ref rejection;
- exact systemd start/stop wiring and absence of boot deployment behavior.

The Task 3 test proves the optional env-file in both dry and fake-live modes,
rejects relative paths and symlinks, and reruns every previous backup/restore,
checksum, encryption, URI, migration-head, required-table, cleanup, timer, and
failure assertion.

Focused GREEN:

```text
$ bash -n ops/deploy.sh ops/deploy_remote.sh ops/backup_postgres.sh \
    ops/tests/test_deploy_script.sh ops/tests/test_backup_scripts.sh
$ bash ops/tests/test_deploy_script.sh
deploy script test: PASS
$ bash ops/tests/test_backup_scripts.sh
backup scripts test: PASS
```

## Full verification

Focused deployment and backup tests passed twice. Task 1–4 regression tests and
the actual local Compose render also passed:

```text
$ bash -n ops/*.sh ops/tests/*.sh
$ for pass in 1 2; do
    bash ops/tests/test_deploy_script.sh
    bash ops/tests/test_backup_scripts.sh
  done
deploy script test: PASS
backup scripts test: PASS
deploy script test: PASS
backup scripts test: PASS
$ bash ops/tests/test_compose_config.sh
true  # repeated for all 16 assertions
$ bash ops/tests/test_bootstrap_server.sh
bootstrap server test: PASS
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: PASS
$ docker compose --env-file .env.example config --quiet
$ FMG_DRY_RUN=1 ops/deploy.sh main
deterministic lock/fetch/checkout/build/stop/data/backup/migrate/up/health/status plan; exit 0
$ <Bash syntax, diff, exact scope/mode, secret/output, no-source/eval,
   destructive/AWS mutation, and generated-artifact gates>
task5 final gate: PASS
```

The real Docker Compose commands above only rendered configuration. All
deployment, backup, health, remote, and systemd effects were dry-run or fake.
ShellCheck and shfmt are conditionally run only when installed.

## Self-review and concerns

- The backup and migration failure branches cannot reach the sole full-up.
- PostgreSQL and Redis are never stopped and no volume-removal command exists.
- The health deadline caps each curl attempt by remaining time and cannot sleep
  after the deadline.
- The exact resolved commit, not the caller's ref string, is printed.
- The dotenv parser ignores every secret key and command-looking line.
- The previous Task 4 StreamingBody Minor remains intentionally untouched.

No binding concern remains. The only tooling limitation is reported after the
final conditional ShellCheck/shfmt gate. The required commit subject is
`ops: deploy stack with one command`; its immutable hash is supplied after
commit.
