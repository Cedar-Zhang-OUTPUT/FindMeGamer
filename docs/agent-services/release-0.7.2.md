# FMG CLI / Skills 0.7.2 — Formal outreach subjects

- Removed the `Internal Test — ` prefix from new `liminal-outreach` v6 and `game-outreach` v5 subjects. LIMINAL's title is now `Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG`; other games use `Thought you might enjoy ${game_name} — ${game_tagline}`.
- Both template bodies, declared variables, signature image and rendering format are unchanged. LIMINAL's approved game-description/demo/closing block remains verbatim; only its four creator-personalization variables are editable. Other games retain the generic template's ten variables.
- Updated both bundled Skills with the full formal subjects, current version baseline and explicit frozen-draft guidance. Fetch the current server template before creating new drafts. Old versions cannot generate new drafts; existing saved previews/tasks are not rewritten, resent or automatically reapproved. To change an old subject, create and review a new preview/task and obtain fresh send approval.
- CLI commands are unchanged. Upgrade the CLI and both Skills using `fmg upgrade --latest --skills`, then verify `fmg version` and re-read both installed Skills and current-stage references.
- No changes to database schema, sender, Graph/IMAP authorization, recipient allowlist, concurrency or send frequency. Deploying this version does not send emails or retry tasks.

## Publication acceptance — 2026-10-09

- Source `c4b0e1de5a10137b30240ec09c455f8e1d61b14a` pushed to `cli`; `fmg-v0.7.2` published with four architecture binaries, both Skills, installer, checksums and Agent guide.
- Service/installer suite: 218 passed, five environment-dependent tests skipped. Actual release-bundle acceptance: four passed, both before publication and using freshly downloaded public assets. Go tests/vet and both Skill validators passed. The existing Starlette/anyio deprecation warning remains.
- Production API/Worker use `fmg-agent:formal-c4b0e1d` (image `31cd88251639`), source `/opt/fmg-agent-formal-c4b0e1d`. Backup: `/var/backups/find-me-gamer-agent/formal-c4b0e1d-20261009`. Previous image `fmg-agent:liminal-0c3bc06` and its Compose checkout remain available for rollback.
- Public HTTPS health and authenticated template reads passed: LIMINAL v6 and generic v5 expose the formal subjects. Both bodies and schemas matched local verified definitions; LIMINAL's fixed block matched the approved full text exactly. API healthy, Worker running, IMAP monitoring active without error.
- Send counts before/after remained 34 sent / 2 failed. No active enrichment or approved pending sends at activation. No mail sends or task retries were issued; sender, authorization, allowlist and frequency configuration were retained.
- Downloaded public assets passed all SHA256 checks. Isolated installation succeeded; public update discovery recognizes CLI and both Skills as version 0.7.2.
