# Deployment, Integration, and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the completed system to the existing US AWS EC2 server, prove backup/restore and end-to-end behavior, and produce a signed, notarized macOS app that coworkers can install.

**Architecture:** One production Docker Compose project runs Caddy, FastAPI, one Celery worker, Celery Beat, PostgreSQL, and Redis on the existing EC2 host. Host-level scripts own bootstrap, deployment, daily PostgreSQL backup, restore rehearsal, and S3 lifecycle configuration; the EC2 Instance Role supplies S3 access. A separate release script stages the SwiftPM GUI bundle, signs with Developer ID and Hardened Runtime, submits to Apple Notary, staples the ticket, and emits a checksum-bearing ZIP.

**Tech Stack:** Docker Compose, Caddy, AWS EC2/EBS/S3/CLI, systemd, PostgreSQL tools, Bash, curl, codesign, notarytool, spctl, ditto.

**Spec:** `docs/superpowers/specs/2026-09-02-find-me-gamer-design.md`

## Global Constraints

- Runtime is the existing AWS EC2 server in the United States plus the existing S3 service.
- Production services are only Caddy, API, Worker, Beat, PostgreSQL, and Redis; do not add RDS, SQS, Lambda, ECS, ALB, Secrets Manager, CloudWatch, or SNS.
- Only Caddy publishes host ports; PostgreSQL and Redis stay on the internal Compose network.
- HTTPS is mandatory and HTTP redirects to HTTPS.
- The EC2 Instance Role, not embedded AWS keys, accesses only the required S3 prefixes.
- Because API/Worker containers obtain Instance Role credentials through Docker bridge networking, EC2 must require IMDSv2 with metadata response hop limit 2.
- The AES master key is a root-owned mode `0600` host file outside the repository; one recovery copy is kept in the company's password manager.
- Database backup runs outside Celery, daily, uploads encrypted to S3, retains 30 days, and is restore-tested before distribution.
- YouTube acquisition objects expire in no more than 30 days.
- Local debug launch does not require notarization; coworker distribution uses Developer ID, Hardened Runtime, Apple Notary, stapling, and Gatekeeper verification.
- Deployment may have a brief interruption; high availability and zero-downtime rollout are out of scope.
- Every task follows TDD or executable validation and ends with a focused commit.

## Operator-Provided Release Inputs

Implementation can proceed locally without these values, but production deployment and distribution cannot complete until the operator supplies them through host files or environment variables:

- EC2 SSH/SSM access and a company-controlled DNS name pointing to the instance.
- Existing S3 bucket name, AWS Region, `backups/` prefix, and `acquisition/` prefix.
- Workspace Access Key, Steam key if used, YouTube key, DeepSeek key, and NetEase enterprise SMTP credentials.
- Initial Creator CSV with 100 rows using `youtube_url`, optional `contact_email`, and optional `notes`.
- Apple Developer ID Application certificate and a configured `notarytool` Keychain profile.
- One controlled company recipient mailbox for SMTP and response smoke tests.
- At least one macOS 14 environment and one macOS 26+ environment for final visual/runtime checks.

## File Map

- `compose.yaml` — production topology, networks, volumes, health checks, restart and log policies.
- `Caddyfile` — company-domain TLS, API/public-response proxying, and safe defaults.
- `.env.example` — non-secret configuration names only.
- `ops/bootstrap_server.sh` — validates the host and creates protected configuration paths.
- `ops/deploy.sh` — one-command on-host backup, build, migrate, restart, and health verification.
- `ops/deploy_remote.sh` — one-command transfer/remote invocation wrapper.
- `ops/backup_postgres.sh` — daily custom-format dump to S3.
- `ops/restore_rehearsal.sh` — isolated restore validation without touching production DB.
- `ops/configure_s3_lifecycle.sh` — idempotent acquisition and backup retention rules.
- `ops/systemd/` — backup service/timer and application service units.
- `ops/iam/ec2-s3-prefix-policy.json` — least-privilege policy template for the existing Instance Role.
- `ops/smoke_test.sh` — API-level production smoke checks that never embeds credentials in arguments.
- `script/build_release.sh` — release bundle staging, signing, notarization, Gatekeeper validation, ZIP, and SHA-256.
- `docs/release-checklist.md` — human macOS 14/26, SMTP, response, and restore acceptance record.

