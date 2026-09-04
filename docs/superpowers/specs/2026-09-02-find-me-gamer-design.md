# Find Me Gamer — Product and System Design

**Date:** 2026-09-02

**Status:** Approved section-by-section in conversation; pending review of this written specification
**Audience:** Product, macOS, backend, and deployment implementers

## 1. Summary

Find Me Gamer is an internal macOS application for game publishers and brand teams. It turns a Steam game page and a pre-analyzed library of YouTube creators into an explainable creator shortlist, then supports personalized email outreach and response tracking.

The product is a shared, single-workspace internal tool. It has no personal user accounts. All business data lives on a shared cloud backend; the macOS app is a thin SwiftUI client. The first release is a working end-to-end internal product, not a UI-only prototype.

The core flow is:

1. Analyze a Steam game or YouTube creator URL.
2. Browse the shared Game and Creator Library.
3. Start a Match for an existing Game Profile.
4. Progressively screen and deeply compare creators already in the Library.
5. Review recommended creators without exposing numeric ranks or scores.
6. Send individual or batch outreach emails using shared templates.
7. Record `Accepted`, `Declined`, or `No Response` through signed public response links.

## 2. Goals

- Provide a native macOS 14+ SwiftUI client with a Codex-like sidebar and central workspace.
- Analyze real Steam game pages and real YouTube creator channels.
- Store a shared Library that all coworkers see immediately.
- Match only against Creator Profiles already present in the Library.
- Use progressive AI disclosure: compact screening, pairwise deep analysis, then final ranking.
- Keep backend rank and score private while presenting qualitative recommendations and evidence.
- Send real outreach through a shared NetEase 163 enterprise SMTP mailbox.
- Track outreach by Match Task, send batch, creator, and response state.
- Run scheduled Game and Creator re-analysis in the cloud.
- Deploy quickly on one existing AWS EC2 server in the United States, using an existing S3 service.

## 3. Non-goals for Version 1

- Personal accounts, roles, permissions, or multi-tenant workspaces.
- Automatic YouTube creator discovery during Match.
- Public consumer access or App Store distribution.
- Localization or language switching; all product and AI content is English.
- Downloading YouTube video/audio, extracting frames, or scraping unofficial transcripts.
- Permanent Profile version browsing or permanent raw YouTube snapshots.
- WebSocket or push-based job updates.
- High availability, auto-scaling, zero-downtime deployment, or multi-region failover.
- Managed AWS services such as RDS, SQS, Lambda, ECS, ALB, Secrets Manager, CloudWatch, or SNS.
- Email open tracking, verified delivery tracking, bounce ingestion, or inbound mailbox parsing.
- Exact numeric Match scores or ordinal ranks in the macOS UI.

## 4. Product Principles and Fixed Boundaries

### 4.1 Shared workspace

- Every installed client connects to the same workspace and sees the same Profiles, Jobs, Match Tasks, Templates, Campaigns, favorites, and shared settings.
- There is no personal identity or ownership attached to a change.
- A shared Workspace Access Key protects internal APIs without introducing personal login accounts.
- The key is entered once on first launch and stored in macOS Keychain.

### 4.2 Cloud is the source of truth

- PostgreSQL is the only source of truth for business data.
- Redis is a job broker and coordination layer only.
- S3 stores temporary analysis artifacts and database backups.
- The client stores only the Workspace Access Key and local appearance preferences.
- The client does not use SwiftData or Core Data for business data.

### 4.3 English-only product

- App UI, status text, AI prompts, Profile output, Match output, default templates, and response pages are English-only.
- There is no localization framework or language picker in version 1.
- User-authored template content is saved verbatim and is not translated automatically.
- The intended operating language for templates is English.

### 4.4 Current Profiles, stable Match conclusions

- A successful Re-analyze replaces the current Profile atomically.
- Version 1 does not expose or permanently retain historical Profile versions.
- A Match freezes its recommendation group, backend order, qualitative labels, and Match Reasons.
- Opening a Creator or Game from an old Match always shows the current Library Profile.
- The exact subject and body of sent emails are retained as business records.

## 5. Information Architecture

The app uses a two-column `NavigationSplitView` with four Sidebar destinations:

1. Library
2. Match
3. Outreach Management
4. Settings

`Analyze Request` is not a Sidebar destination. It is an action inside Library.

`Match Result` is not a Sidebar destination. Match creation, task history, and result detail share the Match workspace.

## 6. macOS Application Design

### 6.1 Platform and navigation

