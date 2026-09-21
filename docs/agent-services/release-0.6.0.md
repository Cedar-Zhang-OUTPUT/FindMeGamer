# FMG CLI / Skills 0.6.0 — Unified outreach template

- One active template: `game-outreach` v4, based on the approved outreach copy and signature, with target-game title, tagline, description, gameplay, availability and URL supplied as variables.
- `liminal-outreach` and game-outreach v3 are no longer accepted for new previews. Existing immutable previews, tasks and receipts remain unchanged; do not recreate or resend them automatically.
- `specific_observation` is a complete, evidence-backed game-connection passage, not a clause after a fixed opening. The fixed wording now says “enjoyed your content”.
- New 15,255-byte inline signature image replaces the 41,280-byte asset. No remote image fetch, Yes/No buttons or new tracking links.
- Both Skills include the complete template, variable contracts and whole-email review guidance. Fixed PR copy and sender signature are not Agent-editable.
- Upgrade with `fmg upgrade --latest --skills`, reload both Skills, then inspect `fmg email template game-outreach` before preparing new drafts. Fetch the returned version rather than reusing old JSON. Changed drafts require fresh approval.
- No SMTP credentials, recipient allowlist or database schema changes. Publishing does not send mail.

Local validation: service suite with isolated PostgreSQL/CLI/Worker/local SMTP: 153 passed, 1 optional container test skipped. Go CLI suite passed; both Skills validate. Deployment and release artifact checks are performed separately during publication.

## Publication acceptance — 2026-09-21

- Source pushed to `cli`; release `fmg-v0.6.0` published as an internal prerelease with four platform archives, both Skills, installer, checksums and Agent installation guide.
- Actual release-image migration/worker/backup-restore test passed after correcting its stale expected schema from 0006 to the existing 0007 inbox schema. No production migration was needed.
- Database backup: `/var/backups/find-me-gamer-agent/agent-20260921T132412Z.dump`, also copied to the configured dedicated S3 backup prefix.
- Production checkout `/opt/fmg-agent-unified-e6bf422`, image `fmg-agent:unified-e6bf422`. Previous image `fmg-agent:batchpatch-a167268` remains available for rollback using its previous Compose checkout and protected env files.
- API and Worker replaced after verifying no active enrichment or pending sends. Public HTTPS health, authenticated CLI access and the single game-outreach v4 catalog passed. IMAP poll succeeded with no error.
- Counts before/after remained: 260 enrichment jobs (211 completed, 49 failed), 40 previews, 5 outreach tasks, 39 recipients, 21 sent messages and 1 recorded reply. No real email was sent by this deployment.
- Downloaded GitHub assets matched all SHA256 entries; isolated installation reported CLI 0.6.0. Actual installer/bundle tests: 4 passed.