---

### Task 1: Production Compose topology and Caddy HTTPS routing

**Files:**
- Create: `compose.yaml`
- Create: `Caddyfile`
- Create: `.env.example`
- Create: `ops/tests/test_compose_config.sh`

**Interfaces:**
- Produces: services `proxy`, `api`, `worker`, `beat`, `postgres`, and `redis`.
- Produces: public `https://${SERVICE_DOMAIN}/api/v1/*`, `/r/*`, `/health/live`, and `/health/ready`.

- [ ] **Step 1: Write the failing topology validation script**

```bash
#!/usr/bin/env bash
set -euo pipefail
rendered="$(docker compose --env-file .env.example config --format json)"
jq -e '.services | keys == ["api","beat","postgres","proxy","redis","worker"]' <<<"$rendered"
jq -e '.services.postgres.ports == null and .services.redis.ports == null' <<<"$rendered"
jq -e '.services.worker.command | tostring | contains("--concurrency=5")' <<<"$rendered"
```

- [ ] **Step 2: Run validation and verify production Compose is absent**

Run: `bash ops/tests/test_compose_config.sh`

Expected: FAIL because `compose.yaml` does not exist.

- [ ] **Step 3: Implement the minimal six-service topology**

Build API/Worker/Beat from `backend/Dockerfile`; use PostgreSQL and Redis pinned major image tags; mount an EBS-backed named database volume; mount `/etc/find-me-gamer/master.key` read-only into API/Worker; use internal `backend` network; expose only Caddy 80/443. Add health checks and `restart: unless-stopped`. Use Docker `json-file` logging with `max-size: 10m` and `max-file: 5`. The Worker command sets concurrency 5. Caddy redirects HTTP automatically, proxies `/api/*`, `/r/*`, and health paths, and adds conservative response headers without caching API data.

- [ ] **Step 4: Render and inspect Compose/Caddy configuration**

Run: `bash ops/tests/test_compose_config.sh && docker compose --env-file .env.example config --quiet && docker run --rm -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile`

Expected: all validation commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add compose.yaml Caddyfile .env.example ops/tests/test_compose_config.sh
git commit -m "ops: define production compose stack"
```

---

### Task 2: Safe host bootstrap and protected runtime configuration

**Files:**
- Create: `ops/bootstrap_server.sh`
- Create: `ops/tests/test_bootstrap_server.sh`
- Create: `ops/iam/ec2-s3-prefix-policy.json`
- Create: `ops/README.md`

**Interfaces:**
- Produces: `/etc/find-me-gamer/app.env` mode `0600` and `/etc/find-me-gamer/master.key` mode `0600`.
- Produces: `/opt/find-me-gamer` deployment directory and validated prerequisites.

- [ ] **Step 1: Write a failing temp-root bootstrap test**

```bash
#!/usr/bin/env bash
set -euo pipefail
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
FMG_ETC_DIR="$test_root/etc" FMG_APP_DIR="$test_root/app" ops/bootstrap_server.sh --test-mode
test "$(stat -f '%Lp' "$test_root/etc/master.key")" = "600"
test "$(stat -f '%Lp' "$test_root/etc/app.env")" = "600"
test "$(wc -c < "$test_root/etc/master.key" | tr -d ' ')" -ge 44
```

- [ ] **Step 2: Run the test and verify bootstrap is missing**

Run: `bash ops/tests/test_bootstrap_server.sh`

Expected: FAIL because `bootstrap_server.sh` is absent.

- [ ] **Step 3: Implement idempotent bootstrap without printing secrets**

Require Docker Compose v2, curl, jq, openssl, AWS CLI v2, and systemd in production mode. Create exact directories, generate a base64-encoded 32-byte AES key only when absent, and install a non-secret app.env skeleton if absent. Prompt silently for a Workspace Access Key and write only its Argon2id hash by invoking the backend security function in a one-off container. Never place Steam/YouTube/DeepSeek/SMTP plaintext in shell arguments or repository files. Document that the Instance Role policy replaces the bucket/Region/prefix values before attachment and contains only `s3:GetObject`, `s3:PutObject`, `s3:ListBucket`, plus bucket-level `s3:GetLifecycleConfiguration` and `s3:PutLifecycleConfiguration` needed by the one-time retention setup. Document the existing Security Group check: public inbound 80/443 only, administration restricted to the company's selected SSH source or SSM path, and no PostgreSQL/Redis host ports.

- [ ] **Step 4: Run bootstrap test and shell validation**

Run: `bash -n ops/bootstrap_server.sh && bash ops/tests/test_bootstrap_server.sh && jq empty ops/iam/ec2-s3-prefix-policy.json`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ops/bootstrap_server.sh ops/tests/test_bootstrap_server.sh ops/iam ops/README.md
git commit -m "ops: bootstrap existing ec2 host"
```