- Minimum deployment target: macOS 14 Sonoma.
- The app is a single-window SwiftUI application.
- Each Sidebar feature owns an independent `NavigationStack` so local navigation state is preserved.
- Match Result detail pushes within the Match workspace and uses Back to return.
- Profile detail uses a shared, resizable system Sheet.
- Outreach composition uses a separate system Sheet.
- Analyze Request uses a right-side, non-modal Inspector.

### 6.2 Liquid Glass compatibility

- The app never implements a custom blur, shader, or imitation of Liquid Glass.
- On macOS 26 and later, it uses Apple-provided Liquid Glass behavior and APIs such as standard system controls, system Glass button styles, `glassEffect`, and `GlassEffectContainer` where appropriate.
- On macOS 14–15, the identical layout uses standard SwiftUI controls without attempting to mimic Liquid Glass.
- Availability checks isolate macOS 26-only APIs.
- System structures come first: `NavigationSplitView`, Toolbar, Sheet, Inspector, Segmented Controls, Menu, and Button.
- App-specific official glass treatment is limited to high-value surfaces such as Match Hero, the batch outreach action bar, and the Analyze Request status entry.
- Gallery cards remain flat and readable rather than receiving glass on every item.

### 6.3 Client architecture

- `AppSession` owns Workspace Access Key validation, base URL, and server connection status.
- A generated OpenAPI client communicates through URLSession.
- Generated API types are wrapped and mapped into client domain models before reaching Views.
- Feature modules:
  - Library
  - Match
  - Outreach
  - Settings
- Each feature owns a focused `@Observable` model.
- A shared Job Poller batches status updates and informs only affected feature models.
- Shared UI includes Profile Detail, Job Status, Email Composer, error banners, and empty/loading states.

### 6.4 Local persistence

- Keychain: Workspace Access Key.
- UserDefaults/AppStorage: appearance mode and font size.
- System URL cache: transient image caching.
- No persistent local business database.

### 6.5 Startup flow

1. Load the configured service base URL.
2. Read the Workspace Access Key from Keychain.
3. If absent or invalid, show the shared workspace access screen.
4. Validate the key with the backend.
5. Open Library by default.
6. Load Profiles, active Jobs, and shared settings in parallel.
7. Show a global Offline Banner if connectivity is lost and disable write actions until reconnection.

## 7. Workspace Specifications

### 7.1 Library

The Library header has two rows.

First row:

`[Game / Creator]  [Only Collection]                         [Analyze Request]`

Second row:

`[Search Profiles…]`

Rules:

- Game/Creator is a Segmented Control.
- Only Collection uses checkbox styling and filters the shared favorite flag.
- Search sits directly below the switcher, is left-aligned, and has a moderate maximum width rather than stretching across a very wide window.
- Search is server-side and debounced.
- Analyze Request is pinned to the upper-right and displays the number of running Analysis Jobs as a badge.
- Results use an adaptive, flat `LazyVGrid` with cursor pagination.
- Changing type, search, or collection filter preserves the other controls' state.

Game Card shows:

- Cover
- Name
- Short Summary
- Primary Tags
- Favorite action

Creator Card shows:

- Avatar
- Channel name
- Subscriber count
- Recent performance summary
- Primary content Tags
- Contact email availability
- Favorite action

Favorite changes are optimistic and roll back if the server request fails. Clicking Favorite never opens the Profile Sheet.

### 7.2 Analyze Request Inspector

- Creator/Game switcher
- URL field
- Submit
- Reverse-chronological Analysis Job list
- Running spinner, green success indicator, and red failure indicator
- Short stage text only: `Fetching Data`, `Analyzing`, or `Finalizing`
- Existing Profile result with `Open Profile` and `Re-analyze`
- Inspector closure never stops a cloud task
- Completion refreshes the affected Library type and highlights the changed card

Duplicate rules:

- URLs are canonicalized to Steam App ID or YouTube Channel ID.
- The backend globally deduplicates Profiles.
- An already-running task for the same target is returned instead of duplicated.
- An existing completed Profile is returned without re-analysis unless the user explicitly chooses Re-analyze.

### 7.3 Match workspace

The top of the Match page is a centered Hero with generous whitespace:

`Find me a creator for [Select Game] [Submit]`

- Submit is hidden until an analyzed Game Profile is selected.
- The selector shows the selected game's thumbnail and name.
- Submitting immediately adds the new task to Match History.

Match History:

- Reverse chronological
- Game cover and name
- Creation time
- Current stage: `Screening`, `Comparing Creators`, or `Ranking`
- Running, success, or failure indicator
- Retry action for failed tasks
- Successful result count
- Successful rows push to Match Result detail

Match Result detail:

