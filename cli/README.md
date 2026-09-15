# fmg CLI — development checkpoint

Calls the company gateway, not YouTube/X/Steam directly. Provider keys never belong in this client. CLI source is working locally; this checkpoint is not yet a public release. Email enrichment is available locally; sending is not implemented yet.

## Build and test

Go 1.27.1 was verified for local development. Run inside `cli`:

```sh
go test ./...
go vet ./...
go build -o fmg ./cmd/fmg
./fmg --help
./fmg version
```

From the repository root, after installing `agent-service` dependencies:

```sh
agent-service/.venv/bin/python cli/tests/gateway_smoke.py --binary cli/fmg
```

This exercises the compiled binary against a real loopback FastAPI server and local database, with simulated upstream platform responses. It does not call any paid API.

## Authenticate

An administrator provides a company gateway HTTPS URL and a revocable access token. Supply the token through stdin, not a command argument or pasted shell history. For example, a secure credential tool can pipe its output to:

```sh
fmg auth login --server https://YOUR-COMPANY-GATEWAY --token-stdin
```

That example URL is illustrative, not a deployed address. Login verifies the token before replacing existing configuration. Configuration is private (0600) in the OS user config directory under `fmg/config.json`; `FMG_CONFIG` chooses an explicit file for isolated environments. Remote HTTP is rejected; loopback HTTP is allowed for local development. The HTTP client honors the normal system process proxy environment and does not follow redirects.

`fmg auth check` reads current token identity/scopes. `fmg auth logout` removes local credentials only; it does not revoke the server token. An administrator revokes it server-side.

## Read official API operations

```sh
fmg youtube operations
fmg youtube describe search.list
fmg youtube call search.list --params '{"part":"snippet","q":"indie games","maxResults":5}'
fmg x describe getUsersByUsername
fmg x call getUsersByUsername --params '{"username":"YouTube","user.fields":["description","public_metrics"]}'
fmg steam call store.appdetails --params '{"appids":"570","l":"english","cc":"US"}'
```

These commands can consume company quota; they are examples, not a prescribed Agent workflow. Inspect the operation's authorization/availability before calling. `data` retains the original upstream JSON, including future fields. `meta` contains server metadata. Unknown quota values are null, not unlimited.

Default is exactly one upstream page. For deliberate pagination:

```sh
fmg youtube call search.list --params '{"part":"snippet","q":"indie games","maxResults":5}' --max-pages 2
```

Multiple pages are NDJSON: one complete response envelope per output line. `--max-items N` stops after a completed page reaches N; **the final full page can exceed N**. It does not truncate upstream data or guarantee a precise billable-item ceiling. Pair it with a small provider page size and `--max-pages` for predictable limits. Default `--max-pages 1` still applies if only max-items is supplied. Repeated cursors stop further requests. Ctrl-C retains already emitted pages; rerun only deliberately using a saved cursor when appropriate.

No automatic retries are performed. For a quota/429 failure inspect the structured stderr error and any retry delay; do not interpret retryable as authorization to loop indefinitely.

## Public business email enrichment

To inspect server-owned templates (read-only; does not send or consume model quota):

```sh
fmg email templates
fmg email template game-outreach
```

Template descriptions include a version, required variables, and text/HTML/subject bodies. The game is supplied through variables, not hard-coded. Template preview and confirmed sending commands are still being implemented; do not invent them from this checkpoint.

Requires an `email:enrich` token scope. These commands can consume company model/search quota:

```sh
fmg email enrich --url https://example.com/creator --name 'Creator' --idempotency-key unique-logical-request
fmg email job JOB_ID
fmg email job JOB_ID --wait --timeout 5m
fmg email retry JOB_ID
```

Reuse the same idempotency key after an uncertain submission; do not create a new key merely because the HTTP response was lost. Keys are scoped to your token. Completed/failed records expire after the server retention window (default 30 days); keys are not permanent reservations.

`--wait` emits NDJSON snapshots every two seconds and does not repeat enrichment. Ctrl-C or timeout stops waiting, not the server task. Query the same job ID later. `retry` explicitly requeues a failed job while preserving successful checkpoints. A process lost mid-execution becomes failed after its lease expires; it is not automatically replayed at additional model cost.

Results include multiple `emails` with purpose, public source URL, discovery method and verification status. `model_reported_unverified` is not independently verified, and no result guarantees delivery. Only a completed job with an empty array means no contact was found. Failures, missing configuration and incomplete public-page work are not Not Found. No emails are sent by enrichment.

## Output and exit status

Command results: JSON stdout (NDJSON for pages or job polling). Help is human-readable text. Errors: structured JSON stderr. Exit 0 success, 2 parameters, 3 authentication/permission, 4 quota/rate limit, 5 network/upstream/output/wait timeout, 6 failed email job, 130 user cancellation. Exit 7 is reserved for unknown send outcomes. The actual error code distinguishes company configuration, provider permission and quota failures.