---

### Task 3: Daily PostgreSQL backup and isolated restore rehearsal

**Files:**
- Create: `ops/backup_postgres.sh`
- Create: `ops/restore_rehearsal.sh`
- Create: `ops/tests/test_backup_scripts.sh`
- Create: `ops/systemd/find-me-gamer-backup.service`
- Create: `ops/systemd/find-me-gamer-backup.timer`

**Interfaces:**
- Produces: `ops/backup_postgres.sh [--pre-migration]` returning the S3 object URI.
- Produces: `ops/restore_rehearsal.sh s3://bucket/key` restoring only to `find_me_gamer_restore_test`.
- Produces: a daily systemd timer independent of Celery.

- [ ] **Step 1: Write failing dry-run tests**

```bash
#!/usr/bin/env bash
set -euo pipefail
backup="$(FMG_DRY_RUN=1 ops/backup_postgres.sh --pre-migration)"
grep -q 'pg_dump --format=custom' <<<"$backup"
grep -q 'aws s3 cp' <<<"$backup"
restore="$(FMG_DRY_RUN=1 ops/restore_rehearsal.sh s3://example/backups/test.dump)"
grep -q 'find_me_gamer_restore_test' <<<"$restore"
! grep -q 'DROP DATABASE find_me_gamer;' <<<"$restore"
```

- [ ] **Step 2: Run dry-run tests and verify scripts are absent**

Run: `bash ops/tests/test_backup_scripts.sh`

Expected: FAIL because backup scripts do not exist.

- [ ] **Step 3: Implement recoverable backup and exact-target restore**

Use `mktemp -d` and a trap. Run `pg_dump --format=custom --no-owner --no-acl` inside the PostgreSQL container, calculate SHA-256, and upload dump plus checksum with `aws s3 cp --sse AES256`. Use date/commit-based object names under the configured backup prefix. Restore rehearsal creates the exact isolated database, runs `pg_restore`, verifies Alembic version and required table counts, reports success, then drops only that exact test database. The systemd service runs the backup script; timer uses `OnCalendar=daily` and `Persistent=true`.

- [ ] **Step 4: Validate scripts and systemd units**

Run: `bash -n ops/backup_postgres.sh ops/restore_rehearsal.sh && bash ops/tests/test_backup_scripts.sh && grep -q '^OnCalendar=daily$' ops/systemd/find-me-gamer-backup.timer && grep -q '^Persistent=true$' ops/systemd/find-me-gamer-backup.timer`

Expected: all static/dry-run checks pass.

- [ ] **Step 5: Commit**

```bash
git add ops/backup_postgres.sh ops/restore_rehearsal.sh ops/tests/test_backup_scripts.sh ops/systemd
git commit -m "ops: back up and restore postgres"
```

---

### Task 4: S3 lifecycle and EC2 metadata/IAM validation

**Files:**
- Create: `ops/configure_s3_lifecycle.sh`
- Create: `ops/s3-lifecycle.json`
- Create: `ops/validate_instance_access.sh`
- Create: `ops/tests/test_s3_configuration.sh`

**Interfaces:**
- Produces: lifecycle rules `FindMeGamerAcquisition30Days` and `FindMeGamerBackups30Days`.
- Produces: read/write/delete-self probe within approved S3 prefixes.

- [ ] **Step 1: Write failing lifecycle-policy tests**

```bash
#!/usr/bin/env bash
set -euo pipefail
jq -e '.Rules[] | select(.ID == "FindMeGamerAcquisition30Days") | .Expiration.Days == 30' ops/s3-lifecycle.json
jq -e '.Rules[] | select(.ID == "FindMeGamerBackups30Days") | .Expiration.Days == 30' ops/s3-lifecycle.json
jq -e '[.Rules[].Filter.Prefix] | all(endswith("/"))' ops/s3-lifecycle.json
```

