# Native 0.4.1: Discover progress and Library refresh

## Scope and root cause

The user reported stale Discover analysis counts, duplicate Add Analysis eligibility after returning to a record, and an empty Creator Library despite successful analysis. The follow-up requirement was to support 1,000+ creators without a full-catalog response or eager rendering.

The client discarded batch items' analysis job IDs, did not forward job changes to Discover, and did not wake the idle job poller after asynchronous batch submission. Library could retain its initial empty cache on navigation. Add Analysis checked count rather than existing/running eligibility. Backend batch counters can lag while the shared worker queue processes analysis.

Application source/tag: `8167879`, `v0.4.1-internal.1`. A test-only follow-up, `1754952`, adds the 1,025-creator pagination fixture. Full source is on `codex/native-profile-editing`; no unrelated branch was merged.

## Changes

- Preserve `analysis_job_id`, project job events into nonterminal batch items, and retain terminal server item precedence. Wake polling after submission and when active batches are read.
- Disable Add Analysis if any selected candidate is already in Library or analyzing, including reopening and mixed selections. Loading batch eligibility must complete before submission is enabled.
- Reload Library's first page when entering it. Existing cursor pagination remains 50 items per request, with server-side search/favorites and lazy grid rendering. No production pagination rewrite was needed.

## Verification

- Eligibility tests first failed against the previous implementation, then passed with the fix.
- Independent scoped review reported no release-blocking findings.
- Final full Swift suite: **363 tests / 55 suites passed**, 6.567 seconds.
- Library targeted suite: **33 tests passed**. The 1,025-item fixture verifies first load 50, next load 100, 21 explicitly requested pages to exhaustion, ordered IDs without loss, and no further requests at the end. This is an isolated fixture, not seeded production data.
- Authenticated production cursor reads with `limit=1` returned one distinct creator per request. Live Swift transport decoding/progress integration passed (one test, 8.952 seconds). No paid provider calls or job submission occurred in these checks.
- Manifest regression and release-script contract tests passed.
- Universal ad-hoc DMG build and verifier passed checksum, bundle/signature validation and read-only mount. Artifact inspected as version 0.4.1, `x86_64 arm64`.
- Actual mounted DMG app launched using existing local credentials. Library displayed **35 creators**. The user's 40-person batch displayed **35 succeeded / 5 failed**, not stale zero counts. Selecting all showed Add Analysis disabled; the local selection was then cleared. No analysis retry, matching or email was submitted.

## Publication

GitHub prerelease published at `2026-09-14T15:08:01Z`, `draft=false`:

- [Release](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.4.1-internal.1)
- [DMG](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/v0.4.1-internal.1/FindMeGamer-0.4.1.dmg)
- [Source](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/tree/v0.4.1-internal.1)

DMG size **17,313,487 bytes**; SHA-256 `8b43a3fd7f094d86853a141cbd610f5cd15a5e15ebe120df197d6dea8a55bb2a`. Draft assets were downloaded, checksum-verified and byte-compared before publication. Not Developer ID signed or Apple-notarized; physical Intel/macOS 14 testing is not claimed.

After publication, only the 0.4.1 update manifest was hot-loaded through Caddy stdin and persisted to `/opt/find-me-gamer/Caddyfile` and `/opt/find-me-gamer-native-040-platform20/Caddyfile`. Previous manifest configuration is retained as `/opt/find-me-gamer/Caddyfile.pre-041`. Both old files were hash-checked before promotion.

Public readiness returned `ok`. The actual URLSession update-check test passed (one test, 10.519 seconds): older clients receive 0.4.1, and 0.4.1 is current.

API, Worker, Beat and Proxy container IDs and start times stayed identical. Current backend remains `find-me-gamer-native:0.4.0-cec8ea9`; no database, analysis data, credentials or worker configuration was changed. The five failed creators were not retried by this release.

Local detailed logs: `/tmp/fmg-041-{build,verify,full-final,pagination,live-update,feed-promotion}.log`, `/tmp/fmg-041-published.json`.
