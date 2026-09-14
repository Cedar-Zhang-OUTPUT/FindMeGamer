# Native 0.4.4 — Four results per page

User reports twenty detailed Match cards remain too heavy. Reduce the render page size to four, preserving existing numbered navigation, backend result ordering, group boundaries and cross-page selection. Library pagination is unchanged. This is a targeted rendering reduction, not a claim that all possible performance issues are resolved. Backend response remains unchanged; no data or analysis modifications.

Regression fixtures updated before implementation and observed failing against twenty-row behavior. Tests cover 1,200 candidates, mixed groups, partial last page, clamping and eligible selections across pages.

Internal universal macOS 14+ app, ad-hoc signed and not notarized. Default server https://44.233.174.193.

## Release evidence

- Full serial Swift suite: 369 tests / 55 suites passed. The first parallel run had two unrelated async-gate timeouts in Settings/Outreach; serial replay passed without code changes there.
- Source `4ab00a7` pushed; prerelease `v0.4.4-internal.1` published at `2026-09-14T17:02:39Z`, draft=false. SHA-256 `045cbab760dac32291e914646636a3beb5ae9b5053ec34178b09ae265263bee9`, 17,474,683 bytes. Uploaded assets downloaded and byte-compared.
- Real mounted release app showed `1–4 of 26`, seven pages, then `5–8 of 26` after Next. No business writes or task retries. Startup initially showed a fetch failure; opening the result succeeded. This release does not claim to resolve network latency.
- Signature, both architecture slices, checksum and DMG verification passed. Concurrent verification/UI mount attempts conflicted; sequential mount retry passed. Only the verification app process was closed.
- Update feed hot-reloaded to 0.4.4. Logs `/tmp/fmg-044-{red,full,full-serial,build,verify-retry,manifest,feed}.log` and `/tmp/fmg-044-published.json`.
