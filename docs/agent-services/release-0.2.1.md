# CLI 0.2.1 — pricing guidance and billing recovery

- Adds offline JSON `fmg pricing`, covering YouTube/Steam zero marginal API estimates, Gemini token/search estimates, provisional X pricing, excluded SMTP/hosting charges and recovery rules.
- Gemini estimation already shipped in 0.2.0. This patch labels its basis correctly as list price before discounts/free allowances, rather than X daily deduplication. No tariff or schema change; historical snapshots remain unchanged.
- Both Skills require pausing affected calls on explicit insufficient credits and asking the user to recharge. Rate limits, authentication and network errors are not automatically treated as insufficient funds. Partial work and identifiers are retained. No automatic recharge or mail resend.
- Existing 0.2.0 installs update with `fmg upgrade --latest --skills`; authentication is retained. Reload both installed Skills after upgrading.

Validation: CLI tests pass, service suite 113 passed / 3 optional integration tests skipped, both Skill validators pass. No paid calibration or real email sending is part of this release.
