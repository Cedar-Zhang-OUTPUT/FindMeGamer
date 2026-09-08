# First desktop rebuild unit · 2026-09-08

## Source and scope

PRD read through the user-authorized Feishu document API: revision 751 of `MOoWdOYNvoogWnxF7jYcGgGinrh`. The coordinator's architecture review was read completely from the uncommitted original-workspace document. Updated coordinator decisions take precedence over older PRD prototype notes: Electron stack, existing necessary connection settings, FindMeGamer/English branding, Instagram unconnected, and initial v1 read-only Library.

Base worktree `codex/electron-desktop` began at `75f94eb`; it keeps earlier Swift and diagnostic history intact. Delivery consists only of new `desktop/` commits/files; do not merge old diagnostic commits into the release branch. No backend, database, original-workspace, deployment, analysis, match or mail mutation is in scope.

## Task path and state design

Connect workspace → browse Creators or Games → explicitly search/filter → open a profile → inspect facts/contacts or expand sources → return to the same results. Settings remains available; Match and Outreach are visibly not connected in this delivery.

| State | Main focus / action | Context retained | Disclosure / transition |
| --- | --- | --- | --- |
| Not configured | Connect workspace / Open Settings | Four navigation entries | Connection form appears on request |
| Editing connection | Service URL + key / Connect | Existing origin and saved-key indicator | No stored key is displayed |
| Saving / verifying | Local operation feedback | Form location, origin | Library stays closed until auth succeeds |
| Library loading | Reserved list region | Tab, search and favorites | Result or actionable error replaces loader |
| List ready | Actual profile rows / Open profile | Separate tab searches and pagination | Load more appends only after success |
| Empty result | Empty state / change search or filter | Current query/type | Does not imply an unconnected source searched successfully |
| Detail | Identity, known facts, contact choices | Return route and original list | Full public evidence/source fields expand nearby |
| Local failure | Relevant error / retry | Current query; previous pages on load-more failure | New searches/refreshes replace the list; retry uses the correct current query/cursor |
| Disconnect / replace | Consequence confirmation or explicit new credentials | Global navigation | Old results and late responses are invalidated |

Errors, key rejection and secure-storage unavailability remain visible. No background operation automatically scrolls or moves keyboard focus. Essential controls retain visible labels or accessible names; animation observes reduced-motion preferences.

## Tests and review

TDD evidence so far:

- Policy/transport tests were added and failed before those modules existed, then passed after implementation.
- Credential store: 12 asserted failures against a skeleton, then 15 tests passed after implementation/recovery coverage.
- Library adapter: missing module first, then 38 tests passed against the actual v1 shapes and routing.
- Renderer behavior tests were written before the App implementation.
- Independent main-process review identified stale failed requests and a proxy-check race after disconnect; three regression tests failed before the shared generation guard was implemented.

Verified on 2026-09-08, Apple Silicon / current macOS host:

- TypeScript check and production build passed. Vitest: **85 tests in 6 files passed**.
- Actual Electron integration: **2 tests passed** using the synthetic HTTP fixture and the coordinator's isolated FastAPI/Postgres/Redis API. The latter loaded `Fixture Cozy Gamer`, its contact, and `Fixture Star Garden` through Settings and the real v1 routes. No backend worker, mail, provider or paid task was invoked.
- A separate opt-in Electron system-proxy test passed: all shell proxy variables removed from the app process, macOS system proxy actually selected, TLS-verified anonymous HTTPS health request returned 200 / healthy. No production Workspace Key was used.
- The local packaged `.app` repeated **both isolated-backend and system-proxy tests successfully**. `app.isPackaged`, `app.asar`, the fixed `fmg://app/index.html` origin, preload bridge and all three bundled visual assets were checked. The `.icns` resource is embedded and referenced by Info.plist; minimum macOS is 14.0.
- Real Electron checks exercised password clearing, actual OS-encrypted persistence (no plaintext key in its file), reload/reverification, list/detail return, same-key connection testing without losing the detail, local failure/retry, four-page navigation, 760×660 window fit, no renderer Node/process/storage bridge, restricted external URLs and a scriptless/IPC-free preview frame.
- Main-process and renderer independent reviews closed two stale-connection races and the same-key context-loss regression. A packaging review led to a runtime allowlist excluding source maps and development/test files. Local code signing uses ad-hoc signing only; distribution signing/notarization has not occurred.

These are real desktop / isolated-data results, not production Library acceptance, performance benchmark results or release approval. The preview is an isolation primitive, not a completed email feature.

## Remaining boundary

No production Workspace Key is assumed or extracted from the old client. Isolated-data acceptance is complete; production read-only acceptance still requires authorized user entry in the new Settings and has not occurred. No SMTP/provider calls or paid tasks may be used merely to make the demo look connected. The backend integration environment uses explicit test data and must not be represented as the live cloud library.

Full v2 editing/discovery/outreach, dual-architecture DMGs, updater delivery, Intel/macOS 14 hardware checks and an end-to-end accessibility pass remain outside this first unit. It creates no release or deployment.

## Explicit follow-on units

Order confirmed by the coordinator: finish this read-only unit → separate Game v2 unit → coordinated full Settings migration. No v2 edit methods were added early. Previously announced identity rules are not copied into the client; confirmed account rebind and its historical isolation must use the final backend contract.

The coordinator's architecture review section 9 was read on 2026-09-08. The blank Settings prototype is an adaptation space, not authorization to delete previous functionality. Its later migration must cover:

- Local appearance: system/light/dark, font size and reset appearance defaults.
- Local workspace: origin, access credential replacement/status and disconnect only this Mac (no cloud deletion).
- Shared service settings: Steam, YouTube, DeepSeek and Google AI configuration status, replacement and testing; X/Twitch follow supported backend contracts. Stored keys never return to the renderer. Shared changes warn that they affect colleagues.
- Shared automatic profile refresh: independent Game 1–90 day and Creator 1–30 day intervals; no new disable-auto-analysis switch.
- Shared SMTP: host, port, encryption, account, password replacement, sender name, Reply-To, rate, connection test and an explicitly confirmed test message to a specified recipient. No real test email without authorization. Settings owns one configuration; Outreach links to it rather than holding a second copy. Templates stay in Outreach.
- Local software update preferences: current version, check for updates, automatic-check preference/status and GitHub manual download; no automatic installation system.

Unsaved inputs must survive unrelated refreshes. Do not add language switching, client S3 keys (server role remains authoritative), fake Instagram connection controls, or the removed Yes/No template appending behavior. Test writes belong only to an isolated environment after the appropriate contract and authority are in place.