- Compact Game header with action to open the full Game Profile
- `Recommended Matches`, expanded by default
- `Other Matches`, collapsed by default
- No ordinal number and no numeric Match score
- Backend order controls display order inside each group
- Creator rows show identity, qualitative Match label, core reasons, performance summary, contact availability, and Outreach state
- `View Match Details` progressively expands the full Match Brief
- Clicking Creator identity opens the shared current Creator Profile Sheet
- Individual Send Email action
- Multi-select checkboxes and a bottom `Send Outreach (N)` action bar
- When a Creator has multiple active emails, sending requires choosing exactly one address and shows each address's purpose; the client never defaults to emailing all addresses
- No-email creators remain visible but cannot be selected for sending
- Previously sent creators cannot be selected again without an explicit Resend action
- Unscreened Creator Profiles are absent from the result UI

### 7.4 Outreach Management

The workspace uses three Segmented Tabs.

#### Campaigns

- Default tab
- One Outreach Campaign per Match Task
- Game, unique creator send count, Accepted, Declined, No Response, Failed, and response rate
- Campaign detail shows Send Batches and individual Deliveries
- Campaign response rate is unique responded creators divided by unique successfully sent creators

#### Templates

- Shared template list
- Create, duplicate, edit, set default, and delete
- Subject Template
- Markdown Body
- Live rendered HTML preview
- Allowed variables:
  - `{{creator_name}}`
  - `{{channel_name}}`
  - `{{game_name}}`
  - `{{steam_url}}`
  - `{{game_summary}}`
  - `{{match_reason}}`
  - `{{sender_name}}`
- Variable insertion menu and sample-data validation
- No arbitrary raw HTML
- Accepted and Declined button labels are configured separately from Markdown
- Default labels are `Yes, I'm in` and `No, I'm not interested`
- Final per-delivery HTML is stored at send time, so template edits never mutate history

#### Email Settings

- SMTP host
- Port
- Encryption mode
- Username
- Credential replacement
- From Name
- Reply-To
- Emails-per-minute limit, default 10 and configurable from 1–60
- `Test Connection`
- `Send Test Email`
- Last test outcome and time
- Secret values are never returned to the client

### 7.5 Settings

#### Appearance — local

- System / Light / Dark
- Font Size
- Restore Defaults

#### Service Connections — shared cloud settings

- Steam
- YouTube
- DeepSeek
- Google AI Studio
- Each displays `Configured` or `Not Configured`, last test time, Replace Key, and Test Connection
- Secret plaintext is never returned

#### Re-analysis Schedule — shared cloud settings

- Creator interval: required, 1–30 days, default 14
- Game interval: required, 1–90 days, default 30
- Neither schedule can be disabled
- Last run and next scheduled run are shown

#### Workspace

- Server connection state
- API base URL
- App version
- `Disconnect This Mac`, which clears only the local Workspace Access Key

Cloud setting changes require an explicit Save action and warn that all coworkers are affected.

## 8. Shared Profile Detail

The shared Profile Sheet uses a system presentation and a scrollable adaptive layout.

Common Header:

- Cover or avatar
- Name
- Source platform and canonical URL
- Favorite
- Open in Steam/YouTube
- Re-analyze
- Last Analyzed
- Next Re-analysis

Wide sheets use two columns; narrow sheets collapse to one. Facts and AI inference are visually distinguished.

### 8.1 Game Profile fields

- Steam identity: name, App ID, URL, developer, publisher, release state/date
- Store assets: cover, screenshots, trailer links, store description
- Store metadata: Genres, Tags, Categories, Game Modes, Platforms, Languages, Review Summary
- AI analysis:
  - Short Summary
  - Core Gameplay Loop
  - Themes
  - Visual Style
  - Tone
  - Target Audience
  - Key Selling Points
  - Content Hooks
  - Comparable Games
  - Suitable Creator Types
  - Potential Promotion Risks
- Analysis time, data update time, model identifiers, prompt version, and source status

Unavailable Steam data remains unavailable; the system never fabricates inaccessible fields such as private publisher analytics or wishlist counts.

### 8.2 Creator Profile fields

- YouTube identity: channel name, Handle, Channel ID, URL, avatar, and banner
- Public metrics: subscribers, total views, public video count, recent upload count, and publishing frequency
- Performance: recent average and median views, engagement summary, and representative videos
- Content analysis: primary games, genres, formats, style, pacing, production quality, and livestream/long-form/short-form tendency
- Audience inference: primary language, likely audience region, and interests, clearly marked as AI inference
- Promotion fit: common sponsorship patterns, brand safety, suitable game types, and collaboration risks
- Contact: an ordered list of public emails with purpose, source, and validation status, plus linked site and social links
- Favorite, manual notes, last analyzed, next scheduled analysis, model identifiers, and prompt version

