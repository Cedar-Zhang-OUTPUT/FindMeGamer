# CLI 0.2.1 — pricing guidance and billing recovery

- Adds offline JSON `fmg pricing`, covering YouTube/Steam zero marginal API estimates, Gemini token/search estimates, provisional X pricing, excluded SMTP/hosting charges and recovery rules.
- Gemini estimation already shipped in 0.2.0. This patch labels its basis correctly as list price before discounts/free allowances, rather than X daily deduplication. No tariff or schema change; historical snapshots remain unchanged.
- Both Skills require pausing affected calls on explicit insufficient credits and asking the user to recharge. Rate limits, authentication and network errors are not automatically treated as insufficient funds. Partial work and identifiers are retained. No automatic recharge or mail resend.
- Existing 0.2.0 installs update with `fmg upgrade --latest --skills`; authentication is retained. Reload both installed Skills after upgrading.

Validation: CLI tests pass, service suite 113 passed / 3 optional integration tests skipped, both Skill validators pass. No paid calibration or real email sending is part of this release.

## Deployment

Deployed image `fmg-agent:0.2.1-3461e7f` from `/opt/fmg-agent-0.2.1-3461e7f`. API is healthy, Worker running, package version and corrected Gemini pricing basis verified inside the live image. Public HTTPS authentication works with the previous CLI. Backup: `/var/backups/find-me-gamer-agent/upgrade-0.2.1-3461e7f/agent-20260916T031324Z.dump`. No schema/tariff/key changes and no old macOS services restarted.

Published source and seven release assets at https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/fmg-v0.2.1 as an internal prerelease, without changing the legacy desktop latest designation.

Public upgrade acceptance: downloaded the actual 0.2.0 macOS arm64 release into an isolated directory and executed `upgrade --latest --skills`. The installed CLI reports 0.2.1, `pricing` returns service/recovery guidance, both downloaded Skills validate, and authentication configuration is byte-for-byte unchanged. No global user install was overwritten.
