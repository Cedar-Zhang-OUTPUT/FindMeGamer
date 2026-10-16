# Multi-mailbox release and safe cutover

Candidate: `fmg-v0.8.0`. This document is an operator runbook, not evidence that a
production command was executed. The current authorization covers local code,
tests and release artifacts only. Production deployment, proxy edits, gate
release, GitHub publication, actual email, paid lookup and second-mailbox
enrollment remain separate decisions. The prohibited container rehearsal is a
blocking release gate; native PostgreSQL/Redis results do not replace it.

## Review before a window

Read [native acceptance](multi-mailbox-acceptance-20261016.md) and the Task 8
report. Require the complete backend regression with real isolated PostgreSQL
and Redis, Go test/vet, executable Skill examples, browser acceptance, local
installer/upgrade/checksum checks, and container backup/restore acceptance.
Recheck the tag immediately before publication; an earlier empty `ls-remote`
result does not reserve it. Redis 8 native testing does not validate production
Redis 7. Publish CLI and both Skills from the same approved source revision.

On the server, inventory every producer/consumer (including old API embedded
threads, ad-hoc workers and alternate Compose projects), active work, uncertain
receipts, sender locks/leases, queue lengths, images/digests, disk/memory and DB
connections. Archive this evidence privately. Neither a zero queue length nor
an elapsed 620 seconds proves that a transport finished. Never clear a lease,
unknown receipt, approval revision or SenderSafety to make a preflight pass.

## Private configuration

Use the verified new image and a host virtualenv containing the same agent
package and dependencies. Set `FMG_AGENT_PYTHON` to that Python. Host tools need
Docker Compose access and private `FMG_AGENT_ADMIN_ENV_FILE` (mode 600): database
and broker URLs must reach the **same** service database/Redis DB from the host;
the mailbox registry path must be host-readable. No shell sourcing is used.
Avoid ambient `FMG_AGENT_DATABASE_URL`/broker/registry overrides: settings in the
process environment take precedence over the private admin file.

Set Compose's `FMG_AGENT_IMAGE`, `FMG_AGENT_ENV_FILE`, `FMG_AGENT_PG_ENV_FILE`,
`FMG_AGENT_NETWORK`, and `FMG_AGENT_MAILBOXES_HOST_FILE`. The registry is mounted
read-only at `/srv/mailboxes/mailboxes.json` in every agent role and migration
container. Its owner must permit image UID 10001 to read it while retaining mode
600; validate this on the actual host before a window. Keep protected OAuth
stores in their existing volume and explicitly map the correct unique paths.

Copy `deploy/agent-services/mailboxes.example.json` to private storage. Replace
the primary placeholder with the exact existing frozen sender, display name,
transport, credentials, monitor and OAuth settings. Registry fields do **not**
inherit legacy environment credentials. Keep `second` disabled with no sender,
credentials or token paths. Only the existing mailbox starts in this rollout.
Keep the interval at five seconds, enrichment at four prefork slots and each
mail consumer at two. Do not activate the `second-mailbox` Compose profile.

## Maintenance and warm drain

The old API has no persistent maintenance gates. Before invoking deployment,
install and verify a temporary proxy rule rejecting write methods for all
`/v1/*` routes, including send, preview, task creation/approval/resume and
enrichment. For Caddy, an operator-reviewed matcher can use `path /v1/*` and
`method POST PUT PATCH DELETE`, with `respond @fmg_maintenance 503` before the
normal `/v1` handler. Verify GET health and existing receipt/status reads remain
available. Inventory and close any direct routes bypassing the proxy. Preserve
the original proxy file. `--proxy-writes-blocked` is the operator's explicit
attestation; the script does not install or independently prove proxy policy.

Only in the separately approved window, with backup destination new and private:

```sh
sh deploy/agent-services/deploy.sh --apply --proxy-writes-blocked /var/backups/find-me-gamer-agent/REVIEWED-UNIQUE-WINDOW
```

`--first-install` is only for an independently verified empty dedicated database.
For an upgrade, never use it to bypass backup. The script saves private config
and container evidence, disables automatic restarts on current containers,
requests SIGTERM for every running role, then observes exit. On a 620-second
drain deadline it **aborts without SIGKILL**, leaves evidence and proxy hold,
and requires operator investigation. It does not restart the old worker.
Snapshot the queue only after all old processes and their embedded loops exit.
Any unacknowledged Redis entry blocks migration; do not delete it to continue.

After exit the script takes a PostgreSQL custom dump, applies additive schema
`0013_mail_runtime`, closes both gates, verifies in-flight work/leases/live
sender locks are absent, and applies identity backfill with table locks and a
before/after frozen-content digest. Backfill changes only mailbox associations.
An unresolved sending record or lease stops deployment for human reconciliation.

## Audited queue migration

Tools use the explicit host admin environment. Audit defaults to read-only;
providing `--manifest` creates a new private, fsynced snapshot without consuming:

```sh
"$FMG_AGENT_PYTHON" deploy/agent-services/mail_runtime.py status
"$FMG_AGENT_PYTHON" deploy/agent-services/queue_cutover.py audit --manifest /PRIVATE/queues.json
"$FMG_AGENT_PYTHON" deploy/agent-services/queue_cutover.py migrate --manifest /PRIVATE/queues.json --confirm
```

