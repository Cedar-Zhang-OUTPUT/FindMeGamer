# Native 0.4.3 — Match Result pagination

Match Result now renders at most 20 Creator rows per page. Previous, Next and a numbered page picker stay below the scrolling content. Recommended and Other matches retain backend ordering; a page containing only Other matches displays them directly. Page changes replace the scroll subtree, releasing off-page row views and resetting the page's scroll position. Selection lives outside that subtree and remains available across pages for the existing outreach flow. Select page selects eligible recipients on the current page; Clear selection clears all pages.

The client slices the result before building expensive row/brief presentations. This is client-side rendering pagination: the existing backend result API and in-memory decoded result are unchanged, not a claim of server-paginated payloads. No backend deployment, analysis, retries, profile changes or email sends are required.

Verification: first ran a failing 1,200-result test (old implementation constructed 1,200 rather than 20 presentations), then passed the full Swift suite: 369 tests / 55 suites. Regression coverage includes crossing the Recommended/Other boundary, last page, page return, result shrink, empty result and cross-page recipient selection. Bounded independent review found no blockers.

Distribution: universal native macOS 14+ app, default service https://44.233.174.193. Internal ad-hoc signature, not Apple-notarized. The update feed is promoted only after verified GitHub assets are published.
