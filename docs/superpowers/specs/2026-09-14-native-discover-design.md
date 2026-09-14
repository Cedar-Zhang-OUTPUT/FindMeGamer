# Native Discover → Analyze → optional Match

Status: design for user review. This document does not claim implementation or authorize deployment. The user confirmed that automatic Match uses the existing Library-wide eligibility rules, not only the Discover selection.

## Goal and boundaries

Extend the released native SwiftUI macOS 14+ application with a focused Discover workflow. Discover searches for creator homepages; a person chooses which accounts to analyze. Do not restore the Electron activity system or the former automatic analyze-every-candidate workflow. Keep the interface and generated analysis in English, the internal-company Demo quality target, and the current server infrastructure.

Existing production baseline: native application source `c880ccb`, operational release follow-up `26ea9d6`, native database head `20260914_native_0008`. New work must build on this native lineage; it must not restore the v2 database or import its migrations.

## Architecture choice

Recommended: a small persistent Discover job and analysis-batch coordinator, delegating to the existing Analyze and Match services. This adds explicit recovery/association records but survives app closure and supports duplicate-submission protection.

Alternatives considered:

1. Client-only chaining of search, individual analyses and Match: fewer server records, but app closure or network uncertainty could lose the follow-up Match or repeat submissions.
2. Reuse the entire v2 activity/discovery/evaluation model: contains reusable provider work, but brings back unrelated workflow states and interfaces that the user removed. Reuse only independently applicable provider adapters/helpers after review, not that subsystem wholesale.

No new hosted services. Use the current API, PostgreSQL, Celery Worker/Beat and existing secrets/storage facilities.

## Navigation and page composition

Sidebar order: Discover, Match, Outreach, Library, Settings. Keep the existing native visual style. Discover becomes the primary starting destination for a new launch without a restored destination; preserve explicit/restored navigation rather than forcibly redirecting a user.

Discover home:

- Heading: `Discover new creators`.
- Hero: `Use [game pill] to continue finding`, followed by `Start` once the game input is valid.
- The pill opens a popover with a search field, Library game results in a scrollable region sized for roughly three rows, then `or paste Steam URL` and its input.
- The complete game result list remains reachable by scrolling/pagination. Do not implement a three-result total limit. Search/filter changes do not reset an already selected game accidentally.
- A chosen Library game shows its name in the pill. A valid Steam URL resolves its app ID and public display name for selection; this lightweight resolution is not represented as completed AI analysis. Use an explicit resolving/error state, not a fabricated game name.
- Finding history sits below the hero, newest first, showing game, submission time and concise task status. Use a compact list/table rather than independent expanded cards for every stage.
- History and results are shared cloud records. Selection and form drafts are local until an explicit submission; row clicks and checkbox toggles make no persistence request.

## Conditions modal

`Start` opens a single modal with:

1. Platforms: YouTube, X, Twitch, Instagram checkboxes. YouTube and X enabled when configured; Twitch/Instagram visible but disabled and labeled `Unavailable` in this version. Neither is falsely advertised as collectable.
2. Content languages: multiselect list of content languages, searchable where necessary, with `Any` as the default.
3. Country or region: multiselect region list, with `Any` as the default.
4. Followers: `Any` or minimum/maximum follower bounds, with plain validation of inconsistent bounds. YouTube subscribers map to this filtering concept; labels in individual profiles remain platform-accurate.
5. Content Keywords: optional free text.

YouTube is the default selected platform; users can add X. Require at least one available platform. `Cancel` preserves the page's game selection and closes without a job; `Submit` explicitly starts the cloud workflow. No extra Match settings or email settings in this dialog.

Discover conditions apply to discovery, not to the subsequent Library-wide Match. The auto-Match confirmation must briefly state that Match also considers existing eligible Library creators.

## Game prerequisite and Discover execution

Submitting creates a Discover record promptly and returns its ID, even when a prerequisite is still pending. All stages appear under the same history record:

`Preparing game` (when needed) → `Finding creators` → `Done`, `Partial`, or `Failed`.