The first contact remains available as a compatibility projection, while the full email list is exposed for display and Outreach selection. Manual contact email is marked `Manual`, takes precedence over discovered contact information, and is never overwritten by Re-analyze.

Match Brief is not embedded into the Creator Profile Sheet because it is specific to one Game and one Match Task.

## 9. Backend Architecture

### 9.1 Deployment topology

Version 1 uses an existing AWS EC2 server in a United States commercial region and an existing S3 service.

Docker Compose services:

- `proxy`: Caddy, HTTPS termination and routing
- `api`: FastAPI application
- `worker`: Celery worker
- `beat`: Celery Beat scheduler
- `postgres`: PostgreSQL
- `redis`: Redis broker

No additional managed AWS runtime or monitoring service is required.

### 9.2 Service responsibilities

#### FastAPI

- Workspace key validation
- Library reads and mutations
- Job creation and status APIs
- Match APIs
- Outreach and Template APIs
- Settings and connection tests
- Public response confirmation and submission
- OpenAPI generation

#### Celery Worker

- Game Analyze
- Creator Analyze
- Match screening
- Pairwise Deep Match
- Final Match ranking
- SMTP sends
- CSV seed import processing
- Retryable background work

#### Celery Beat

- Enqueue due automatic re-analysis
- Stagger work rather than enqueuing every Profile simultaneously

Database backup is not a Celery business Job. A host cron entry or systemd timer runs it independently so a broken application queue cannot suppress backups.

#### PostgreSQL

- Sole business data source
- Current Profiles, Jobs, Match results, Outreach records, Templates, and shared settings

#### Redis

- Celery broker and short-lived coordination only
- Never the sole location of business state or final Job status

#### S3

- Temporary raw acquisition payloads
- Temporary image analysis artifacts
- Database backups
- Prefix-based lifecycle expiration

## 10. Core Data Model

### 10.1 Profiles

`game_profiles`

- Stable ID and Steam App ID
- Canonical URL
- Current facts, AI analysis, Game Brief, and source freshness
- Favorite flag
- Last/next analysis timestamps
- Model and prompt metadata

`creator_profiles`

- Stable ID and YouTube Channel ID
- Canonical URL
- Current facts, AI analysis, Creator Brief, and source freshness
- Favorite flag and manual notes
- Last/next analysis timestamps
- Model and prompt metadata

`creator_contacts`

- Creator ID
- Email
- Source type and source URL
- Manual/discovered flag
- Validation state
- Priority and active state

There is no permanent Profile Version table in version 1.

### 10.2 Jobs

`analysis_jobs`

- Target type and canonical target ID
- Mode: create or re-analyze
- Status: queued, running, succeeded, failed
- Stage, completed/total unit counts, error code, retryable flag, correlation ID
- Related Profile ID
- Created/started/completed timestamps

`match_tasks`

- Game ID
- Locked Game Brief used by the task
- Status and stage
- Hidden recommendation threshold used by the task
- Screening, comparison, and ranking progress
- Error and retry metadata
- Created/started/completed timestamps

`match_screening_records`

- Match Task ID and Creator ID
- Locked Creator Brief used by screening
- Selected flag and screening reason
- Retained for 30 days for diagnostics

`match_candidate_inputs`

- Match Task ID and selected Creator ID
- Locked full Creator Profile input used by Pairwise Deep Match
- Input model and prompt metadata
- Retained for 30 days to support deterministic checkpoint retry
- Internal task data only; never exposed as a browsable historical Profile version

`match_result_items`

- Match Task ID and Creator ID
- Match Brief
- Hidden numeric total and dimension scores
- Hidden backend order
- Qualitative labels and dimension outcomes
- Result group and Match Reasons

The API never serializes hidden rank or numeric total score to the macOS client.

### 10.3 Outreach

`outreach_campaigns`

- One-to-one with Match Task
- Aggregate state derived from Deliveries

`send_batches`

- Campaign ID
- Template ID
- Batch status and requested time
- Selected Creator IDs

`deliveries`

- Campaign, Send Batch, and Creator IDs
- The single explicitly selected contact email used; a Creator with multiple active emails requires a recipient selection before preview or send
- Rendered subject, Markdown source, and final HTML
- Template name/version metadata
- Send state: queued, sending, sent, failed
- Response state: no_response, accepted, declined
- Response token hash
- SMTP error details safe for display
- Created/sent/responded timestamps