Audit reports enrichment, outreach-recipient and retry IDs, recognized/unknown
counts and DB-state aggregates. It snapshots exact broker bytes for the old
`fmg_agent` queue and its four standard Redis priority lists, plus unacked
hash/index evidence. It binds the snapshot to database/schema and broker endpoint.
Unknown envelopes/callbacks or unacked entries cause nonzero exit before any
publication. Do not hand-edit a manifest; take a new audit after reconciliation.

Migration verifies stopped Compose services, held runtime, no in-flight work and
the original manifest checksum. Current DB state determines routing: queued
enrichment, approved `sending` recipients with no attempt, and legal due retries.
Paused/blocked/draft tasks, disabled senders, sent/unknown/prior attempts, invalid
recipients, human replies and revoked authorization are not replayed. Their DB
records are retained. Every destination publication precedes removal of exactly
one matching old envelope. There is no purge/FLUSHALL or broad Redis deletion.

The private `.progress.jsonl` marks each operation `pending-reconciliation`
before publication and `acknowledged` only after exact removal. Redis publication
and old-list acknowledgement cannot be one cross-queue transaction. If the
connection breaks between them, the old envelope remains (or its acknowledgement
may already have succeeded); retain the journal, inspect both queues and DB, and
rerun the same manifest only while stopped/held. Duplicate delivery is protected
by the existing DB idempotency/reservations. Already-absent entries are reported,
not republished. Any new unexpected old envelope requires another audit.

Recoverability: the manifest stores each original envelope as base64 and its
original key/order; the database dump retains authoritative task state. Rehearse
restoration into an **isolated** broker/schema and compare bytes/digests/counts.
Never blindly restore an old live queue after migration: that would duplicate
delivery. Reconcile destination/journal/DB first. Keep the original snapshot and
the failed-attempt evidence; there is intentionally no automatic destructive
production restore command.

## Held startup, readiness and release

The script recreates API, enrichment, primary-mail, dispatcher and monitor roles
with gates closed. Queued mail and enrichment cannot contact providers while
held. A held monitor initializes its local DB/leadership loop without IMAP/OAuth
network calls. Global maintenance differs from SenderSafety: per-mailbox safety
pauses still allow monitoring when the global runtime is open.

`mail_runtime.py readiness` and `release` verify schema/backfill, drained send
state, the five-second interval, the exact running role set, API health and fresh
container-local evidence from each role. Worker evidence requires initialized
broker connection, the exact queue and 4/2 pool size. Dispatch evidence is emitted
after a successful iteration, monitor evidence after a held local check or
successful scan. Missing/stale/wrong-role/dead-PID evidence fails closed. Artifacts
bind role/mailbox/schema/database/queue/concurrency and PID start identity, and
are removed on clean shutdown/error. They prove **local readiness**, not remote
provider connectivity. Mail probes also verify local credential/token-store
configuration without calling the provider. The old queue and unacked ledger
must be empty before release.

```sh
"$FMG_AGENT_PYTHON" deploy/agent-services/mail_runtime.py readiness
sh deploy/agent-services/smoke.sh https://YOUR-VERIFIED-HOST
# Only after user review and explicit resume authorization:
"$FMG_AGENT_PYTHON" deploy/agent-services/mail_runtime.py release
```

Smoke requires `FMG_CONFIG` for that exact server and optionally `FMG_BIN`. It
reads health, auth, catalogs, templates and mailboxes only. It sends no mail and
makes no paid lookup. `release` changes only the two runtime flags; it does not
approve tasks, resume protected pauses, clear SenderSafety or rewrite unknown.
`hold` waits for live shared runtime locks to drain. Switching/removing the proxy
rule is an operator action in the approved window. Without resume authorization,
leave both gates held and report readiness only.

Compare before/after task-state and safety counts, unknown counts, approvals,
frozen digest, snapshot message counts, published/retained/already-absent counts,
and durable pending DB work. On discrepancy hold immediately and investigate.
Queue duplicates mean raw broker count alone is not a task conservation proof.

## Release artifacts and rollback

Build and install locally without publication:

```sh
sh cli/scripts/build-release.sh fmg-v0.8.0 .local/releases/fmg-v0.8.0
python3 .local/releases/fmg-v0.8.0/install.py --release-dir .local/releases/fmg-v0.8.0 --tag fmg-v0.8.0 --skills
fmg version
fmg update check
```

The bundle contains four platform binaries, both Skills, installer and SHA256SUMS.
Actual bundle tests verify checksums, version, both Skill stamps, and repeated
offline installation preserving authentication bytes/permissions. Publication
must use the reviewed same-source tag; no tag/push/draft release is performed by
the build command.

See [rollback boundary](../../deploy/agent-services/rollback.md). Before even
considering a legacy worker, run `mail_runtime.py check-legacy-rollback` under
hold. Any non-primary persisted identity or enabled second mailbox refuses it.
Passing this check is necessary, not authorization or proof an old image supports
the schema. Prefer a verified multi-mailbox-compatible image; do not guess a
single-mailbox fallback. Report separately: code/testing, CLI/Skill publication,
server deployment, and second-mailbox configuration/authorization.
