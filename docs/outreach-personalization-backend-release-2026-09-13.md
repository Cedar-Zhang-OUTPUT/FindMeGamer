# Outreach personalization backend release — 2026-09-13

## Delivered backend

- Commit: `14d0a6ca60f8fbe03647136a61e64c0cf1cd76ff`.
- Server: `44.233.174.193`; previous backend `991a8efbc21a1203fe1ec4c131bdac6dc7bba862`.
- Database: `20260910_0022` → `20260913_0023`.
- API, Worker, Beat, Proxy, PostgreSQL and Redis passed healthy checks after restart.
- HTTPS readiness returned `{"status":"ok"}`.
- Authenticated public GET-only smoke read 1 Game, 38 Creators, 1 Activity,
  3 compositions and all 46 existing drafts. No smoke writes or actual emails.

Draft-local overrides and safe partial saving/preview are separate from strict
generation and sending checks. Refresh preserves saved overrides; changed sources
still require explicit refresh. See [API contract](backend-v2-outreach-drafts.md).
This backend contract was coordinated with the internal.11 desktop release, not
treated as compatible with every earlier exact-decoding client.

## Tests and independent review

- Expanded analysis unit tests plus related outreach integration/unit regression:
  **486 passed, 1 skipped**.
- Current-version populated migration, earlier outreach migrations, Creator Library,
  preparation, publication and evidence DTO regression: **83 passed**.
- Final populated migration / normal JSON-null draft value / successful checkpoint
  description backfill checks: **7 passed** (overlaps earlier suites).
- New partial-edit and fact-invalidation cases first failed against the old code;
  implementation made them pass. No claim of an additional complete backend suite.
- One bounded independent read-only review: no blockers. It specifically required
  the new desktop decoder and real IPC acceptance before release.
- Frontend reported real internal.11 `.app` against isolated PostgreSQL/API/IPC
  acceptance, then repeated from the mounted DMG. Covered different-source edits,
  refresh preserving all four overrides, partial save/reopen, unchanged shared
  Creator/siblings, and blocked qualification. No send or sender-facts POST.

## Maintenance, backup and preservation

No active business work or active/reserved/scheduled Worker tasks were found before
deployment. Checks repeated after image build and after ingress/scheduler shutdown,
before stopping the idle Worker. No existing Analyze or Match task was retried.

S3 pre-migration backup:

```text
s3://zhangyue-data-493392056671-us-west-2/backups/20260913T075435Z-14d0a6ca60f8-pre-migration.dump
```

The filename uses the checked-out new commit; the contained database is the
pre-migration **0022** database. The uploaded dump and its SHA256 file were downloaded
again; checksum validation and `pg_restore --list` succeeded. **A complete restore
was not executed or claimed.** No additional restore exercise was required.

Protected server evidence directory:

```text
/var/backups/find-me-gamer/20260913-outreach-14d0a6c
```

This root-only directory contains deployment guards, before/after fingerprints,
backup URI/dump/checksum/table-of-contents, backfill reports and protected config
backup. Config `app.env` and `master.key` checksums remained unchanged.

All **43 non-Alembic tables** matched preservation fingerprints before and after.
The comparison excludes only the authorized additions to `draft.manual_overrides`,
`work.source_fields.outreach_observation`, and work `updated_at` changed by that
source-only update. All other data, including existing values, human layers,
Profiles, contacts, recipient snapshots, historical records and service settings,
was included. Alembic version changed as expected.

## Stored-fact backfill results

The no-network backfill ran dry-run → apply → repeat dry-run while services were
quiescent:

- 33 already successfully analyzed current YouTube Creators scanned.
- 1,595 works received source-only metadata suggestions.
- 1,284 suggestions reused descriptions in the matching successful source checkpoint;
  the remaining 311 used retained titles.
- Repeat dry-run: 0 works to update; idempotency confirmed.
- No new `evidence_excerpt` or `verification_notes` viewing evidence was manufactured.
- No provider/model call, paid reanalysis or email sending was triggered by backfill.

There are still **38 total Creator records**, not 55 Creators. The preflight's
33 succeeded + 22 failed Analysis Job rows are cumulative task history, not the
number of current successful/failed Creator Profiles.

All 46 old draft snapshots remain unchanged and currently report `source_changed`.
A read-only calculation of their current input found four nonempty suggested slots
for each; all 46 chosen work evidence kinds are **metadata**. Descriptions, titles
and these suggestions are not proof that a human watched or enjoyed a video.
Actual applicable evidence, human confirmations, recipient and SMTP are still
required for sending. Actual Activity deliveries remained zero.

## How colleagues load prefills into existing drafts

In internal.11:

1. **Match** → corresponding Activity → **History & saved lists** → **Draft history**
   → **Open draft set**.
2. Select the recipient in **Draft people**.
3. Click **Refresh sources**, then **Refresh and keep overrides**.
4. Use **Edit personalization**, review or adjust values, then **Save changes**.
5. **Review sending** is a separate eligibility check, not a consequence of saving.

Refresh preserves **saved** overrides, discards **unsaved** edits and clears sender
confirmations. The UI warns that refresh may use model quota when generation is
eligible; this release's backfill itself incurred no model calls. Existing drafts
were not silently overwritten or automatically sent. Missing genuine viewing
evidence is not bypassed by the new metadata prefills.

## Local acceptance fixture

The synthetic API at `127.0.0.1:18743` and its independent database were retained
for desktop acceptance; they contain no production service keys. Only the designated
draft PATCH, its refresh POST, and the composition qualification POST were allowed;
all other writes were denied, task dispatch was stubbed and no Worker was running.
Its target may retain the test's manual overrides and empty observation. Do not
interpret this local fixture as production state or reset the cloud Library.

Root coordinator owns the integrated desktop source and GitHub package release.