`templates`

- Name and default flag
- Subject Template and Markdown Body
- Accepted/Declined labels
- Created/updated timestamps

`shared_settings`

- Creator and Game re-analysis intervals
- Internal recommended Match threshold, default 0.70
- SMTP rate limit
- Service connection state metadata

`service_secrets`

- Encrypted Steam, YouTube, DeepSeek, Google AI Studio, and SMTP values
- AES-256-GCM ciphertext, nonce, update time, and last connection test status
- The encryption key is not stored in PostgreSQL

## 11. Analyze Pipeline

### 11.1 Common behavior

1. Validate and canonicalize the submitted URL.
2. Resolve Steam App ID or YouTube Channel ID.
3. Return an active duplicate Job if one exists.
4. Return the existing Profile unless explicit Re-analyze was requested.
5. Create the Analysis Job in PostgreSQL before enqueuing it.
6. Fetch source data and store only temporary acquisition artifacts in S3.
7. Run model stages using English prompts and strict structured output.
8. Validate the complete output against the Profile schema.
9. Atomically replace the current Profile only after full success.
10. Leave the previous current Profile untouched on Re-analyze failure.

Transient network, rate-limit, and model failures retry with exponential backoff. Invalid URLs, missing resources, and unsupported targets fail without repeated retries. AI schema failures receive one repair attempt followed by a clean retry.

### 11.2 Game Analyze

1. Parse the Steam App ID.
2. Fetch public store data and any additional public data available through the configured Steam API key.
3. Collect text, Tags, categories, public reviews summary, and media URLs.
4. Use `deepseek-v4-flash` for structured extraction.
5. Use `deepseek-v4-flash-vision-exp` for cover and representative screenshot understanding.
6. Use `deepseek-v4-pro` for final synthesis and Game Brief generation.
7. Validate and update the current Game Profile.

Vision is optional within the pipeline. If the experimental Vision model fails after its retries, the Game Analyze can complete using text evidence and marks visual analysis as unavailable.

### 11.3 Creator Analyze

1. Resolve Channel ID from Channel URL or Handle.
2. Fetch channel snippet, content details, statistics, and uploads playlist through YouTube Data API.
3. Fetch metadata and public statistics for the 50 most recent public videos.
4. Compute recent frequency and performance summaries.
5. Use `deepseek-v4-flash` to analyze the 50 videos' titles, descriptions, Tags, duration, dates, and performance context.
6. Choose about 12 representative official thumbnails, balanced between recency and recent performance.
7. Use `deepseek-v4-flash-vision-exp` for thumbnail-level visual analysis.
8. Search the public channel description and linked public websites for a business contact email.
9. Only when that evidence contains no email, use `gemini-3.8-flash` with Google Search and URL Context for bounded public-web email research; never replace an email already found by the original path.
10. Use `deepseek-v4-pro` for final Creator Profile and Creator Brief synthesis.
11. Preserve manual email and manual notes while replacing current analyzed fields.

Version 1 does not download video/audio, extract frames, or use unofficial transcript endpoints. YouTube's official caption download API is unsuitable for arbitrary creators because it requires permission to edit the video.

The experimental Vision step is non-fatal for Creator Analyze as well. After its retries are exhausted, text and public metadata analysis may still complete, with visual analysis marked unavailable.

### 11.4 Source retention and refresh

- Creator Re-analyze is mandatory and can be scheduled from 1–30 days.
- Game Re-analyze is mandatory and can be scheduled from 1–90 days.
- The scheduler checks due Profiles every 15 minutes and enqueues them in small batches.
- Manual Re-analyze resets `next_analysis_at` after successful completion.
- Creator raw API JSON, thumbnail cache, and temporary source artifacts expire from S3 within 30 days.
- YouTube API fields shown in Library always come from the latest successful refresh.
- A Creator whose latest successful refresh becomes older than 30 days is marked `Stale`, excluded from new Match tasks, and has expired YouTube-derived fields hidden until refresh succeeds. Manual contact information and notes remain available.
- An internal-only deployment is not treated as an exemption from YouTube data refresh requirements.
- A formal YouTube API compliance review is deferred until the product expands beyond the internal pilot.

## 12. Match Pipeline

Match uses only current Creator Profiles already in Library. It never discovers new creators.

### 12.1 Briefs

- Every Game Profile contains a relatively detailed Game Brief.
- Every Creator Profile contains a compact Creator Brief.
- Briefs are regenerated with the Profile during Analyze/Re-analyze.

### 12.2 Stage 1 — Candidate Screening

