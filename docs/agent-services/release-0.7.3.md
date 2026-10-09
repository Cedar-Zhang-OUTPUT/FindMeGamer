# FMG CLI / Skills 0.7.3 — LIMINAL footer banner

- `liminal-outreach` v7 adds the approved LIMINAL: Within PNG below the existing Ontology Play signature logo. The original 800×210 image is preserved (309,405 bytes; SHA256 `659f2546794346a25e7d670db353e573bb88e62718a0a2a27d32edae5753b7bd`), displayed proportionally at up to 600px wide.
- Both images are embedded with distinct Content-IDs and frozen in each draft. SMTP and Microsoft Graph use the same MIME representation; no external image fetch is required. Plain-text fallback, all fixed prose, title and four personalization variables are unchanged.
- `game-outreach` remains v5 with only the existing signature logo. Old saved LIMINAL drafts keep their original single image; adding the banner requires a new preview/task and fresh send approval. No automatic resend or approval transfer.
- Updated both Skills' footer/version references. Agents fill only declared text variables; images are supplied by the server. Upgrade with `fmg upgrade --latest --skills`, then re-read both installed Skills and relevant references.
- No sender, OAuth, IMAP, recipient allowlist, send-rate or database-schema changes. Publication does not send mail or retry tasks. Existing CLI command syntax remains compatible.

Publication acceptance is recorded after local tests, server health/template checks and public release-asset installation checks.
