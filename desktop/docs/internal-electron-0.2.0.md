# Electron 0.2.0-internal.1 release preparation

Coordinator approved HTTPS origin `https://44.233.174.193`, deployed backend 5706ad7 / DB 0019. The public origin is a first-run suggestion only. Existing saved origins and encrypted keys remain authoritative. No workspace key is bundled, no connection or business request starts from this default, and missing credentials stay disconnected.

## Source verification

TDD: four expected failures before implementation; final 43 tests passed (credential-store, connection-default, renderer). Typecheck and build passed; existing chunk-size warning remains. One bounded independent Medium review found no P1/P2. Old empty-first-run assertions were updated; the custom-origin UI test now clears the prefilled field before typing. No backend/API changes.

## Packaging

- npm version `0.2.0-internal.1`; macOS short version `0.2.0`, build `20001`, custom release metadata includes full internal version and Electron technology.
- Local and remote tag checks found no existing 0.2 tag at preparation time. Coordinator owns final tag/ref and publication.
- `npm run bundle:dir` creates a new uniquely suffixed artifacts directory every time, never overwriting older builds.
- Current host/target: arm64, macOS 14+. No Intel or universal compatibility claim.
- Bundle ID remains `com.findmegamer.desktop`, as in legacy SwiftUI; preserve app identity and existing Electron credentials. Do not overwrite the old app during testing. Keep the new app in its versioned directory. Electron uses `FindMeGamerDesktop` user data; isolated acceptance uses a separate temporary profile.
- Only ad-hoc code signing is implemented. Prior native bundle inspection confirms `Signature=adhoc`, no TeamIdentifier; no Developer ID or notarization claimed or requested. Other Macs may require their normal per-app Gatekeeper approval or IT policy approval.
- After source commit/freeze: package, verify ASAR/source runtime contents, icon and metadata, signature and architecture; create a separately named read-only compressed DMG, verify mount/signature/checksums. No publication from this task.
- Native first-run smoke uses a clean isolated profile, automatic updates disabled, no key entry or credential writes, and blocks external requests. It verifies the shipped default field and disabled Connect state, not authenticated cloud workflows.

SMTP and X credentials are not configured on the server. Installation does not imply those capabilities are ready; no live analysis or mail is part of this verification. Cloud authenticated read-only acceptance is owned by the coordinator/server task.
