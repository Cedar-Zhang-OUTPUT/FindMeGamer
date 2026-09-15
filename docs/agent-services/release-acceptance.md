# FMG CLI 0.1.0 — pre-deployment acceptance

Date: 2026-09-15. Scope: company internal Demo. **Local development and release preparation complete; no production deployment, GitHub push/release publication or real external email in this stage.**

## Delivered

- Isolated authenticated API gateway; YouTube/X read catalogs and calls, Steam API and store search/recommendations. CLI preserves upstream result fields and exposes explicit pagination rather than silently fetching unlimited pages.
- Durable public business-email enrichment with saved successful checkpoints, asynchronous status and explicit retry. Company provider credentials remain on the server.
- Versioned fixed outreach template, preview, explicit recipient/content confirmation and idempotent sending. Unknown SMTP outcomes are not automatically resent.
- Per-token/per-run usage attribution, available numeric provider usage and dated YouTube quota estimates. Unavailable monetary prices/actual invoices and Codex/Work per-task usage stay unknown, not zero.
- Technical `fmg-api` and business `fmg-research` Skills; local evidence, Game Profile Markdown, JSON Match Briefs, stable identity index and resume/deduplication helper. Independent behavioral validation recorded in `skill-validation.md`.
- Four CLI archives, optional Skills bundle, checksum-verified installer/CLI upgrade, Docker image/Compose deployment tools, guarded maintenance deployment and rollback instructions. GitHub workflow creates a draft only when explicitly invoked later.

## Measured verification

| Check | Result |
|---|---|
| New-service Python suite with PostgreSQL, Redis, Worker, local SMTP and release image enabled | 108 passed; one third-party AnyIO/Starlette deprecation warning |
| Go CLI tests / vet | All 20 named tests passed; vet passed |
| Installer and actual release bundle acceptance | 2 passed; corrupt checksum preserves old binary; actual CLI plus both Skills install |
| Skill examples | CLI→loopback gateway operations/schema/pagination/Steam/usage/auth smoke passed; email E2E and workspace tests 4 passed |
| Skill metadata validators | Both valid |
| Independent reviews | Usage attribution, Skills behavior and release tools reviewed; two release P2 findings fixed and rechecked |
| Formatting / dependencies / shell | Black check 48 files, pip check, shell syntax and git whitespace checks passed |
| macOS arm64 | Actual installed CLI executed, reports 0.1.0 |
| Linux arm64 | Actual archived CLI executed inside network-disabled Linux container, reports 0.1.0 |
| macOS amd64 / Linux amd64 | Cross-compilation only; not runtime tested |

Built with Go 1.27.1. Service tested with Python 3.13.15/PostgreSQL 17. The local service image `fmg-agent:predeploy` was built from the new service only; legacy configuration is not copied into the image.

`tests/test_release_container.py` runs the actual image as a non-root user, applies migrations twice, performs real CLI auth/catalog/template checks against the same local API, and verifies a queued private-URL job reaches a safe local rejection without a paid upstream call. A PostgreSQL custom-format backup is restored in its own random test schema, preserving the token, email job and migration revision `0004_usage`. Generated test containers/schema are removed afterwards. This is not a production backup or public HTTPS test.

Release-test fixes: build metadata now sets `main.version`; macOS hidden metadata is excluded from archives; deployment smoke checks its CLI server matches the requested target before any network access.

## Local artifacts

Under repository worktree `dist/fmg-v0.1.0/` (ignored build output):

- `fmg_darwin_arm64.tar.gz`, `fmg_darwin_amd64.tar.gz`
- `fmg_linux_arm64.tar.gz`, `fmg_linux_amd64.tar.gz`
- `fmg-skills.tar.gz`, `install.py`, `SHA256SUMS`

These are local candidate artifacts, not published download URLs. `quickstart.md` documents offline installation and labels the future one-command public installer URL as unavailable until publication. No global Skill or user CLI installation was replaced during these tests.

## Explicitly remaining at rollout

1. Recheck EC2/old backup/network/PG version; create isolated new DB/role and protected service configuration. Transfer company keys without logging them. Confirm public HTTPS and access-token distribution.
2. Deploy in a maintenance window; keep old macOS services stopped. Verify new production auth, provider permissions and controlled real email enrichment. Existing previous provider smoke results are not substitutes for new deployment acceptance.
3. SMTP configuration plus an explicitly approved recipient are required before real delivery acceptance. Preview and local SMTP tests already pass. No automatic sending on install.
4. Push the intended source branch, upload candidate assets, download again and compare checksums; only then publish the actual installation command. GitHub download/upgrade network path has not been exercised against an unpublished release.

Not claimed: social platform writes, Instagram/Twitch live APIs, old Library/Match server models, reply ingestion or Yes/No callbacks, exact dollar costs without attributable prices, public notarization, or uninterrupted rolling upgrades.
