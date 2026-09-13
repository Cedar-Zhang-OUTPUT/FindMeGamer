# Internal.11 artifact acceptance — 2026-09-13

Status: accepted for root-coordinated internal release; not uploaded by this task.

## Frozen implementation

- f58a34f: per-draft personalization, partial persistence/preview, strict sending
  boundary, per-field confirmation invalidation and real packaged IPC test.
- 272bffe and a59e336: retained scoped bulk selection and loading diagnosis.
- Version `0.2.0-internal.11`; macOS bundle build `20011`; arm64 Electron 44.2.0.
- Compatible backend contract: 14d0a6c. Backend deployment is coordinated by root.

## Artifact

Root directory:
`desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.11-arm64-udAHQe/`

- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`
- DMG: `FindMeGamer-Electron-0.2.0-internal.11-arm64.dmg`
- DMG size: **151241430 bytes**
- DMG SHA-256: `b5eed06465620c5747bada602f6114e4d7c329e70c2c18a77108a3d7fbe05bc5`
- ASAR SHA-256: `d562ffd65ae0e5046d61e4c39e3a87291293bb18019a8b559b5b82ddb5375865`
- App icon SHA-256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`

Ten packaged runtime files match the local frozen build byte-for-byte. Full
internal version is preserved in packaged package.json. The app icon is correctly
packaged under Electron's `electron.icns` filename; its hash equals build/AppIcon.icns.

Strict/deep ad-hoc signature verification passed for original and mounted app.
`hdiutil verify` passed; read-only mounted ASAR equals original ASAR. Mounted DMG
application real-process launch and full personalization acceptance passed:
**1 test, 11.6 seconds**. The test mount was detached afterward.

## Test evidence and limits

- Vitest **1347 passed / 6 skipped**, 131 files passed / 1 skipped, 60.78 seconds.
- Typecheck/build pass; existing Vite large-chunk warning retained.
- Packaged personalization with real IPC/API/isolated persistent DB: **1 passed**.
- Same app bulk selection and four wide/narrow table scroll cases: **5 passed**.
- Mounted DMG repeats saved override, empty Observation, preview, per-person
  retained editing, refresh preserving overrides, reload, unchanged shared Creator
  and sibling drafts, blocked qualification, and current-content human-confirmation
  display. No send or sender-facts mutation is invoked.
- Evidence directories beneath desktop/output/playwright:
  `personalization-internal11-final-20260913`,
  `personalization-internal11-mounted-20260913`,
  `internal11-bulk-scroll-20260913`.
- One bounded independent review, one P2 fixed and covered by unit and native checks.
  Detailed behavior and TDD notes: personalization-verification.md.

First package download timed out connecting to GitHub. Rebuilt using the existing
local Electron 44.2.0 archive; no dependency version change. First native attempt
timed out (90 seconds plus teardown); later debug and normal native runs passed.
These failures remain in their original output directories, with no claim of an
established startup root cause. No runtime edits followed the accepted package.

This is an ad-hoc signed internal macOS arm64 Demo, not Developer ID signed or
notarized. Verification does not exercise real providers, real SMTP, live production
traffic, Intel Macs or all accessibility settings. Real API acceptance used synthetic
loopback 18743; bulk/scroll used loopback 18093, with synthetic IPC row expansion
for layout stress. Production state and the user's installed app were not replaced.
