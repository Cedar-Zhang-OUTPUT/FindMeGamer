# Creator completion contract

Apply to every suitable creator delivered by a research task, including batches. Early rejected leads need not undergo expensive enrichment. A budget ceiling or service failure means partial delivery with explicit outstanding work, not permission to mark unqueried facts unavailable.

## Required checks

- Resolve canonical platform identity, homepage and public greeting name. Use a published display/preferred name, falling back to a real username/channel name (never guess a legal name).
- Inspect relevant works and describe content direction, all five Match rationale sections and evidence limitations. Search keywords alone do not prove a creator played a game.
- Query follower/subscriber counts even when there is no count filter. Reuse suitable saved responses; preserve known freshness limitations without requiring a new update timestamp.
- Collect the verified platform list and latest-up-to-10 cumulative view total using the rules below. Source evidence is required; a metric update timestamp is not.
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
{"status":"found","value":1234,"metric":"followers","source":"../evidence/followers-response.json"}
```

Use actual values and source evidence. `status=unavailable` requires `value=null`, source and `reason` explaining a successful check (e.g. platform hides the count). `pending`/`blocked`/`failed` remain incomplete. `checked_at` is optional: preserve a valid existing value when useful, but do not require or invent one. The display string identifies the platform metric or unavailable reason; no update date is required.

## Creator Profile metrics

During creator discovery/evaluation, collect these facts in the saved Creator Profile / JSON Match Brief so an Agent can later fill Feishu without repeating the research. A metrics-only request does not trigger email enrichment or a fresh discovery campaign.

- **Platforms:** retain `creator.platform` as the source/main account platform and its stable account ID and homepage. Save `creator.active_platforms` as the platforms actually verified for this creator; use the source platform as the initial known platform. Add another platform only with a confirmed account link/identity, not a matching display name. This list may represent verified source platforms; it does not assert a measured recent activity window. Do not search every possible platform solely to populate a multi-select.
- **Followers:** reuse `metrics.followers` for the main account's followers/subscribers. Keep additional platforms' counts separately with their account identity; never add them together. A single numeric CRM value uses the main account platform recorded with the profile/row source.
- **Recent content views:** select the latest **up to 10 unique public content items**, ordered by publication time, for that same account. Sum each selected item's cumulative view count. This is not an average, median, best-performing sample, last-10-days value, or channel lifetime total. For example, five items with 100, 200, 300, 400 and 500 views produce **1,500**, not 300. If more than 10 are available, include only the latest 10.
- A complete list of only five available items is a valid five-item sample; do not pad with zeroes, require 10, extrapolate to 10, or block on sample size. A page containing five items with more recent items still unexamined is not proof the account only has five: page within the agreed budget until the latest 10 or the end of the available list is established. Deduplicate by content ID before counting.
- Use YouTube's channel uploads to select recent videos and `videos.list` to read their view counts; a relevant-game search or popularity sort does not establish the latest 10. For Twitch, use the account's recent public videos/VODs by publication time; keep Clips as a separately labelled sample when requested, rather than silently pooling them with VODs. Live concurrent viewers are not cumulative views. For other platforms, use only a view counter actually exposed by the authorized API; likes/reposts cannot stand in for views.
- Missing/hidden view counts are unknown, not zero. If any selected item lacks a numeric count, keep the total unavailable/partial with `value: null` and explain the gap; retain the known records without presenting their subtotal as the complete total. An API failure stays blocked/failed. An explicitly confirmed empty available-content list may use total 0 and sample count 0, without claiming the creator never published anything.
- First inspect saved profiles and raw API responses. Reuse them if they establish this account, the latest selected items and their counts; an old average/median alone is insufficient. Query only missing or deliberately refreshed facts within the authorized budget. Do not use Gemini to estimate the numbers or rerun an email lookup to fill these metrics.
- **No update-time requirement:** do not add or require metric update/collection timestamps in the profile or Feishu. Existing timestamps in source artifacts may remain. Content publication dates are still needed to select the most recent items; they are not metric update timestamps.

Minimal saved view summary (example of a complete five-item sample):

```json
{"status":"found","platform":"youtube","value":1500,"sample_count":5,"source":"../evidence/recent-content.json"}
```

Store that summary as `metrics.recent_content_views`. Its source records retain selected content IDs/URLs, publication order/dates, individual numeric view counts and whether the available list ended before 10. Verify the sum against those records. No new timestamp property is required. For unavailable/partial/blocked/failed results use `value: null` and a concrete reason rather than a fabricated completed total.

For authorized CRM maintenance, map this saved total to `近10个内容的浏览量`, not `average_views` or `median_views`. Follow the installed fmg-api CRM guide for the actual field types, same-row updates and readback. Upgrading the Skill alone does not authorize a bulk historical backfill.

## Email evidence and final check

Store `contacts.basic_lookup` with `status=completed` and `source`. If no email is found there, store `contacts.enrichment` with actual `job_id`, `status=completed` and `source` pointing to the saved final service response. This artifact provenance is separate from Gemini's optional source URL. `not_found` needs both checks complete and an empty address list. If found, select one `primary_email` from the valid `emails` list, including a completed Gemini result without a source URL; retain `model_reported_unverified` and never invent a URL. Prefer the creator's explicitly designated collaboration/contact address, then their own published address over an unrelated agency inbox. Ask when the recipient is genuinely ambiguous. Preserve alternatives internally but display only the chosen address. Finding an address is not proof of delivery or consent to send.

Include the submitted API/profile evidence file path with enrichment progress, using fmg-api's public-evidence contract. A normal valid Gemini response completes enrichment: valid emails → Found; empty emails → Not Found. Missing sources/grounding or optional retrieval diagnostics do not change these outcomes and must not block the batch. Real failed/limited/timed-out/invalid-output jobs stay incomplete; a failed-attempt checkpoint is not a successful empty lookup. Legacy `public_pages_incomplete`/`enrichment_search_incomplete` jobs keep their actual state until the upgraded backend reconciles saved valid results without another paid call. Never create completion proof by editing state locally. Authorized retries keep the existing job/run and recorded usage. Not Found is best effort, not a guarantee that no address exists.

Run `python3 scripts/research_dashboard.py --root WORKSPACE --run-id RUN --validate`. Fix omissions or report a partial result with specific blocked counts. Never claim every creator has been fully analyzed merely because rows render. Inspect all required fields and underlying evidence as well: structural validation cannot verify truth or that the provider was actually called.
