# CLI 0.2.0 — cost visibility and automated updates

## Scope

- Persist per-request estimated USD snapshots (migration `0005_cost`); provider envelopes expose `meta.cost`, Gemini successful checkpoints expose `cost`, and `/v1/usage` aggregates the known subtotal without hiding unknown components. Older ledger rows remain unpriced; no retrospective invented bill.
- X estimate counts primary and expanded identifiable resources at dated list prices. It precedes daily UTC deduplication, free allowances and discounts, so it is not actual billing. Unmapped operations/counts remain explicit unknowns.
- Gemini 3.8/3.7 Flash uses reported input, cached input, output plus thinking, and observable Google Search queries. Promotional rates until 2026-12-31 and announced 2027 rates are dated in code. Unreported tool usage stays excluded/unknown. No model calls are made solely for cost estimation.
- YouTube and Steam have zero marginal API charge under the current gateway assumptions; quota remains separately reported. Hosting, subscriptions and SMTP per-message prices are excluded, not invented.
- `fmg upgrade --latest --skills` installs the matching CLI/Skills with SHA256 checks, preserving auth and numbered Skill backups. `--tag` pins a release; `--skill-dir` preserves custom destinations. Python 3.10+ is required for combined upgrade. CLI 0.1.0 bootstraps using the 0.2.0 installer.
- Both Skills now explicitly collect available host `get_usage_limits` snapshots before and after metered work. Report account remaining and comparable percentage-point change separately from precise task usage. Reset/identity change/missing tool is explained, never fabricated.

Sources verified 2026-09-15: [X](https://docs.x.com/x-api/getting-started/pricing), [Gemini](https://ai.google.dev/gemini-api/docs/pricing), [YouTube quota](https://developers.google.com/youtube/v3/determine_quota_cost). Costs are estimates, not invoices; the tariff is a versioned source change, not live-scraped per request.

## Validation

The user's previous external-environment run supplies the behavioral regression: monetary cost was always unknown and the available host usage tool was not used. New instructions provide explicit begin/end steps and required accounting slots, not a prohibition on all shared-account reporting.

Independent review exercised the pricing/usage/installer tests, real PostgreSQL migration, Go suite, and Skill scenarios (available host tool, missing tool, reset window, partial Gemini pricing). No blockers found. Initial new pricing tests failed on missing cost output/estimator/grounding counts; new installer/Go tests failed on missing latest-selector/combined update and blocked repeated Skill backups before implementation.

Deployment and public-download acceptance results are recorded below once performed.
