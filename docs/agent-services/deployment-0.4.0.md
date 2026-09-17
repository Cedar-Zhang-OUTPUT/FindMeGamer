# CLI and gateway 0.4.0 — 2026-09-17

- Released source `d8aa1a0` on branch `cli`; GitHub release `fmg-v0.4.0`.
- Server image `fmg-agent:0.4.0-d8aa1a0`, checkout `/opt/fmg-agent-0.4.0-d8aa1a0`.
- Backed up before maintenance at `/var/backups/find-me-gamer-agent/upgrade-0.4.0-20260917T050819Z/`; database dump also copied to the existing S3 `backups/agent/` prefix. Private configuration and OAuth volume preserved.
- API healthy; Worker running; HTTPS health, authenticated CLI access and template catalog verified. Default template is version 2, HTML resource present in installed package; explicit version 1 remains available.
- Existing database counts retained: 38 completed / 27 failed enrichment jobs, two outreach tasks, two accepted sends. No outstanding recipients or in-flight sends at cutoff. Task rows retain dispatch state `sending`; their displayed completion is derived from recipient delivery states. Deployment checks pending recipients, not just the task dispatch flag.
- SMTP allowlist remains `yifan.zhang@byoutput.com`. No new mail was sent as part of deployment; the earlier authorized design test used inactive sample buttons. Real task emails retain recipient-specific confirmation links.
- Four binaries, Skills, installer and checksums uploaded, downloaded and checksum-verified. Downloaded bundle installation test passed; CLI reports 0.4.0. Go test/vet and CLI Python tests passed; backend regression: 136 passed, one optional test skipped.
- Includes immutable approved outreach, per-recipient response tracking, HTML/plain-text previews, read-only local creator/outreach dashboards, game/search-plan confirmation and browser checkpoints.
- Upgrade with `fmg upgrade --latest --skills`, then `fmg version`, `fmg auth check`, and reload both installed Skills. Existing local dashboard processes must be restarted to load updated HTML.
- Rollback image `fmg-agent:outreach-61c001b` remains available. Do not erase or restore databases during a routine image rollback.
