# Email mechanics

## Fixed template rule

Personalization means filling declared variables only. For LIMINAL select
`liminal-outreach`, never silently replace it with `game-outreach`.
The five variables are creator_name, channel_name, reference_work,
specific_observation and game_download_url. Non-variable phrases (including
following/enjoying videos and demo availability), subject and signature are
fixed PR copy approved by the user. Do not independently rewrite, soften, add
disclaimers, or append Internal Test to the body. Check evidence for variable
values; do not turn missing evidence into permission to replace fixed copy.
Ask about missing variable information instead. Only an explicit user request
authorizes changing the template or fixed copy.

Enrichment needs `email:enrich`; previews and sends need `email:send`. Enrichment searches public business contacts only and may spend company Gemini/search quota.

```sh
fmg --run-id demo-1 email enrich --url https://example.com/creator --name Creator --idempotency-key demo-1-creator
fmg email job JOB_ID --wait --timeout 5m
fmg email retry JOB_ID
```

Reusing a submission key returns the original job; changed input conflicts. Polling does not repeat work. `--wait` emits NDJSON and stopping the CLI does not cancel server work. Retry explicitly resumes failed stages, reusing completed checkpoints and the original run attribution. A completed empty result is Not Found; timeout/rate-limit/failed is unresolved, not Not Found. Multiple emails include purpose/source/method/verification. None guarantee inbox delivery. Copy needed results before terminal enrichment jobs expire (default 30 days).

Inspect templates with `fmg email templates` and `fmg email template game-outreach`. Use exactly the returned version and variables. `message.json` is:

For `Liminal Outreach`, fetch `fmg email template liminal-outreach`. Its server-owned subject currently starts `Internal Test`; the CLI does not accept a custom subject override. Preserve all fixed template prose and substitute only declared variables. Never infer the version from an old example. A template/version change requires a fresh preview/task and review, not editing an old snapshot. If `smtp_recipient_not_allowed` is returned, ask the administrator to authorize the intended address; do not bypass the allowlist with another workflow.

```json
{"template_id":"game-outreach","template_version":"3","to":"creator@example.com","variables":{"creator_name":"Creator","game_name":"Selected Game","game_summary":"Factual game description","game_url":"https://store.steampowered.com/app/570/","personalization":"A specific statement supported by saved public evidence","sender_name":"Sender","company_name":"Company"}}
```

Use these commands for individual or special-purpose sending with the available template capabilities. For batches with tracking, use [Outreach tasks](outreach.md), not a loop of individual sends. `fmg email preview --input message.json` creates an immutable snapshot; `fmg email preview --id ID` rereads it. Inspect the actual rendered subject, plain text, recipient and sender; obtain user approval before sending:

For the browser copilot experience, render the returned preview into a read-only local page and proactively open it in Codex's built-in browser before requesting approval. Show the receipt/status in the same page during and after sending. Use returned data with safe text escaping; never embed the CLI credential, invent a public preview URL, or imply that individual Email sends support the Outreach Task dashboard . If browser access is unavailable, say so and present the full preview in the conversation instead; explicit approval is still required.

```sh
fmg --run-id demo-1 email send --preview-id PREVIEW_ID --confirm --idempotency-key demo-1-approved-recipient
fmg email receipt SEND_ID
```

Do not use `--confirm` merely because the user requested drafting. Each preview permits one SMTP attempt. Repeat the same key after an uncertain HTTP response; do not create a new preview/key to bypass unknown delivery. Exit 7/`unknown` requires investigation. Explicit failure requires a new approved preview before another attempt. `sent` is SMTP acceptance, not inbox/read/interest. Follow the server-rendered template. Generic emails are plain text; Liminal Outreach v4 has an approved minimal HTML alternative solely for its inline signature logo, with a plain-text fallback. Do not add custom HTML, Markdown formatting or Yes/No links. Do not append tracking links. For reply monitoring in the task dashboard, use Outreach tasks. One plain To address, no CC/BCC/attachments. Missing SMTP allows preview but blocks send; configuring/changing the sender requires a new preview. Previews older than 30 days cannot be sent.
