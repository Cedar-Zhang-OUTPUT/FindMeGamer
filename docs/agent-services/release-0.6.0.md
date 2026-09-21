# FMG CLI / Skills 0.6.0 — Unified outreach template

- One active template: `game-outreach` v4, based on the approved outreach copy and signature, with target-game title, tagline, description, gameplay, availability and URL supplied as variables.
- `liminal-outreach` and game-outreach v3 are no longer accepted for new previews. Existing immutable previews, tasks and receipts remain unchanged; do not recreate or resend them automatically.
- `specific_observation` is a complete, evidence-backed game-connection passage, not a clause after a fixed opening. The fixed wording now says “enjoyed your content”.
- New 15,255-byte inline signature image replaces the 41,280-byte asset. No remote image fetch, Yes/No buttons or new tracking links.
- Both Skills include the complete template, variable contracts and whole-email review guidance. Fixed PR copy and sender signature are not Agent-editable.
- Upgrade with `fmg upgrade --latest --skills`, reload both Skills, then inspect `fmg email template game-outreach` before preparing new drafts. Fetch the returned version rather than reusing old JSON. Changed drafts require fresh approval.
- No SMTP credentials, recipient allowlist or database schema changes. Publishing does not send mail.

Local validation: service suite with isolated PostgreSQL/CLI/Worker/local SMTP: 153 passed, 1 optional container test skipped. Go CLI suite passed; both Skills validate. Deployment and release artifact checks are performed separately during publication.
