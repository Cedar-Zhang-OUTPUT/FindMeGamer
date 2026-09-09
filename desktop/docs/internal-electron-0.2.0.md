# Electron 0.2.0-internal.1 release preparation

Coordinator approved HTTPS origin `https://44.233.174.193`, deployed backend 5706ad7 / DB 0019. The public origin is a first-run suggestion only. Existing saved origins and encrypted keys remain authoritative. No workspace key is bundled, no connection or business request starts from this default, and missing credentials stay disconnected.

## Source verification

TDD: four expected failures before implementation; final 43 tests passed (credential-store, connection-default, renderer). Typecheck and build passed; existing chunk-size warning remains. One bounded independent Medium review found no P1/P2. Old empty-first-run assertions were updated; the custom-origin UI test now clears the prefilled field before typing. No backend/API changes.

## Packaging

- npm version `0.2.0-internal.1`; macOS short version `0.2.0`, build `20001`, custom release metadata includes full internal version and Electron technology.
- Before ASAR sealing, restore the full npm semver overwritten by packager's numeric macOS appVersion; native acceptance asserts `app.getVersion()` retains `internal.1`.
- Local and remote tag checks found no existing 0.2 tag at preparation time. Coordinator owns final tag/ref and publication.
- `npm run bundle:dir` creates a new uniquely suffixed artifacts directory every time, never overwriting older builds.
- Current host/target: arm64, macOS 14+. No Intel or universal compatibility claim.
- Bundle ID remains `com.findmegamer.desktop`, as in legacy SwiftUI; preserve app identity and existing Electron credentials. Do not overwrite the old app during testing. Keep the new app in its versioned directory. Electron uses `FindMeGamerDesktop` user data; isolated acceptance uses a separate temporary profile.
- Only ad-hoc code signing is implemented. Prior native bundle inspection confirms `Signature=adhoc`, no TeamIdentifier; no Developer ID or notarization claimed or requested. Other Macs may require their normal per-app Gatekeeper approval or IT policy approval.
- After source commit/freeze: package, verify ASAR/source runtime contents, icon and metadata, signature and architecture; create a separately named read-only compressed DMG, verify mount/signature/checksums. No publication from this task.
- Native first-run smoke uses a clean isolated profile, automatic updates disabled, no key entry or credential writes, and blocks external requests. It verifies the shipped default field and disabled Connect state, not authenticated cloud workflows.

SMTP and X credentials are not configured on the server. Installation does not imply those capabilities are ready; no live analysis or mail is part of this verification. Cloud authenticated read-only acceptance is owned by the coordinator/server task.

## Final local artifacts and acceptance

Runtime/package source frozen at `3667ac95efb11c79106f7ff8daad92fbf853acc7`. Later changes in this document and failure-capture test only do not change packaged runtime. All artifacts are under:

`/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.1-arm64-oHUOBL/`

- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`
- DMG: `FindMeGamer-Electron-0.2.0-internal.1-arm64.dmg` (~144 MiB)
- DMG SHA-256: `4d6b9b9976e533414cdee48b6db27f0d0cc1316753bd007549afb57dfd8e2285`
- ASAR SHA-256: `43ad8a3481c192feed1d22f7d6d749c8a21aa4dd7150a912898e8e0a181df41f`
- Embedded icon SHA-256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91` matches source `.icns`. Packager's missing optional `.icon` warning does not mean `.icns` is missing.

Nine packaged runtime files match the frozen build byte-for-byte. Package manifest retains full internal semver. App and read-only-mounted DMG app pass strict/deep signature verification; main executable arm64. `hdiutil verify` passed; mounted ASAR matches the original; test mount detached afterward. Old packages remain untouched and are not release candidates.

Native first-run: one final-package attempt timed out locating Open Settings; no captured evidence establishes its cause. A single bounded recheck of the same unchanged package passed (1/1, 1.6 s test / 2.1 s runner). The earlier pre-semver package also passed startup but is not the deliverable. Do not present these as uninterrupted green runs.

Final recheck confirms real packaged Electron, isolated `/tmp/fmg-internal-first-run-YKyVyu`, `app.getVersion() === 0.2.0-internal.1`, default HTTPS origin, blank key, disabled Connect, no credentials file, zero observed external requests after the test listener was installed. No key was entered and no encrypt/decrypt operation was requested. Own process closed afterward. Screenshot and JSON: `output/playwright-internal-first-run-final-recheck/internal-first-run-interna-af69b-without-a-key-or-connection/` (ignored local evidence); screenshot visually inspected.

The initial final-package startup timeout remains an observed test-stability limitation, not a diagnosed product defect. No other-Mac/Intel run, Developer ID notarization or authenticated final-package cloud scenario is claimed. Coordinator owns GitHub source/ref and Release upload.
