# Email mechanics

## Fixed template rule

Use the single `game-outreach` template for every game. Before drafting, read [full template and variable guidance](email-template.md), then fetch `fmg email template game-outreach`. Its version, schema and fixed copy are authoritative. Never submit a legacy Liminal template or infer a version from examples.

Enrichment needs `email:enrich`; previews and sends need `email:send`. Enrichment searches public business contacts only and may spend company Gemini/search quota.

```sh
fmg --run-id demo-1 email enrich --url https://example.com/creator --name Creator --idempotency-key demo-1-creator
fmg email job JOB_ID --wait --timeout 5m
fmg email retry JOB_ID
```

Reusing a submission key returns the original job; changed input conflicts. Polling does not repeat work. `--wait` emits NDJSON and stopping the CLI does not cancel server work. Retry explicitly resumes failed stages, reusing completed checkpoints and the original run attribution. A completed empty result is Not Found; timeout/rate-limit/failed is unresolved, not Not Found. Multiple emails include purpose/source/method/verification. None guarantee inbox delivery. Copy needed results before terminal enrichment jobs expire (default 30 days).

Inspect with `fmg email templates` and `fmg email template game-outreach`. `message.json` contains `template_id`, current `template_version`, `to`, and all declared `variables` from the [full template](email-template.md). The subject starts Internal Test and derives its game name/tagline from variables; no custom subject override. Changed templates/content require new preview and approval. If `smtp_recipient_not_allowed` is returned, ask the administrator; never bypass the allowlist.

Use these commands for individual or special-purpose sending with the available template capabilities. For batches with tracking, use [Outreach tasks](outreach.md), not a loop of individual sends. `fmg email preview --input message.json` creates an immutable snapshot; `fmg email preview --id ID` rereads it. Inspect the actual rendered subject, plain text, recipient and sender; obtain user approval before sending:

For the browser copilot experience, render the returned preview into a read-only local page and proactively open it in Codex's built-in browser before requesting approval. Show the receipt/status in the same page during and after sending. Use returned data with safe text escaping; never embed the CLI credential, invent a public preview URL, or imply that individual Email sends support the Outreach Task dashboard . If browser access is unavailable, say so and present the full preview in the conversation instead; explicit approval is still required.

```sh
fmg --run-id demo-1 email send --preview-id PREVIEW_ID --confirm --idempotency-key demo-1-approved-recipient
fmg email receipt SEND_ID
```

Do not use `--confirm` merely because the user requested drafting. Each preview permits one SMTP attempt. Repeat the same key after an uncertain HTTP response; do not create a new preview/key to bypass unknown delivery. Exit 7/`unknown` requires investigation. Explicit failure requires a new approved preview before another attempt. `sent` is SMTP acceptance, not inbox/read/interest. Follow the server-rendered template. The unified template has an approved minimal HTML alternative solely for its inline signature logo, with a plain-text fallback. Do not add custom HTML, Markdown formatting or Yes/No links. Do not append tracking links. For reply monitoring in the task dashboard, use Outreach tasks. One plain To address, no CC/BCC/attachments. Missing SMTP allows preview but blocks send; configuring/changing the sender requires a new preview. Previews older than 30 days cannot be sent.
