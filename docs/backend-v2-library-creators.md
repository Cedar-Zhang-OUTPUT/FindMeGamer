# Creator Library foundation — second backend unit

Status: second backend unit verified, 2026-09-08. Scope is
Library data, evidence and explicit identity correction, not discovery, campaign
management, AI outreach generation, SMTP or production rollout.

## Frontend contract

All routes use existing Workspace Bearer authentication and the existing safe
error envelope. OpenAPI is exported to `backend/openapi.json` before handoff.

| Method | `/api/v2/library/creators` suffix | Operation |
| --- | --- | --- |
| GET | none | List/search/filter |
| POST | none | Create platform account |
| GET | `/{creator_id}` | Shared detail |
| PATCH | `/{creator_id}` | Edit business fields/favorite |
| PUT | `/{creator_id}/identity` | Explicit confirmed rebind |
| POST | `/{creator_id}/contacts` | Add manual email |
| PATCH | `/{creator_id}/contacts/{contact_id}` | Edit/hide email |
| GET | `/{creator_id}/works` | Known structured works |
| POST | `/{creator_id}/works` | Add manual work/evidence note |
| PATCH | `/{creator_id}/works/{work_id}` | Edit work/evidence |

All POSTs require `Idempotency-Key`. Retrying identical input with the same key
replays the original 201 snapshot for 24 hours; different input returns 409.
PATCH requires `expected_revision`; contact writes use the Creator revision,
work edits use the work revision. Omitted fields stay unchanged, null clears
nullable fields, arrays replace the whole array. `reset_fields` resumes source
values; it cannot overlap explicitly set fields. A stale edit returns 409 rather
than silently overwriting a colleague's change.
Creating a work additionally requires `expected_identity_revision` from
`creator.source_identity.revision`; a stale page cannot attach the previous
account's evidence to a newly rebound account.

Create defaults `platform` to `youtube`; options are `youtube`, `x`, `twitch`,
`instagram`. Provide `account_id` or HTTP(S) `profile_url`; other data is optional.
YouTube IDs are channel IDs (not handles), X/Twitch IDs numeric, Instagram has
only a preset/manual record and no real adapter in this release. Saving never
starts a provider task. Same names on different platforms are separate Creators.

Editable fields: `name`, `public_name`, `public_name_confirmed`, `handle`,
`profile_url`, `avatar_url`, `description`, `follower_count` (nonnegative integer,
null unknown), `follower_count_collected_at` (timezone-aware timestamp),
`languages`, `country_code` (two uppercase letters or null), `country_name`,
`other_contacts` (`{label?, value, url?}`), `source_notes`, `internal_notes`,
`interest_notes`, `favorite`. Changing a public name clears its old confirmation
unless the same edit explicitly confirms the new name.

Detail adds `source_identity` (`platform`, `account_id`, `canonical_url`, identity
`revision`), `source_fields`, `manual_overrides`, `overridden_fields`, Creator
`revision`, contacts, current-identity `work_count`, analysis dates and
`analysis_available`. Manual/source layers are separate; these source fields are
not a claim that the user or sender personally watched any content.

List parameters: `query`, `platform`, `language`, `only_collection`, `limit`
(default 50, maximum 100), `offset` (default 0). Response `{items,total,limit,offset}`.
Query searches name, handle, identity, profile URL and currently known work names/
content titles. Unknown language/region is not silently inferred.

## Emails and works

Contact create requires `expected_revision` and `email`; optional `purpose`,
`source_url`, `is_active`, `verification_notes`. Contact PATCH supports these
fields plus reset. It returns updated Creator detail with its new revision.
Email format is validated; changing an email resets validation to `unverified`.
The client cannot claim a contact is automatically verified. Hide a contact with
`is_active=false` rather than deleting its provenance.

Contact detail includes stable UUID, `origin` (`manual` or `source`), source type,
source fields, manual overlays, validation state, identity revision and
`is_current_identity`. Multiple addresses and purposes remain independent. This
does not authorize sending to all addresses; existing send requests still select
one address explicitly. A source refresh updates source facts, not human edits;
missing source addresses become inactive instead of erasing their IDs/notes.

Works support `work_name`, `content_title`, `platform`, `content_type`,
`source_url`, `content_id`, `published_at`, `collected_at`, `metrics` (`{name,value}`),
`game_id`, `verification_notes`, `evidence_excerpt`, `timestamp_seconds`.
At least a work/content title or source URL is required. Dates are timezone-aware;
metrics/time offsets are finite and nonnegative. A linked `game_id` must exist.
Content type defaults `unverified`; options also include `gameplay`, `livestream`,
`review`, `commentary`, `trailer`, `news`, `other`.

Works retain origin, source fields, human fields, acquisition `source_platform`,
`source_content_id` and `source_collected_at`. Editing display platform/content ID
does not rewrite the acquisition identity. Manually entered records remain
manual even when they contain a URL or verification note. The system does not
convert a title match to “played this game,” or lack of evidence to “never played.”