- [ ] **Step 2: Run the test and verify configuration is absent**

Run: `bash ops/tests/test_s3_configuration.sh`

Expected: FAIL because lifecycle JSON is missing.

- [ ] **Step 3: Implement idempotent lifecycle merge and access probe**

Generate lifecycle JSON from exact configured acquisition/backup prefixes, preserve unrelated existing bucket rules, and call `put-bucket-lifecycle-configuration`. The validation script confirms AWS CLI is using an Instance Role identity, refuses static `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` environment credentials, and checks the instance metadata options report `HttpTokens=required` with `HttpPutResponseHopLimit=2`. It then runs the S3 probe through a one-off API container so the same boto3 credential path used by production writes, reads, and deletes one random exact key under `acquisition/health/`. If the hop limit is not 2, stop and print `aws ec2 modify-instance-metadata-options --instance-id "$instance_id" --http-tokens required --http-put-response-hop-limit 2` using the instance ID already resolved by the script; do not silently mutate instance metadata.

- [ ] **Step 4: Validate JSON and dry-run commands**

Run: `bash ops/tests/test_s3_configuration.sh && FMG_DRY_RUN=1 bash ops/configure_s3_lifecycle.sh && FMG_DRY_RUN=1 bash ops/validate_instance_access.sh`

Expected: PASS and commands target only configured prefixes.

- [ ] **Step 5: Commit**

```bash
git add ops/configure_s3_lifecycle.sh ops/s3-lifecycle.json ops/validate_instance_access.sh ops/tests/test_s3_configuration.sh
git commit -m "ops: enforce s3 retention boundaries"
```

---

### Task 5: One-command deployment with pre-migration backup and health gate

**Files:**
- Create: `ops/deploy.sh`
- Create: `ops/deploy_remote.sh`
- Create: `ops/tests/test_deploy_script.sh`
- Create: `ops/systemd/find-me-gamer.service`

**Interfaces:**
- Produces: `ops/deploy.sh [git-ref]` on the server.
- Produces: `ops/deploy_remote.sh <host> [git-ref]` from a trusted workstation.

- [ ] **Step 1: Write a failing ordered-step dry-run test**

```bash
#!/usr/bin/env bash
set -euo pipefail
output="$(FMG_DRY_RUN=1 ops/deploy.sh main)"
backup_line="$(grep -n 'backup_postgres.sh --pre-migration' <<<"$output" | cut -d: -f1)"
migrate_line="$(grep -n 'alembic upgrade head' <<<"$output" | cut -d: -f1)"
up_line="$(grep -n 'docker compose up -d' <<<"$output" | cut -d: -f1)"
test "$backup_line" -lt "$migrate_line"
test "$migrate_line" -lt "$up_line"
grep -q '/health/ready' <<<"$output"
```

- [ ] **Step 2: Run dry-run test and verify deployment script is absent**

Run: `bash ops/tests/test_deploy_script.sh`

Expected: FAIL because `deploy.sh` is missing.

- [ ] **Step 3: Implement locked, ordered deployment**

Acquire `flock` on `/var/lock/find-me-gamer-deploy.lock`; fetch and checkout the requested existing ref; load `/etc/find-me-gamer/app.env`; build images; run pre-migration backup; run Alembic against the existing PostgreSQL service; start the six services; wait up to 120 seconds for `/health/ready`; print service status and the deployed commit. Stop immediately on backup or migration failure. Remote wrapper accepts an explicit host, validates the ref, and invokes one quoted SSH command; it does not embed secrets.

- [ ] **Step 4: Run deployment script tests and Compose dry run**