- For a Library selection or Steam app ID already in Library, reuse the existing valid Game Profile and preserve manual overrides.
- If absent or not usable for discovery, create/reuse the existing Game Analysis job and wait for it server-side. Do not create a second job for another request targeting the same running analysis.
- A failed game prerequisite prevents platform discovery, preserves the Discover record and offers a targeted retry. Never search as if a missing game profile had been analyzed.
- Snapshot the effective game context and submitted conditions for the discovery run so later edits do not silently change its historical meaning.
- Use the game facts/analysis/Brief and conditions to plan search terms, then use the enabled platform adapters to return public creator identities/homepages. Apply lightweight public metadata checks for filters where available.
- Do not perform full Creator analysis, email enrichment, deep Match or ranking during discovery. Displayed `Done` means discovery finished, not that its accounts have been analyzed or qualified for outreach.
- Proposed operational default: at most 100 unique accounts across the selected platforms per run, bounded platform requests/pagination, no guarantee of reaching 100. Keep this a backend limit instead of adding a primary-screen parameter.
- Country/content-language filtering uses attributable available information. Do not equate an arbitrary X location string with verified country, or silently pretend unknown attributes match restrictive filters. Unknown values remain visible as unknown; with restrictive filters, unverified candidates are not presented as confirmed matches. `Any` does not exclude unknown values.
- Zero results may be valid. Distinguish completed-empty from provider failure; do not silently loosen the user's filters.
- Isolate platform failures. Preserve successful results and a compact failure explanation, with retry limited to incomplete platform work. Prevent duplicate results on retries.

## Results and Library deduplication

Opening a history record shows one scrollable table: selection, creator display name (or handle), platform, homepage link, and a quiet `In Library` / analysis-state indicator where applicable. Keep optional filter/source details behind a disclosure. No separate persistent right-side detail area is needed for a list of URLs.

- Support select, deselect, Select all and Deselect all. Select all means the full finite result set, not only rendered rows; show the selected count. Preserve local selection across pagination and refresh by stable candidate ID.
- Show `Add Analysis` at the lower right only when at least one candidate is selected.
- Normalize identity by `(platform, stable platform account ID)` and canonical URL, not display name or literal URL text. Do not automatically merge the same-looking person across platforms.
- A Discover result may refer to an existing Creator. Keep it in Discover history but do not duplicate it in Library.
- Discovery alone persists candidate metadata in Discover storage, not a pretend fully analyzed Creator Profile.

## Add Analysis confirmation and orchestration

`Add Analysis` first opens `Do you want to start matching immediately after analysis?` No batch or analysis job is submitted before the choice.

- `Cancel`: close the dialog, retain selection, do not submit.
- `Just analyze`: submit the selected accounts to the existing analysis service.
- `Do matching immediately`: highlighted primary button; submit analysis and persist the server-side follow-up Match intent.

The selected-account snapshot and requested mode are committed once, with an idempotency key retained across ambiguous network failures. The server reuses an existing usable Profile, joins an already running compatible analysis, or enqueues the normal analysis path as appropriate. Failed refreshes never replace a successful existing Profile, and manual overrides are preserved.

Batch status shows reused, analyzing, succeeded and failed counts without implying that failed accounts succeeded. Analysis tasks are also visible through the existing analysis-task UI.

When the entire submitted batch reaches a terminal state, automatic mode creates exactly one ordinary Match task using the associated game and **all currently eligible Creator Profiles in Library**, including old profiles and newly analyzed accounts. Apply existing freshness/Brief validity rules and snapshot semantics. Do not require every new account to succeed; failed accounts remain available for targeted analysis retry. If Library has no eligible creators or the game cannot be used, show the actual blocked condition instead of creating a fake successful Match.

Link the created Match in the Discover record and ordinary Match history. App closure cannot cancel this follow-up. Duplicate worker deliveries/client retries cannot create extra Match tasks. Retrying failed analysis items after a Match has already been created does not silently create another Match; a later new Match remains explicit.

No email is sent by Discover, Add Analysis, or auto-Match.