The works list defaults to the current identity, paged with limit/offset. Set
`include_previous_identity=true` to read retained records from previous account
bindings; they are flagged `is_current_identity=false` and cannot be edited into
current evidence. Known records are not advertised as a complete platform history.

## Explicit identity correction

Ordinary profile/handle edits never change acquisition identity. Rebind requires
`PUT /{creator_id}/identity` with `expected_revision`, `confirmed:true`, `platform`,
and `account_id` or `profile_url`. The UI should show old/new identity and explain
that old evidence/contacts will no longer be current before confirming.

The same Creator UUID is retained. A small prior-identity binding record preserves
historical successful analysis validation; it is not a permanent Profile version
or raw-content archive. Identity revision advances. Previous contacts are retained
but deactivated, and old works remain in their previous identity revision. Source
facts/AI summaries/analysis schedule are cleared for the new binding; explicitly
entered manual profile fields, notes and favorite remain available for correction.
The previous homepage/handle overrides are cleared; the explicitly supplied new
homepage is used, otherwise the new canonical URL is shown. Public-name
confirmation is cleared. The legacy v1 contact editor cannot prove which identity
its page showed, so after rebind it returns 409 and directs users to the v2 editor.

If analysis is queued/running for either affected YouTube account, return
`creator_analysis_in_progress` (409) and retry after it finishes. Pending/sending
deliveries return `creator_delivery_in_progress`. This uses the existing shared
write lock; late work on a failed job cannot publish across a rebind. Uniqueness
conflicts return `creator_identity_conflict`; no cross-platform person merge occurs.

Sent snapshots and old response links stay unchanged. An old Match cannot use the
new identity's email: preview/send returns `creator_identity_changed` (409), and
the user needs a new Match for the corrected account. No new campaign feature or
automatic resend is introduced here.

Other errors: 401 `workspace_key_invalid`, 422 `request_invalid`, 404
`creator_not_found` / `creator_contact_not_found` / `creator_work_not_found`, 409
`creator_revision_conflict` / `work_revision_conflict` / `creator_contact_conflict`
/ `idempotency_key_conflict`.

## Migration, runtime and remaining units

Migration `0008 → 0009` preserves existing YouTube UUIDs and contacts, and imports
known representative video metadata as unverified structured works. New source
refreshes upsert known videos and contacts without replacing human overlays.
Legacy v1 Library/Match only include bound YouTube accounts; automatic scheduling
does not manufacture jobs for unbound or unimplemented platforms.

Downgrade refuses to discard new multi-platform/manual/evidence/identity-history
data; use a verified pre-migration backup when rollback requires removing it.
Production rollout permits a maintenance window and does not support mixed old/
new Worker operation. No production deployment is part of this unit.

The frontend's 18090 API stays on accepted `dd4b15d` from a detached stable snapshot
until a coordinated update. It must not be rebuilt from this unfinished checkout.

Cross-unit settings handoff: retain current provider status/replace/test APIs for
Steam/YouTube/DeepSeek/Google AI, independent Game 1–90 day and Creator 1–30 day
refresh cycles (no disable switch), shared configuration notices and no secret
readback. X/Twitch credential/test contracts come with their later adapters;
Instagram stays unavailable. S3 remains server-side instance-role configuration.
SMTP save/connection testing never implies permission to send; real test mail
requires an explicit recipient and authorization. No new settings/RBAC/services
are introduced in this Creator unit.

## Verification and handoff

Final isolated backend run: **1,903 passed**, with real Redis checks enabled and
no skips. The only warning is the existing Starlette/AnyIO deprecation. No paid
API, real provider, production database, SMTP recipient or real email was used.

```sh
docker compose -p fmg-v2-tests -f backend/compose.test.yaml up -d postgres-test redis-test
docker compose -p fmg-v2-tests -f backend/compose.test.yaml run --rm --no-deps -e REAL_REDIS_URL=redis://redis-test:6379/0 test pytest -q --tb=short
```

TDD covered creation/editing/duplicate identities, multiple contacts and provenance,
known works, successful/failed refresh, identity-scoped records, current-schema
migration and historical successful jobs after rebind. Independent limited review
found stale-page work attachment, legacy contact write boundaries and stale homepage
overrides; all were fixed with failing-then-passing regressions. The older single
manual-email/deleted-source-email assertions were updated to the explicitly changed
multi-email/non-destructive source policy; production validation was not weakened.

Existing v1 OpenAPI paths are unchanged. Creator features are not yet wired into
the new desktop client. The 18090 frontend stack deliberately remains the clean
`dd4b15d` Game v2 snapshot; coordinate its next rebuild after frontend validation.
This is a safe integration point for the coordinator to add the desktop-only
frontend commit, not a claim of full discovery/outreach delivery or production
deployment.