Run: `bash -n ops/deploy.sh ops/deploy_remote.sh && bash ops/tests/test_deploy_script.sh && docker compose --env-file .env.example config --quiet`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ops/deploy.sh ops/deploy_remote.sh ops/tests/test_deploy_script.sh ops/systemd/find-me-gamer.service
git commit -m "ops: deploy stack with one command"
```

---

### Task 6: Local production-shape integration and worker restart tests

**Files:**
- Create: `integration/compose.integration.yaml`
- Create: `integration/run.sh`
- Create: `integration/tests/test_worker_recovery.sh`
- Create: `integration/tests/test_service_health.sh`
- Create: `integration/README.md`

**Interfaces:**
- Produces: `integration/run.sh` that starts isolated production-shaped services with fake external gateways.
- Verifies: API/Worker/Beat/PostgreSQL/Redis health and durable Job recovery across worker restart.

- [ ] **Step 1: Write failing recovery checks**

```bash
#!/usr/bin/env bash
set -euo pipefail
job_id="$(integration/helpers/create_running_analysis_job.sh)"
docker compose -f integration/compose.integration.yaml restart worker
integration/helpers/wait_for_job.sh "$job_id" succeeded 90
test "$(integration/helpers/read_profile_count.sh creator)" -eq 1
```

- [ ] **Step 2: Run integration harness and verify it is absent**

Run: `bash integration/run.sh`

Expected: FAIL because integration Compose does not exist.

- [ ] **Step 3: Implement isolated fake-backed stack**

Extend production Compose without changing it: replace Steam/YouTube/DeepSeek/S3/SMTP gateways through test dependency configuration and use isolated volumes/project name. Run migrations, seed deterministic fixtures, interrupt the Worker during Analyze and Match, restart it, and verify PostgreSQL checkpoints drive completion. Assert Caddy/API health, Beat enqueues due work, Redis loss does not erase final business state, and no partial Match results appear.

- [ ] **Step 4: Run the complete integration harness**

Run: `bash integration/run.sh`

Expected: all integration shell checks and backend pytest integration tests pass; the harness tears down only its named project and volumes.

- [ ] **Step 5: Commit**

```bash
git add integration
git commit -m "test: verify production-shaped recovery"
```

---

### Task 7: Production API smoke script and initial Creator seed procedure

**Files:**
- Create: `ops/smoke_test.sh`
- Create: `ops/seed_initial_creators.sh`
- Create: `ops/tests/test_operator_scripts.sh`
- Create: `ops/tests/fixtures/creator-seed-100.csv`
- Create: `docs/creator-seed-format.csv`

**Interfaces:**
- Produces: `FMG_WORKSPACE_KEY_FILE=<path> ops/smoke_test.sh <base-url>`.
- Produces: `ops/seed_initial_creators.sh <creator-csv>` using the backend CLI.

- [ ] **Step 1: Write failing safe-argument tests**

```bash
#!/usr/bin/env bash
set -euo pipefail
bash -n ops/smoke_test.sh ops/seed_initial_creators.sh
! grep -Eq -- '--workspace-key|--youtube-key|--smtp-password' ops/smoke_test.sh ops/seed_initial_creators.sh
head -n 1 docs/creator-seed-format.csv | grep -qx 'youtube_url,contact_email,notes'
test "$(tail -n +2 ops/tests/fixtures/creator-seed-100.csv | wc -l | tr -d ' ')" -eq 100
```

- [ ] **Step 2: Run tests and verify scripts are missing**

Run: `bash ops/tests/test_operator_scripts.sh`

Expected: FAIL because operator scripts are absent.

- [ ] **Step 3: Implement secret-file smoke and resumable seed commands**

Read the Workspace Key from a mode-0600 file, never a process argument. Smoke validates Session, settings status, profile lists, changed-Job cursor, and public GET non-mutation. Seeding validates exactly the approved CSV header, requires 100 non-empty unique YouTube URLs for the release run, copies the file to a temporary path inside the API container, invokes `python -m app.cli.seed_creators`, retrieves the row report, and removes only the temporary container file. It can be rerun safely and retries failed/incomplete rows.

- [ ] **Step 4: Run operator script tests**

Run: `bash ops/tests/test_operator_scripts.sh && FMG_DRY_RUN=1 ops/seed_initial_creators.sh ops/tests/fixtures/creator-seed-100.csv`

Expected: static checks pass; dry run prints the exact safe command without changing data.

- [ ] **Step 5: Commit**

```bash
git add ops/smoke_test.sh ops/seed_initial_creators.sh ops/tests/test_operator_scripts.sh ops/tests/fixtures/creator-seed-100.csv docs/creator-seed-format.csv
git commit -m "ops: add smoke and creator seed workflow"
```

---

### Task 8: Signed and notarized coworker release artifact

**Files:**
- Create: `script/build_release.sh`
- Create: `script/verify_release.sh`
- Create: `script/tests/test_release_scripts.sh`
- Create: `macos/FindMeGamer.entitlements`

**Interfaces:**
- Produces: `DEVELOPER_ID_APPLICATION=<identity> NOTARY_PROFILE=<profile> SERVICE_BASE_URL=<https-url> ./script/build_release.sh`.
- Produces: `release/FindMeGamer-<version>.zip` and matching `.sha256`.

- [ ] **Step 1: Write failing release-script policy tests**

```bash
#!/usr/bin/env bash
set -euo pipefail
grep -q -- '--options runtime' script/build_release.sh
grep -q 'notarytool submit' script/build_release.sh
grep -q 'stapler staple' script/build_release.sh
grep -q 'spctl -a -vv' script/verify_release.sh
plutil -lint macos/FindMeGamer.entitlements
```

- [ ] **Step 2: Run policy tests and verify scripts are absent**

Run: `bash script/tests/test_release_scripts.sh`

Expected: FAIL because release scripts do not exist.

- [ ] **Step 3: Implement distribution-only packaging and trust checks**

Require an HTTPS `SERVICE_BASE_URL`, semantic `APP_VERSION`, Developer ID Application identity, and existing Notary Keychain profile. Build Swift in release mode, stage the same valid `.app` structure as the debug runner, set `CFBundleShortVersionString`/`CFBundleVersion`, and use an empty least-privilege entitlements dictionary because the non-sandboxed app needs no special entitlement for outbound network or Keychain access. Sign the deepest code first, then the bundle with timestamp and Hardened Runtime. ZIP with `ditto`, submit with `xcrun notarytool submit --wait`, staple, run `codesign --verify --deep --strict`, `spctl -a -vv`, and `xcrun stapler validate`, then create SHA-256. Do not describe notarization as required for the local debug runner.

- [ ] **Step 4: Run static checks and an ad hoc bundle validation**

Run: `bash script/tests/test_release_scripts.sh && ADHOC_RELEASE=1 SERVICE_BASE_URL=https://example.invalid APP_VERSION=0.1.0 ./script/build_release.sh && ./script/verify_release.sh release/FindMeGamer-0.1.0.zip --allow-adhoc`

