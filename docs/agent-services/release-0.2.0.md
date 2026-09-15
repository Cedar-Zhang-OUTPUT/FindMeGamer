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

## Deployment verification

Backend deployed at `/opt/fmg-agent-0.2.0-b97f52b`, image `fmg-agent:0.2.0-b97f52b`; package reports 0.2.0 and database revision is `0005_cost`. API is healthy and Worker is running. All 69 existing ledger rows remain present and unpriced. Maintenance backup: `/var/backups/find-me-gamer-agent/upgrade-0.2.0-b97f52b/agent-20260915T101626Z.dump`; subsequent scheduled-backup service invocation completed successfully (local plus S3).

116 service tests passed across the full image-enabled suite (115 plus separately enabled compiled-CLI/email E2E). Real PostgreSQL old-schema migration preserves an existing usage record with null price. Four installer/bundle tests, Go tests/vet, CLI HTTP smoke, and both Skill metadata validators passed. The existing third-party AnyIO deprecation warning remains nonblocking.

Public HTTPS smoke run `release-020-smoke`: X user lookup returned an estimated USD 0.010; Steam Store search returned USD 0 marginal API charge. The authoritative run total was USD 0.010 for two successful requests with no unknown components. This is an estimate before discounts/deduplication, not observed billing. No real email sent and no additional Gemini invocation made for this deployment.

## Public upgrade acceptance

Published [fmg-v0.2.0](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/fmg-v0.2.0), source tag `b97f52b`, with four platform archives, Skills, installer, SHA256SUMS and Agent guide. This remains an internal prerelease and does not change the legacy desktop latest designation.

Downloaded the public installer/checksums anonymously. In an isolated directory containing the actual released 0.1.0 binary/Skills and a copied private configuration, verified the installer checksum and bootstrapped 0.2.0. Then the freshly installed binary executed `upgrade --latest --skills` against real GitHub release metadata/assets. Both replacements succeeded, CLI version remained 0.2.0, numbered Skill backups were retained, configuration bytes were unchanged, and production `auth check` succeeded. No global installation or user Skill edits were overwritten by these checks.

Host quota was checked during development: account/window changed from the initial snapshot, so whole-task quota attribution is unavailable. Two comparable later snapshots showed shared-account usage 33% then 34% (remaining 67% then 66%), not a precise task charge. No reset credit was consumed.