- Model: `deepseek-v4-flash`
- Input: one detailed Game Brief plus every compact Creator Brief in Library
- Creator input order is shuffled with a stable per-task seed to reduce position bias
- Output: zero to 30 selected Creator IDs and screening evidence
- Purpose: identify creators worth expensive deep comparison, not produce final rank
- Unselected creators remain hidden from the client

If screening selects zero creators, the Match Task succeeds with an empty result and skips Pairwise Deep Match and Final Ranking. The client displays a clear `No suitable creators found` state.

### 12.3 Stage 2 — Pairwise Deep Match

- Model: `deepseek-v4-pro`
- One independent model call per selected Creator
- Input: locked Game Brief plus the selected Creator's complete Profile details captured for this Match Task
- Output: one Match Brief containing:
  - Content Fit
  - Audience Fit
  - Performance Fit
  - Promotion Fit
  - Brand Safety
  - Strengths
  - Risks
  - Evidence
  - Match Reasons
- At most 30 subtasks run with a server concurrency limit of 5
- Match input data is locked when the task starts so a concurrent Re-analyze cannot change the task mid-run

### 12.4 Stage 3 — Final Ranking

- Model: `deepseek-v4-pro`
- Input: all successful Match Briefs
- Output: hidden total/dimension scores, hidden backend order, qualitative labels, final reasons, and recommended/other grouping
- Default hidden recommended threshold: 0.70
- The threshold value is saved on the Match Task so later configuration changes do not regroup old results
- Client API output contains group, qualitative labels, qualitative dimension outcomes, and reasons, but not numeric rank or numeric total score

Qualitative labels are `Strong Match`, `Good Match`, and `Limited Match`. Labels and reasons explain the result without presenting false numeric precision.

Contact email availability, favorite state, and prior outreach never affect Match score. They affect only outreach actions.

### 12.5 Match failure behavior

- Every model output passes strict JSON Schema validation.
- Successful pairwise Match Briefs are checkpointed.
- A retry resumes only missing or failed nodes.
- If any pairwise comparison remains failed after retries, the Match Task fails and publishes no partial result.
- Final Ranking runs only when every selected pair has a valid Match Brief.
- Match History exposes Retry on a failed task.
- Immutable Match input snapshots are retained for 30 days. After they expire, Retry creates a new Match Task against current eligible Profiles and marks the old failed task as superseded rather than pretending to resume the original inputs.

## 13. Outreach Pipeline

### 13.1 Campaign hierarchy

`Match Task → Outreach Campaign → Send Batch → Delivery`

- Every Match Task has one Campaign.
- Each individual or batch send creates a Send Batch.
- Each Creator message creates a Delivery.
- Campaign metrics aggregate by unique Creator rather than number of emails.

### 13.2 Compose and confirmation

1. User selects one or more eligible creators from Match Result.
2. For every Creator with multiple active emails, the user explicitly selects one recipient using its displayed purpose and source.
3. Composer loads the default or chosen Template.
4. Variables render separately for each Creator.
5. The user previews the rendered output and may make a send-only override.
6. The system validates the selected active contact email, SMTP configuration, Template variables, CTA labels, and duplicate-send rules.
7. Final confirmation creates one Delivery per Creator in the Send Batch with an Idempotency Key.
8. Celery sends messages through NetEase enterprise SMTP at the configured rate.

Markdown controls only the body. The backend renders and sanitizes HTML, then appends the system-controlled response block. Template authors cannot remove or replace response endpoints through raw HTML.

### 13.3 Response links

- Every Delivery has a cryptographically random token; only its hash is stored.
- The email contains Accepted and Declined links with the corresponding choice preselected.
- GET opens a branded confirmation page and never mutates data.
- The Creator confirms with a POST.
- The confirmation page reuses the Delivery's configured Accepted/Declined labels while keeping the surrounding system copy in English.
- The first confirmed response for a Campaign/Creator pair is final.
- Reopening any response link displays the recorded state.
- A public link cannot change a confirmed result.
- No Creator account is required.

### 13.4 Send and resend semantics

- SMTP acceptance is called `Sent`, never `Delivered`.
- Clear SMTP rejection is `Failed`.
- Transient SMTP errors retry; permanent errors do not.
- An explicit Resend creates a new Delivery and supersedes the prior no-response or failed Delivery.
- A superseded Delivery's response link becomes read-only and cannot submit a new choice.
- Resend is disabled after the Campaign/Creator pair has a confirmed Accepted or Declined response.
- The first confirmed response across valid Deliveries locks the Campaign/Creator response.

## 14. API Contract

### 14.1 General rules

