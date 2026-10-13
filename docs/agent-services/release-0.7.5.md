# FMG CLI / Skills 0.7.5 — delivery-only outreach dashboard

- Removed the Reply column, human/automatic reply filters, reply statistics/rate and reply-body viewer from the bundled read-only outreach dashboard. The three table columns are recipient, sending and draft.
- Preserved provider acceptance, failed/unknown delivery, bounces, queued/sending retries, draft preview/search/pagination, mailbox-monitor health and sender holds. The local dashboard's read-only Python bridge projects delivery data without exposing reply bodies or reply statistics to browser JavaScript.
- Both Skills distinguish the delivery-only presentation from preserved server-side IMAP reply correlation/records and automatic bounce pauses. Explicit reply investigations still use full task queries; legacy CLI/API response contracts remain unchanged.
- No cloud API/worker code change, database migration, transport/template edit, sender-hold release, task approval or production test email is required. API and worker remain on the verified existing image; release deployment consists of publishing the matching four-platform CLI/Skill bundle and setup guide.

Upgrade with `fmg upgrade --latest --skills`, verify `fmg version`, then re-read both installed Skills and outreach references. Stop/relaunch only the local dashboard with the same task ID to load its new page; do not recreate or restart an email task for a UI upgrade.

## Verification

- Two regression tests failed against the old dashboard: reply bodies reached the browser and the extra Reply table column was present. Both pass with the new projection and table.
- Skill scenario testing first reproduced instructions promising reply UI, then verified delivery-only guidance, continued monitoring/bounce safety and explicit CLI reply investigation with the updated references.
- Full backend suite: 303 passed, one opt-in Docker test skipped because local Docker remains stopped. Real isolated PostgreSQL/Redis, CLI/worker restart, reply correlation, bounce safety, pacing, invalid-recipient exclusion and unknown-delivery tests included. One existing Starlette/AnyIO deprecation warning remains. The first full run was blocked by the test PostgreSQL process using its default port instead of the isolated 55439; after correcting that local startup, both full runs passed (301 before the malformed-response regressions; 303 afterward).
- Four-platform build, Go tests/vet, four installer/bundle tests, both Skill validators, Black and diff checks passed. Review reproduced malformed CLI payloads disconnecting the dashboard; two added regression cases now verify the existing HTTP 503 response instead. No review findings remain.
- Real browser QA used the Playwright CLI because no Browser plugin/skill was available: 1440×1000 desktop and 390×844 mobile, page identity/nonblank/no overlay, zero console warnings/errors, exact three-column table, reply-body omission, unchanged draft modal, 20/5 pagination, search, bounced/retrying/issues filters, sender hold and monitor status. Mobile keeps the table horizontally scrollable without whole-page overflow. Screenshots are retained outside the repository in `/tmp/fmg-delivery-qa-Vrt7B8/`.
- Before publication, live API and worker retained their original container IDs/images, confirming no restart. Sender status remained ready, with no active initial sends/retries at inspection. Publication does not approve tasks, release holds or send mail.

## Public release acceptance — 2026-10-13

- Published `fmg-v0.7.5` from commit `133529a713399ff652bbc51a9c725acb9c8600ae`. All seven uploaded files were downloaded again; SHA256 verification and four installer/bundle tests passed on those downloaded assets. Anonymous server-side downloads independently verified all four platform archives, the Skill bundle and installer.
- A separate real 0.7.4 installation ran `fmg upgrade --latest --skills` successfully against the public release. The downloaded CLI reports 0.7.5, authentication still works, both installed Skill markers report 0.7.5, and `fmg update check --refresh` reports `current` with latest 0.7.5.
- The newly downloaded dashboard/CLI successfully queried an existing 50-recipient production task through the real HTTPS gateway. Browser data contains no `reply_state`, reply bodies or reply statistics; drafts, bounce/retry data, sender safety and active monitoring remain available. The acceptance helper made no sending requests.
- Isolated PostgreSQL/Redis and the fixture dashboard/browser were stopped after validation. Local Docker remained stopped. No production task was approved/resumed, no sender hold was released and no production test mail was sent for this release.
