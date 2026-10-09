# FMG CLI / Skills 0.7.3 — LIMINAL footer banner

- `liminal-outreach` v7 adds the approved LIMINAL: Within PNG below the existing Ontology Play signature logo. The original 800×210 image is preserved (309,405 bytes; SHA256 `659f2546794346a25e7d670db353e573bb88e62718a0a2a27d32edae5753b7bd`), displayed proportionally at up to 600px wide.
- Both images are embedded with distinct Content-IDs and frozen in each draft. SMTP and Microsoft Graph use the same MIME representation; no external image fetch is required. Plain-text fallback, all fixed prose, title and four personalization variables are unchanged.
- `game-outreach` remains v5 with only the existing signature logo. Old saved LIMINAL drafts keep their original single image; adding the banner requires a new preview/task and fresh send approval. No automatic resend or approval transfer.
- Updated both Skills' footer/version references. Agents fill only declared text variables; images are supplied by the server. Upgrade with `fmg upgrade --latest --skills`, then re-read both installed Skills and relevant references.
- No sender, OAuth, IMAP, recipient allowlist, send-rate or database-schema changes. Publication does not send mail or retry tasks. Existing CLI command syntax remains compatible.

## Publication acceptance — 2026-10-09

- Implementation `34d8fdf47dd201f1eb3f7aaa62a8cff9e72429d3` pushed to `cli`; `fmg-v0.7.3` published with four binary architectures, both Skills, installer, checksums and Agent guide.
- Service/installer suite: 223 passed, five environment-dependent checks skipped; the existing Starlette/anyio deprecation warning remains. New regressions verify both image CIDs/order and original banner bytes through real local SMTP, mocked Graph HTTP with real MIME, persisted drafts and old single-image compatibility. Go tests/vet and both Skill validators passed; independent retrieval confirmed current footer rules and approval boundaries.
- Production API/Worker use `fmg-agent:banner-34d8fdf` (image `9bdeed156486`), source `/opt/fmg-agent-banner-34d8fdf`. Backup: `/var/backups/find-me-gamer-agent/banner-34d8fdf-20261009`; prior `fmg-agent:formal-c4b0e1d` image/Compose checkout retained for rollback.
- Offline packaged-image rendering/MIME verification found both inline images with the exact original banner hash. Public HTTPS health and authenticated reads expose LIMINAL v7 and generic v5; fixed LIMINAL prose matched the approved block and generic definition remained unchanged. API healthy, Worker running, IMAP monitoring active without error.
- Before/after send counts remained 35 sent / 2 failed. No active enrichment or pending approved sends at activation; no production sends or task retries were issued. Existing private configuration and OAuth volumes retained.
- Freshly downloaded public assets passed every SHA256 check and four installer tests. Isolated installation and public update discovery recognize CLI and both Skills as version 0.7.3.
