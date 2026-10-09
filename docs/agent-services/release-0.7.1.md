# FMG CLI / Skills 0.7.1 — Dedicated LIMINAL outreach template

- Added `liminal-outreach` v5 for the user-confirmed target LIMINAL: Within. Only `creator_name`, `channel_name`, `reference_work` and `specific_observation` are editable.
- The approved section from “I’m reaching out” through the signature is preserved verbatim, including Demo URL `https://store.steampowered.com/app/4952700/_/`, Dispatch/PARANORMASIGHT comparisons and demo access wording.
- Kept `game-outreach` v4 unchanged for other games. Select by the outreach target, not the creator's reference game. Both Skills include both full templates and their variable contracts.
- Both retain the Internal Test subject prefix, compact inline signature image and plain-text fallback. No Yes/No buttons. Legacy LIMINAL versions 1–4 stay retired; saved previews/tasks remain immutable and replacement drafts need fresh approval.
- CLI commands are unchanged. Upgrade CLI and bundled Skills with `fmg upgrade --latest --skills`, then verify the version and re-read both installed Skills and relevant references.
- No database schema, sender, OAuth, recipient allowlist or send-frequency changes. Publication does not send emails or retry existing tasks.

Local acceptance: service suite 210 passed, four environment-dependent checks skipped; existing Starlette/anyio deprecation warning remains. Go suite passed. Both Skills validate and independent retrieval scenarios distinguish target/reference games and preserve old approvals. Four architecture bundles built; isolated actual-bundle installation/update check and installer tests: four passed. Deployment/public downloads are checked separately during publication.

## Publication acceptance — 2026-10-09

- Source `0c3bc06083b5e9bd3db7f378cc9fc8599bce8433` pushed to `cli`; prerelease `fmg-v0.7.1` published with four binaries, Skills, installer, checksums and Agent guide.
- Production API/Worker use `fmg-agent:liminal-0c3bc06` (image `8451e129dd83`), source `/opt/fmg-agent-liminal-0c3bc06`. Backup: `/var/backups/find-me-gamer-agent/liminal-0c3bc06-20261009`. Previous image `fmg-agent:graph-4271e39` and its Compose checkout remain available for rollback.
- Public HTTPS health and authenticated template reads passed. LIMINAL's fixed block matched the approved full text exactly; the generic template definition was identical to v4. API healthy, Worker running, IMAP monitoring active without error.
- Send counts before/after remained 33 sent / 2 failed. No active enrichment or approved pending sends at activation; deployment issued no mail sends. Sender, Graph/IMAP authorization and unrestricted-recipient configuration were retained.
- Downloaded public assets passed every SHA256 check. Actual downloaded-bundle installer/update acceptance: four passed.
