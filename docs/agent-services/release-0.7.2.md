# FMG CLI / Skills 0.7.2 — Formal outreach subjects

- Removed the `Internal Test — ` prefix from new `liminal-outreach` v6 and `game-outreach` v5 subjects. LIMINAL's title is now `Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG`; other games use `Thought you might enjoy ${game_name} — ${game_tagline}`.
- Both template bodies, declared variables, signature image and rendering format are unchanged. LIMINAL's approved game-description/demo/closing block remains verbatim; only its four creator-personalization variables are editable. Other games retain the generic template's ten variables.
- Updated both bundled Skills with the full formal subjects, current version baseline and explicit frozen-draft guidance. Fetch the current server template before creating new drafts. Old versions cannot generate new drafts; existing saved previews/tasks are not rewritten, resent or automatically reapproved. To change an old subject, create and review a new preview/task and obtain fresh send approval.
- CLI commands are unchanged. Upgrade the CLI and both Skills using `fmg upgrade --latest --skills`, then verify `fmg version` and re-read both installed Skills and current-stage references.
- No changes to database schema, sender, Graph/IMAP authorization, recipient allowlist, concurrency or send frequency. Deploying this version does not send emails or retry tasks.

Publication acceptance is recorded after full local tests, cloud health/template checks and verification of downloaded release assets.