## X analysis and platform-neutral compatibility

Current native storage and DTOs use required `youtube_channel_id`; simply adding an X search button is insufficient. Introduce a shared platform/account identity while preserving existing YouTube IDs and historical snapshots. Use an additive migration from native head; deployment may stop API/Worker/Beat in a maintenance window.

Adapt the full X path: canonical-link validation, stable identity resolution, public account/recent content acquisition, facts/analysis/Brief creation, available email discovery and fallback, persistence, Profile editing, Library detail/cards, and Match inputs. Reuse validated pieces from the old X adapter where appropriate. Never manufacture a YouTube channel ID or pretend X posts are YouTube videos to pass an existing schema.

Preserve existing YouTube behavior, multiple email addresses/purposes, manual edits, reanalysis retention and historical Match/outreach snapshots. All DeepSeek calls stay on `deepseek-flash`. Existing cloud X secret is already retained and should be used through the secret service, never copied into the client or committed.

Use a common core Profile/Brief structure for matching and editing, with typed platform-specific metrics/content details and source attribution. Unknown/private fields remain absent or explicitly unknown rather than zero/guessed. Provider provenance and manually supplied/curated data must remain distinguishable.

Twitch and Instagram identifiers can exist for curated Library records without enabling their live acquisition. Unsupported refreshes must retain imported data and explain unavailability rather than repeatedly submitting doomed provider jobs. This is a capability distinction, not a fabricated successful analysis.

## Later official API research and curated-import contract

After the Discover/X implementation, verify current official Twitch and Instagram documentation and report available account/content/metrics fields, authentication prerequisites, access limitations, and whether enough evidence exists for comparable Profile analysis. Do not promise arbitrary-account or email access without documentation/verification.

Deliver versioned machine-readable JSON Schema, fillable JSON templates and valid examples for other agents to prepare Twitch/Instagram records. Distinguish raw supplied facts/content/evidence from optional prepared analysis/Brief, document required/optional fields, stable identity, platform URL, content timestamps/URLs, metric semantics, emails/purposes/sources, nulls and missing values. Provide safe validation instructions and a mapping to the shared Profile model. No new end-user bulk-import UI or automatic fake dataset generation is included; actual supplied-record import is a later explicit operation.

## Failure and recovery rules

- Retain drafts when canceling, changing disclosure state, or recovering from errors.
- Never send a new write automatically merely because its previous response timed out; reconcile by idempotency/record identity first.
- Preserve partial discoveries, successful analysis and manually edited Profiles.
- Do not reset Library, change SMTP, send real outreach or expand platform permissions to make tests pass.
- Avoid fabricated progress percentages/ETAs. Use clear current-stage labels and actual counts.
- Retain visible recovery actions without stacking job internals, histories and settings in the primary task area.

## Verification and delivery order

1. Contract/platform identity migration with YouTube regression and X analysis tests.
2. Discover/game-prerequisite/result-deduplication API and worker tests.
3. Analysis batch, client retry/worker duplicate delivery and exactly-once auto-Match tests.
4. Native page/modal/table, local selection, scrolling, cancellation and recovery tests plus actual UI walkthrough.
5. Small real YouTube/X discovery and analysis checks with bounded requests; no SMTP. Verify selected game context and that an old eligible Library creator participates in automatic Match alongside the new selection.
6. Bounded independent review against the agreed Demo blockers; preserve fresh backups, migrate native DB, deploy, package and publish only after release authorization. No data reset is implied.
7. Official API research and curated Profile templates as described above.

Acceptance must specifically cover more than three games in the picker, off-screen result selection, malformed/duplicate Steam URLs, existing versus missing game analysis, duplicate Creator aliases, local-only checkbox changes, Cancel producing no jobs, partially failed analysis, closure/restart during orchestration, all-Library Match participation, X Profile edit/read/match compatibility, and clearly unavailable Twitch/Instagram.

Pure defensive edge cases, multi-tenancy, zero-downtime/old-new worker coexistence, unrelated UI redesign, and full v2 business-data conversion are outside this release.
