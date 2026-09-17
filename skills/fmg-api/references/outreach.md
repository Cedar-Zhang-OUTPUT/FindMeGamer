# Batch outreach

Requires `email:send`. `fmg email` remains available for individual/special sending; use tasks when a batch needs server execution and Yes/No tracking. Never use individual sending to bypass a blocked batch.

Inspect `fmg email template game-outreach` for the current version and required variables. Create one JSON file:

```json
{"name":"Game launch","template_id":"game-outreach","template_version":"1","recipients":[{"creator_id":"youtube:CHANNEL_ID","to":"creator@example.com","variables":{"creator_name":"Creator","game_name":"Selected Game","game_summary":"Factual introduction","game_url":"https://store.steampowered.com/app/570/","personalization":"Specific evidence-backed observation","sender_name":"Sender","company_name":"Company"}}]}
```

Up to 1,000 recipients per task, one address each; duplicate addresses within a task are rejected. Choose among multiple contacts before creation. Creator ID is the saved platform-qualified identity, not an invented personal name.

```sh
fmg --run-id RUN_ID outreach task create --input batch.json --idempotency-key STABLE_KEY
fmg outreach task list
fmg outreach task get TASK_ID
```

Create stores frozen template, rendered drafts, recipient addresses and revision, but **does not send**. A repeated key with the same payload returns the same task; changed payload conflicts. Save the task ID/revision locally. For modifications, edit the local input and create a new task/key, leaving the old one unapproved; review and approve only the replacement. No in-place edits or automatic approval transfer.

## Preview and monitor

Use the bundled, read-only dashboard instead of generating a webpage:

```sh
python3 PATH_TO_INSTALLED_FMG_API/scripts/outreach_dashboard.py --task-id TASK_ID
```

Resolve the installed Skill path; use `--fmg /absolute/path/to/fmg` if needed. Run it in a retained terminal session. The script prints a loopback URL; open that exact URL in Codex's built-in browser. It shows every recipient (20 per page), full text draft previews, sending state and responses, and polls every five seconds. It cannot approve/send/edit. The gateway credential remains in the CLI, never browser JavaScript. Closing this local process stops the dashboard, not an approved server task.

Opening the browser is part of the workflow: **before sending**, open the draft dashboard for review; **after approved start**, reuse/show it for sending progress; **after completion**, reuse/show it for outcomes and response tracking. If the relevant tab is already visible, do not create another or steal focus on every poll. Verify the page actually loaded; a queued browser-open request is not a visible-page confirmation. If the built-in browser is unavailable, explain that and provide the actual printed URL plus reviewable content. Do not auto-approve because the page opened, and never test recipient response links by submitting a Yes/No yourself.

Have the user review recipients and drafts, then explicitly approve the exact task revision. A request to create drafts alone is not permission to send. Save approval scope/message reference in local artifacts. Only then:

```sh
fmg outreach task start TASK_ID --revision REVIEWED_REVISION --confirm
```

The worker sends independently of Codex. Repeating start is safe for the same revision; do not recreate a batch after a timeout. Query its ID. `sent` means SMTP accepted, `failed` means explicit failure, `unknown` means delivery may have occurred: never automatically resend unknown rows. A separately approved replacement for known failed rows must exclude successful/uncertain ones. Unconfigured SMTP blocks start, and a sender change requires newly generated/reviewed drafts.

## Response meaning

Each message has independent, unguessable Yes/No links bound to its task recipient. Opening a link only shows confirmation; submitting records that recipient's response. Duplicate confirmation is idempotent; an opposite choice after confirmation is rejected and the recipient is asked to contact the sender. Each task invitation is independent, even for the same creator. Never click response confirmation on behalf of a creator during preview.

`response_rate` is Yes/No responses **among sent rows**, divided by sent rows; null when none were SMTP-accepted. Responses from uncertain deliveries are retained but excluded from that rate. Direct replies to the mailbox are not ingested. Yes is interest, not completed cooperation. Usage is attributed to the creation run ID; query it after sending completes. SMTP monetary cost remains unknown unless configured pricing exists.