- Internal base path: `/api/v1`
- Internal authorization: bearer Workspace Access Key
- Public response paths: `/r/{token}` and corresponding POST endpoint
- JSON request/response bodies
- Cursor pagination for lists
- Idempotency Key required for Analyze creation, Match creation, Send Batch creation, and Retry commands
- Standard errors include code, user-readable message, retryable flag, and correlation ID
- Secret reads return status only, never plaintext

### 14.2 Main resource groups

#### Session

- Validate Workspace Access Key
- Return sanitized workspace and service status

#### Jobs

- Create Analysis Job
- List Jobs changed after a cursor
- Read Job
- Retry Job

#### Profiles

- List/search/filter Game or Creator Profiles
- Read Profile
- Toggle shared Favorite
- Update manual Creator contact and notes

#### Match

- Create Match Task
- List Match History
- Read Match Task and result groups
- Retry failed Match Task

#### Outreach

- List/read Campaigns
- Create Send Batch
- Read Deliveries
- Manage Templates
- Read/update SMTP configuration status
- Test SMTP connection and send test email

#### Settings

- Read/update re-analysis intervals
- Read connection status
- Replace and test Steam, YouTube, DeepSeek, and Google AI Studio keys

#### Public Response

- GET confirmation page without mutation
- POST final Accepted/Declined response

### 14.3 Job polling

- Job states: `queued`, `running`, `succeeded`, `failed`
- Client maps queued/running to Loading, succeeded to green, and failed to red
- Job includes stage, completed/total work, safe error, retryability, related resource ID, and timestamps
- While any Job is active, the client polls the changed-Jobs endpoint every three seconds
- When no Job is active, polling stops
- App activation and manual Refresh trigger immediate synchronization
- Job completion returns affected resource IDs so only relevant feature data reloads
- Version 1 does not use WebSocket or push updates

## 15. Security Baseline for the Internal Pilot

The release intentionally avoids complex managed security services while retaining low-cost safeguards necessary for real SMTP and API credentials.

- HTTPS is mandatory.
- Public HTTP redirects to HTTPS.
- Only the reverse proxy is publicly reachable.
- PostgreSQL and Redis listen only on the internal Docker network.
- Workspace Access Key is hashed with Argon2id.
- Public response tokens are high-entropy and stored as SHA-256 hashes.
- Service secrets use AES-256-GCM encryption in PostgreSQL.
- The encryption master key is stored in a root-owned, mode `0600` server file outside the repository and mounted read-only into API and Worker containers.
- One recovery copy of the master key is stored outside EC2 in the company's existing password-management process; it is not uploaded beside database backups.
- Logs never include keys, response tokens, SMTP credentials, or complete email bodies.
- Internal, response, and SMTP operations have rate limits.
- The EC2 Instance Role can access only the required S3 bucket prefixes.
- Server administration is restricted by network policy rather than exposing PostgreSQL, Redis, or unrestricted SSH.

## 16. Deployment and Operations

### 16.1 Deployment

- Target: existing AWS EC2 server in the United States
- Runtime: Docker Compose
- Persistent database volume: EC2/EBS-backed Docker volume
- HTTPS and routing: Caddy
- Public service address: a company-controlled domain configured through `SERVICE_BASE_URL`
- One deployment script performs:
  1. Pull/build images
  2. Pre-migration database backup
  3. Database migrations
  4. `docker compose up -d`
  5. Health verification

Brief deployment interruption is acceptable for version 1.

### 16.2 Backups

- Daily `pg_dump`
- Encrypted upload to the existing S3 backup prefix using bucket default encryption
- Thirty-day backup retention
- Separate S3 lifecycle prefix for YouTube acquisition artifacts, expiring within 30 days
- One successful restore rehearsal before internal release

### 16.3 Minimal monitoring

- Docker Health Checks
- Docker restart policies
- Host log rotation
- `/health/live` for process liveness
- `/health/ready` for PostgreSQL and Redis readiness
- Job error details and correlation IDs in the client
- No CloudWatch agent or external alerting in version 1

## 17. Initial Creator Seeding

The first 100 KOLs are loaded before coworkers receive the app.

The backend includes an administrative CSV import command; it is not exposed in the macOS UI.

CSV columns:

- `youtube_url` — required
- `contact_email` — optional, imported as Manual Contact
- `notes` — optional

Import behavior:

- Canonicalize Channel IDs
- Skip duplicates
- Enqueue normal Creator Analysis Jobs
- Preserve manual email and notes
- Resume after interruption
- Retry only failed or incomplete entries
- Emit counts and row-level reports for succeeded, duplicate, and failed entries

After seeding, coworkers add individual Creators through Analyze Request.