Expected: bundle structure and ad hoc signature pass locally; the real release path remains gated on Developer ID/Notary credentials.

- [ ] **Step 5: Commit**

```bash
git add script/build_release.sh script/verify_release.sh script/tests/test_release_scripts.sh macos/FindMeGamer.entitlements
git commit -m "build: package notarized macos release"
```

---

### Task 9: Full real-service and macOS compatibility acceptance checklist

**Files:**
- Create: `docs/release-checklist.md`
- Create: `ops/record_release_evidence.sh`
- Create: `ops/tests/test_release_checklist.sh`

**Interfaces:**
- Produces: a per-release evidence directory `release/evidence/<version>/` containing sanitized command results and human check marks.
- Verifies: all fifteen real smoke scenarios from the specification.

- [ ] **Step 1: Write failing checklist-coverage test**

```bash
#!/usr/bin/env bash
set -euo pipefail
for item in \
  workspace-key steam-analyze youtube-analyze library reanalyze creator-seed \
  three-stage-match outreach accepted declined duplicate-send cloud-continuation \
  offline-reconnect macos-14 macos-26 backup-restore master-key-recovery; do
  grep -q "id: $item" docs/release-checklist.md
done
```

- [ ] **Step 2: Run checklist test and verify document is absent**

Run: `bash ops/tests/test_release_checklist.sh`

Expected: FAIL because release checklist does not exist.

- [ ] **Step 3: Implement exact acceptance record and evidence capture**

Give every scenario an ID, operator, timestamp, environment, expected outcome, actual outcome, and pass/fail box. Include real Steam/YouTube Analyze, 100-Creator seed, three-stage Match, hidden-score inspection, individual/batch NetEase send to controlled mailboxes, Accepted/Declined confirmation, duplicate prevention, app-close cloud continuation, offline recovery, macOS 14 standard fallback, macOS 26 official glass, isolated restore rehearsal, and confirmation that one AES master-key recovery copy is stored in the company password manager rather than S3. Evidence script records sanitized `docker compose ps`, health JSON, migration revision, deployed commit, release checksum, code-sign/notary output, and backup restore report; it never captures keys, tokens, credentials, or email bodies.

