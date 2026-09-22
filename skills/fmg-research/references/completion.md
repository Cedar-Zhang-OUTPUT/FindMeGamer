# Creator completion contract

Apply to every suitable creator delivered by a research task, including batches. Early rejected leads need not undergo expensive enrichment. A budget ceiling or service failure means partial delivery with explicit outstanding work, not permission to mark unqueried facts unavailable.

## Required checks

- Resolve canonical platform identity, homepage and public greeting name. Use a published display/preferred name, falling back to a real username/channel name (never guess a legal name).
- Inspect relevant works and describe content direction, all five Match rationale sections and evidence limitations. Search keywords alone do not prove a creator played a game.
- Query follower/subscriber counts even when there is no count filter. Existing saved responses may be reused if their age is disclosed and suitable for the user's task.
- Assess content language and creator location from evidence independently. Audience geography is a separate fact; do not substitute creator location or infer nationality from language. Genuine missing evidence is allowed; describe what was checked.
- Inspect profile/about/bio and saved evidence for email. If absent, run `fmg email enrich`, save its job ID and poll the bounded job to completion. Enrichment is part of creator analysis, not an optional follow-up offer. Only a completed empty enrichment can become `not_found`; failed/limited/queued work stays unresolved. Never invent an address.

## Counts by platform

Use `fmg-api` help/catalogs for current command syntax:

| Platform | Required source | Metric |
| --- | --- | --- |
| YouTube | `channels.list`, `part=statistics`, `statistics.subscriberCount`; respect `hiddenSubscriberCount` | subscribers |
| X | account lookup with `user.fields=public_metrics`, `public_metrics.followers_count` | followers |
| Twitch | `getChannelFollowers`, broadcaster ID, `first=1`; read **total**, even if `data` is empty | followers |

Do not use video/stream viewers, views, following count, search-result counts or sums across platforms. Missing is not zero. An authorization, rate-limit, credit or network error is `blocked`, not a successful unavailable-count lookup. Save its evidence and recovery action; do not retry endlessly.

Every Match Brief stores `metrics.followers`:

```json
{"status":"found","value":1234,"metric":"followers","source":"../evidence/followers-response.json","checked_at":"2026-09-22T01:00:00Z"}
```

Use actual values and timestamps. `status=unavailable` requires `value=null`, source, timestamp and `reason` explaining a successful check (e.g. platform hides the count). `pending`/`blocked`/`failed` remain incomplete. The display string includes metric/date or unavailable reason. Do not create proof records without actually reading the source response.

## Email evidence and final check

Store `contacts.basic_lookup` with `status=completed` and `source`. If no email is found there, store `contacts.enrichment` with actual `job_id`, `status=completed` and `source` of the final service response. `not_found` needs both checks complete and an empty address list. If found, select one `primary_email` from the source-backed `emails` list; prefer the creator's explicitly designated collaboration/contact address, then their own published address over an unrelated agency inbox. Ask when the recipient is genuinely ambiguous. Preserve alternatives internally but display only the chosen address. Finding an address is not proof of delivery or consent to send.

Run `python3 scripts/research_dashboard.py --root WORKSPACE --run-id RUN --validate`. Fix omissions or report a partial result with specific blocked counts. Never claim every creator has been fully analyzed merely because rows render. Inspect all required fields and underlying evidence as well: structural validation cannot verify truth or that the provider was actually called.