## 18. Error Handling

### 18.1 Client

- Global Offline Banner
- Feature-level loading and empty states
- Inline Job failure with safe error and Retry
- Optimistic Favorite rollback
- Write controls disabled while offline
- Profile Re-analyze failure shown without discarding the previous Profile
- SMTP and service connection tests show last result and timestamp

### 18.2 Backend

- Correlation ID per request and Job
- Transactional Job creation before enqueue
- Atomic Profile replacement after full validation
- Idempotent task boundaries
- Exponential backoff for transient external errors
- Explicit non-retryable source errors
- Checkpointed Match subtasks
- No partial Match publication
- No partial Send Batch creation

## 19. Verification Strategy

### 19.1 Unit tests

- URL canonicalization and deduplication
- Job state transitions and retry decisions
- Mandatory re-analysis schedules and Creator 30-day maximum
- Match screening cap of 30
- Hidden score/rank serialization rules
- Markdown variable rendering and CTA injection
- HTML sanitization
- Idempotency and duplicate-send prevention
- Campaign aggregation by unique Creator
- Workspace key and response token verification
- Secret encryption/decryption and response redaction

### 19.2 Integration tests

- FastAPI, Worker, Beat, PostgreSQL, and Redis in Docker Compose
- Stub Steam, YouTube, DeepSeek, and SMTP success/failure/timeout/rate-limit behavior
- Worker restart during Analysis and Match
- Match resume from checkpoint
- Database migration
- S3 upload and lifecycle-prefix assignment
- Backup and restore command
- OpenAPI schema generation and Swift client compilation

### 19.3 Real smoke test

1. Validate a Workspace Access Key.
2. Analyze one Steam game.
3. Analyze one YouTube Creator.
4. Browse, search, favorite, edit contact, and Re-analyze.
5. Seed a representative Creator set.
6. Run the three-stage Match.
7. Inspect Recommended/Other and Match Brief disclosure.
8. Send an Outreach email to a controlled company mailbox.
9. Confirm Accepted and Declined flows.
10. Verify Campaign statistics and duplicate-send protection.
11. Close the app during work and confirm cloud tasks continue.
12. Test offline/reconnection behavior.
13. Verify standard SwiftUI fallback on macOS 14.
14. Verify Apple-provided Liquid Glass behavior on macOS 26+.
15. Restore a database backup into an isolated test database.

## 20. Version 1 Acceptance Criteria

- The four Sidebar workspaces operate end-to-end.
- One hundred Creator Profiles can be seeded, analyzed, and automatically refreshed.
- Game and Creator Profile cards and detail sheets show real current data and English AI analysis.
- Duplicate Analyze submissions do not create duplicate Profiles or Jobs.
- Match screens all current, non-stale Creator Profiles in Library, selects no more than 30, deeply compares each selected Creator, and publishes only a complete final result.
- The client never displays an ordinal rank or numeric Match total.
- Individual and batch outreach work through the configured NetEase enterprise SMTP mailbox.
- Yes/No email actions require explicit confirmation and update Campaign statistics.
- Idempotency prevents accidental duplicate Match, Analyze, or Send operations.
- Failed tasks display a safe explanation and can retry from a sensible checkpoint.
- Automatic Creator and Game Re-analyze are mandatory and honor configured intervals.
- YouTube temporary artifacts expire within 30 days.
- One command updates the application on the existing EC2 server.
- Database backup and restore are proven before internal distribution.

## 21. External Technical References

- Apple Liquid Glass adoption: https://developer.apple.com/documentation/TechnologyOverviews/adopting-liquid-glass
- Apple Swift OpenAPI Generator: https://github.com/apple/swift-openapi-generator
- FastAPI OpenAPI support: https://fastapi.tiangolo.com/features/
- Celery periodic tasks: https://docs.celeryq.dev/en/latest/userguide/periodic-tasks.html
- DeepSeek models: https://api-docs.deepseek.com/
- DeepSeek Vision: https://api-docs.deepseek.com/guides/vision/
- YouTube Channels API: https://developers.google.com/youtube/v3/docs/channels
- YouTube Captions download authorization: https://developers.google.com/youtube/v3/docs/captions/download
- YouTube API developer policies: https://developers.google.com/youtube/terms/developer-policies
- YouTube derived metrics and storage: https://developers.google.com/youtube/terms/derived-metrics-policy
- Steamworks Web API overview: https://partner.steamgames.com/doc/webapi_overview
- Steam IStoreService: https://partner.steamgames.com/doc/webapi/IStoreService
- S3 lifecycle expiration: https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html
