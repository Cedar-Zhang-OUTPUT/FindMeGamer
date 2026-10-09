# FMG CLI / Skills 0.7.1 — Dedicated LIMINAL outreach template

- Added `liminal-outreach` v5 for the user-confirmed target LIMINAL: Within. Only `creator_name`, `channel_name`, `reference_work` and `specific_observation` are editable.
- The approved section from “I’m reaching out” through the signature is preserved verbatim, including Demo URL `https://store.steampowered.com/app/4952700/_/`, Dispatch/PARANORMASIGHT comparisons and demo access wording.
- Kept `game-outreach` v4 unchanged for other games. Select by the outreach target, not the creator's reference game. Both Skills include both full templates and their variable contracts.
- Both retain the Internal Test subject prefix, compact inline signature image and plain-text fallback. No Yes/No buttons. Legacy LIMINAL versions 1–4 stay retired; saved previews/tasks remain immutable and replacement drafts need fresh approval.
- CLI commands are unchanged. Upgrade CLI and bundled Skills with `fmg upgrade --latest --skills`, then verify the version and re-read both installed Skills and relevant references.
- No database schema, sender, OAuth, recipient allowlist or send-frequency changes. Publication does not send emails or retry existing tasks.

Local acceptance: service suite 210 passed, four environment-dependent checks skipped; existing Starlette/anyio deprecation warning remains. Go suite passed. Both Skills validate and independent retrieval scenarios distinguish target/reference games and preserve old approvals. Four architecture bundles built; isolated actual-bundle installation/update check and installer tests: four passed. Deployment/public downloads are checked separately during publication.
