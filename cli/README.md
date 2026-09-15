# fmg CLI — development checkpoint

Calls the company gateway, not YouTube/X/Steam directly. Provider keys never belong in this client. Platform reads, email enrichment and confirmed template sending are implemented locally; this checkpoint is not yet a public release.

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

### Find a Steam game and its similar products

```sh
fmg steam describe store.search
fmg steam call store.search --params '{"term":"LIMINAL: Within"}'
fmg steam call store.recommendations --params '{"appid":"570"}'
fmg steam call store.recommendations --params '{"appid":"https://store.steampowered.com/app/570/"}'
```

These are labelled Store convenience helpers, not guaranteed official Web API methods. Each makes one bounded request; no automatic detail lookups or exhaustive paging. Locale defaults to `l=english,cc=US`, with explicit overrides available. Search returns `data.candidates` (App ID/name/canonical URL) and preserves the raw search JSON in `data.upstream`. Multiple name matches remain multiple candidates: the Agent must resolve ambiguity rather than silently selecting the first.

Recommendations return `data.items`, excluding the selected game and duplicate App IDs. Steam's current recommendation cards do not contain verified titles, so `name` is null and `name_hint` is only a readable URL slug. Resolve actual titles/details with `store.appdetails` for the relevant IDs before treating them as game facts. Both helpers return `meta.source_url` and `meta.retrieved_at` for evidence. Recommendations can vary by locale and time and need not match a signed-in user's ordering. An unrecognized or inaccessible page is an error, not a successful empty list.

## Public business email enrichment

To inspect server-owned templates (read-only; does not send or consume model quota):

```sh
fmg email templates
fmg email template game-outreach
```

Template descriptions include a version, required variables, and text/HTML/subject bodies. The game is supplied through variables, not hard-coded. See confirmed sending below for immutable previews.

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

## Preview and confirmed sending

Requires `email:send`. Company SMTP credentials stay on the server. Create a local `message.json` containing:

```json
{
  "template_id": "game-outreach",
  "template_version": 1,
  "to": "creator@example.com",
  "variables": {
    "creator_name": "Creator",
    "game_name": "Your Game",
    "game_summary": "An accurate description of the selected game.",
    "game_url": "https://store.steampowered.com/app/570/",
    "personalization": "A statement supported by saved public evidence.",
    "sender_name": "Your Name",
    "company_name": "Your Company"
  }
}
```

Inspect the current template first; this example is not approved outreach content. Previewing creates a fixed snapshot and does not send:

```sh
fmg email preview --input message.json
fmg email preview --id PREVIEW_ID
```

After the user approves the exact recipients and rendered messages, send each approved preview:

```sh
fmg email send --preview-id PREVIEW_ID --confirm --idempotency-key unique-approved-message
fmg email receipt SEND_ID
```

`--confirm` is mandatory, but an Agent must obtain the user's approval before using it. For a batch, approve the full batch and keep one preview/key/receipt per recipient. This version accepts one plain email address per preview; CC, BCC, attachments and arbitrary message-body fields are not supported.

One preview permits at most one SMTP attempt. Repeating the same key returns its receipt; a different key for the same preview is rejected. If the HTTP response is lost, query the receipt or repeat the **same** preview/key; never invent a new key or preview to automatically retry. `unknown` means delivery may have happened and requires investigation, not resending. An interrupted `sending` record older than five minutes becomes `unknown` when queried. An explicitly failed delivery also requires a new preview and renewed approval for another attempt.

`sent` means the SMTP server accepted the message, not that it reached the inbox or was read. Missing SMTP configuration permits previews but blocks sending. Previews expire for sending after 30 days; changing the configured sender requires a new preview. Send receipts are not removed by enrichment-job cleanup.

Compiled-CLI/HTTP/database tests and a local SMTP capture server cover accepted, refused and unknown outcomes. Company SMTP and external delivery have **not** been verified yet.

## Output and exit status

Command results: JSON stdout (NDJSON for pages or job polling). Help is human-readable text. Errors: structured JSON stderr. Exit 0 successful request (inspect receipt state), 2 parameters, 3 authentication/permission, 4 quota/rate limit, 5 network/upstream/output/wait timeout, 6 failed email job or delivery, 7 unknown send outcome, 130 user cancellation. The actual error code distinguishes company configuration, provider permission and quota failures.
