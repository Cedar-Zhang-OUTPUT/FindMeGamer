# Native 0.4.3 — Match Result pagination

Match Result now renders at most 20 Creator rows per page. Previous, Next and a numbered page picker stay below the scrolling content. Recommended and Other matches retain backend ordering; a page containing only Other matches displays them directly. Page changes replace the scroll subtree, releasing off-page row views and resetting the page's scroll position. Selection lives outside that subtree and remains available across pages for the existing outreach flow. Select page selects eligible recipients on the current page; Clear selection clears all pages.

The client slices the result before building expensive row/brief presentations. This is client-side rendering pagination: the existing backend result API and in-memory decoded result are unchanged, not a claim of server-paginated payloads. No backend deployment, analysis, retries, profile changes or email sends are required.

Verification: first ran a failing 1,200-result test (old implementation constructed 1,200 rather than 20 presentations), then passed the full Swift suite: 369 tests / 55 suites. Regression coverage includes crossing the Recommended/Other boundary, last page, page return, result shrink, empty result and cross-page recipient selection. Bounded independent review found no blockers.

Distribution: universal native macOS 14+ app, default service https://44.233.174.193. Internal ad-hoc signature, not Apple-notarized. The update feed is promoted only after verified GitHub assets are published.

## Published verification

- Source commit `882719d`, GitHub prerelease `v0.4.3-internal.1`, published `2026-09-14T16:50:59Z` (September 15 Shanghai time), `isDraft=false`.
- DMG 17,474,726 bytes; SHA-256 `ae5969a53d04d275a128b37614733737d7b5edf044b3b30fc470bf77c93e3dde`. Uploaded assets downloaded and byte-compared before publication; GitHub asset digest agrees.
- Bundle version 0.4.3, both `x86_64 arm64` slices, signature, read-only DMG mount and checksum verified. Packaging contract tests passed. Physical Intel/macOS 14 execution and notarization are not claimed.
- Launched the mounted release app and used native accessibility controls against the existing 26-person result: first page showed 1–20, Next showed 21–26 with Previous enabled and Next disabled. Returning retained the first-page selection. Cleared that local test selection; no compose/send/retry/analysis action was invoked. Closed only the mounted verification process afterward.
- Public update feed now returns 0.4.3; `/health/ready` returns `ok`. API, Worker, Beat and Proxy IDs and start times are byte-identical before/after feed hot reload. No data changes.
- Logs: `/tmp/fmg-043-{red,green,full,build,verify,manifest,release-tests,feed}.log`, `/tmp/fmg-043-published.json`.