- [ ] **Step 4: Run checklist coverage and evidence dry run**

Run: `bash ops/tests/test_release_checklist.sh && FMG_DRY_RUN=1 ops/record_release_evidence.sh 0.1.0`

Expected: PASS and evidence paths remain within `release/evidence/0.1.0/`.

- [ ] **Step 5: Commit**

```bash
git add docs/release-checklist.md ops/record_release_evidence.sh ops/tests/test_release_checklist.sh
git commit -m "docs: add end to end release acceptance"
```

---

### Task 10: Execute production release gate

**Files:**
- Modify: `docs/release-checklist.md` with dated results only.
- Create: `release/evidence/<version>/` through the evidence script; keep secrets excluded.

**Interfaces:**
- Consumes: all operator-provided release inputs.
- Produces: deployed commit, proven restore, seeded Library, completed smoke evidence, and notarized coworker ZIP.

- [ ] **Step 1: Validate production prerequisites without mutation**

Run: `ssh "$FMG_EC2_HOST" 'cd /opt/find-me-gamer && set -a && . /etc/find-me-gamer/app.env && set +a && sudo --preserve-env=FMG_S3_BUCKET,FMG_AWS_REGION,FMG_ACQUISITION_PREFIX ops/validate_instance_access.sh' && security find-identity -p codesigning -v && xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null`

Expected: EC2 uses the expected Instance Role, S3 probe passes, Developer ID identity is visible, and Notary credentials work.

- [ ] **Step 2: Deploy and configure retention**

Run: `ops/deploy_remote.sh "$FMG_EC2_HOST" "$RELEASE_GIT_REF" && ssh "$FMG_EC2_HOST" 'cd /opt/find-me-gamer && set -a && . /etc/find-me-gamer/app.env && set +a && sudo --preserve-env=FMG_S3_BUCKET,FMG_AWS_REGION,FMG_ACQUISITION_PREFIX,FMG_BACKUP_PREFIX ops/configure_s3_lifecycle.sh && sudo systemctl enable --now find-me-gamer-backup.timer'`

Expected: deploy prints the requested commit, `/health/ready` succeeds, lifecycle contains both 30-day rules, and backup timer is active.

- [ ] **Step 3: Seed Creators and execute real smoke checks**

Run: `ssh "$FMG_EC2_HOST" 'cd /opt/find-me-gamer && set -a && . /etc/find-me-gamer/app.env && set +a && sudo ops/seed_initial_creators.sh /etc/find-me-gamer/creator-seed.csv && sudo --preserve-env=SERVICE_DOMAIN,FMG_WORKSPACE_KEY_FILE ops/smoke_test.sh "https://$SERVICE_DOMAIN"'`

Expected: 100 unique Creator rows are queued or already complete, no unresolved failed rows remain after retries, and API smoke passes.

- [ ] **Step 4: Prove restore, package the app, and complete human checks**

Run: `ssh "$FMG_EC2_HOST" 'cd /opt/find-me-gamer && set -a && . /etc/find-me-gamer/app.env && set +a && backup_uri="$(sudo --preserve-env=FMG_S3_BUCKET,FMG_AWS_REGION,FMG_BACKUP_PREFIX ops/backup_postgres.sh)" && sudo --preserve-env=FMG_S3_BUCKET,FMG_AWS_REGION ops/restore_rehearsal.sh "$backup_uri"' && SERVICE_BASE_URL="https://$SERVICE_DOMAIN" APP_VERSION="$APP_VERSION" DEVELOPER_ID_APPLICATION="$DEVELOPER_ID_APPLICATION" NOTARY_PROFILE="$NOTARY_PROFILE" ./script/build_release.sh && ./script/verify_release.sh "release/FindMeGamer-$APP_VERSION.zip"`

Expected: isolated restore succeeds; signature, Notary, staple, and Gatekeeper checks pass. Install and execute the remaining macOS 14, macOS 26, SMTP, response, and offline checks in `docs/release-checklist.md`, then run `ops/record_release_evidence.sh "$APP_VERSION"`.

- [ ] **Step 5: Commit only the sanitized release record**

```bash
git add docs/release-checklist.md
git commit -m "chore: record internal release acceptance"
```
