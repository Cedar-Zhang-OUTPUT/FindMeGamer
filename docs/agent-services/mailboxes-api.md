# Mailbox discovery and frozen draft identity

These are agent-service endpoints, not upstream platform operations; they do not belong in the platform `api-catalog`. All require the existing bearer token with `email:send`. Responses use `{ "data": ..., "meta": { "request_id": ... } }`. Discovery consumes no model/search quota and exposes no transport credentials, OAuth tokens or token-store paths.

## Discover

New LIMINAL drafts use `liminal` / `liminal-private-outreach` version `2` (plain text); No Rest uses `second` / `thieves-outreach` version `3` (plain text). The historical `ontologyplay` Hotmail identity is disabled for sending and monitoring; its old `liminal-outreach` template, immutable drafts, receipts and holds remain unchanged. No Rest stays `second` / `thieves-outreach`. Never transfer old approval or resend sent, unknown or in-flight attempts during migration.

`GET /v1/email/mailboxes` / `fmg email mailboxes`:

```json
{
  "data": [{
    "id": "liminal",
    "from": "liminal_within@ontologyplay.com",
    "display_name": "Ontology Play",
    "enabled": true,
    "ready": true,
    "allowed_templates": ["liminal-private-outreach"],
    "send_interval_seconds": 8,
    "send_interval_choices_seconds": [8, 9, 10]
  }],
  "meta": {"request_id": "REQUEST_ID", "mailboxes_version": 1}
}
```

`data` is an array, including disabled profiles. `id`, `from`, `display_name` are strings, `enabled`/`ready` booleans, `allowed_templates` an array of template IDs, and the send interval a number. `ready` reflects configured transport readiness, not a promise of provider acceptance or absence of a sender hold. A missing endpoint or unsupported/missing `mailboxes_version` makes the new CLI request an administrator upgrade; it never assumes capability from a client upgrade. Authentication/permission errors remain authentication/permission failures.

The user selects an enabled identity explicitly before creation. An allowlist entry is necessary but not sufficient for LIMINAL: `liminal-private-outreach` requires mailbox ID `liminal` and actual From `liminal_within@ontologyplay.com` (case-insensitive). `game-outreach` requires explicit permission in the chosen mailbox's list. Inspect `GET /v1/email/templates/{template_id}` (`fmg email template ID`) for the current string version and complete variable schema. Fixed text/images are server-owned.

## Create an immutable task or preview

`POST /v1/outreach/tasks` requires `Idempotency-Key` and accepts:

```json
{
  "name": "Reviewed campaign",
  "mailbox_id": "liminal",
  "template_id": "liminal-private-outreach",
  "template_version": "2",
  "recipients": [{
    "creator_id": "youtube:ACTUAL_ID",
    "to": "creator@example.com",
    "variables": {
      "creator_name": "Saved public name",
      "channel_name": "Saved channel",
      "reference_work": "Evidenced work",
      "specific_observation": "An evidence-backed connection."
    }
  }]
}
```

One to 1,000 recipients, one plain address each; same-task duplicate addresses are rejected. `creator_id` is at most 300 characters; task `name` 1–200; mailbox ID at most 40; template ID at most 100; version at most 40. Variables must match the selected server schema. Unknown fields are rejected. Creation stores the mailbox, sender/display name, template/version, rendered messages and approval revision; it does not send. Token ownership and run attribution remain unchanged. Same key + same payload returns the original task; changed payload conflicts.

`POST /v1/email/previews` accepts the same three identity fields plus `to` and `variables` (without task name or recipients). Preview responses contain `id`, `mailbox_id`, `display_name`, `template_id`, `template_version`, `message` (including frozen `from`/`from_name`, `to`, `subject`, `text` and server-owned inline assets), `created_at`, `send_ready`. `GET /v1/email/previews/{id}` rereads that snapshot; `send_ready` is evaluated against current configuration.

New CLI draft creation requires all three identity fields explicitly as nonempty strings, supplied in JSON or flags:

```sh
fmg outreach task create --input batch.json --idempotency-key STABLE_KEY --mailbox liminal --template liminal-private-outreach --template-version 2
fmg email preview --input message.json --mailbox liminal --template liminal-private-outreach --template-version 2
```

Flags fill absent fields; identical JSON values are allowed, differing values conflict before POST. Missing, null, empty or non-string fields fail locally. Older API clients may omit mailbox only under the server's narrow legacy compatibility path; this is not the new client contract. Disabled/unknown mailbox and prohibited template combinations fail server validation; the client never falls back to another account.

## Review, approval and reads

Full `GET /v1/outreach/tasks/{id}` returns task `id`, `name`, `revision`, state/progress, frozen `mailbox_id`, `sender`, `display_name`, `template_version`, full `template` (with `id`/`version`), recipient drafts and monitoring/safety. `?summary=true` retains lightweight identity/version/progress/safety without template bodies, recipients, images or replies. List responses likewise include mailbox, sender/display name and template version. An unresolved historical identity is shown explicitly; it is not assigned an account by the UI.

The local dashboard displays frozen identity and template/version using text escaping. It remains read-only and delivery-only, with no Reply UI or secrets; server reply monitoring and bounce protection continue.

After explicit user approval of the exact recipients, identity, rendered content and task revision, `POST /v1/outreach/tasks/{id}/start` accepts only `{ "revision": "REVIEWED_REVISION", "confirm": true }`. Individual `POST /v1/email/sends` accepts only `{ "preview_id": "ID", "confirm": true }` with a stable `Idempotency-Key`. Neither operation accepts a mailbox override. Changed identity/content requires a new draft and fresh approval. Existing approvals never transfer; `unknown` delivery is investigated, never automatically resent. Rate limits and holds do not authorize switching accounts.

Independent batches have no new cross-task/contact deduplication. Agents must divide contacts explicitly and save assignments plus stable creation keys. Each enabled mailbox has two sending slots shared with bounce retries and a shared lock. The server selects a random 8, 9 or 10 second cooldown after each transport attempt and persists it; polling cannot change it. `send_interval_seconds` is the minimum, and the additive `send_interval_choices_seconds` field lists the choices without changing discovery version 1. Mailboxes are timed independently. Dispatch/network delays may increase actual spacing. Gemini uses a separate four-slot enrichment queue and monitoring consumes neither. These capacity facts do not change per-task budgets, retries, sender holds or approval requirements.
