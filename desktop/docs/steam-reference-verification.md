# Steam reference provenance — September 10, 2026

## Scope

`f88935e` adds only Reference Works provenance and local acquisition status. Steam-origin references display “Steam recommendation” and an explicit source button, distinct from the target game's URL. No played/verified/AI similarity claims are inferred. Existing editing and deletion remain available; replacement payloads retain the old editable fields and ID, never client-authored source metadata. Empty-reference failures remain visible. Existing Refresh Steam source / Analyze game controls are unchanged.

`e13b459` sends `X-FMG-Steam-References: 1` only from authenticated workspace API transports. External media and source-link opening do not carry it. The backend owns opt-in response projection and preserves the old shape for existing internal.4 clients, including nested Game snapshots and idempotent replays. Missing metadata remains compatible; new metadata is strictly validated in Game and draft boundaries.

## Verification

- TDD: new DTO tests initially failed at strict Game/nested draft decoding; new UI tests initially lacked source/failure rendering; opt-in tests initially observed no feature header. Each passed after its implementation.
- Typecheck, build, 126 related UI/client tests, and 36 opt-in/transport tests passed.
- Final combined suite: 116 files, 1243 passed / 1 environment-gated test skipped. The skipped actual-Game export test was subsequently run explicitly against both real API-exported synthetic Game responses: 10 tests passed for each of `game-detail.json` and `game-detail-unavailable.json` under the coordinator workspace `.local/steam-reference-dto/`.
- UI tests walk detail → source button → edit reference → remove reference → save. The unchanged revision-checked removal body is asserted. Partial failures and zero-reference unavailable state are covered. No production data was changed, no live import was initiated, and no SMTP was sent by the frontend task.
- New API provenance must not break frozen old clients. `scripts/verify-steam-compat.mjs` reads exact internal.4 Game/draft decoder source from commit `26e382f`, compiles in memory and validates actual old-shape exports; the opt-in draft is checked by current decoders. This does not alter old sources or packages.

The existing internal.4 package remains sealed and unchanged. Coordinator reserved internal.5/build20005 for a separate package after final compatibility checks. Final compatibility and package outcome follow below.

## Final compatibility and internal.5

Backend contract pin: `97f3c19d2694c0a158d461791e4616a153f4a413`. Actual API exports `game-detail-legacy.json` and `draft-legacy.json` passed unchanged through the frozen `26e382f` strict decoders. `draft-new.json` passed through current decoders. The verification also asserted legacy nested references contain neither source field and legacy Game has no steam_recommendations. No wire metadata was hand-edited to make a test pass.

Source/release commits: `f88935e` → `e13b459` → `5dd040b`. Version-only final typecheck/build passed; no redundant full regression after that metadata change. A packaging command initially ran from repository root (no package.json); rerunning from desktop succeeded, with no code fix required.

Unique artifact root:
`desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.5-arm64-nr0Png/`

- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`
- DMG: `FindMeGamer-Electron-0.2.0-internal.5-arm64.dmg`
- DMG SHA256: `0f6765336bb1ec8363f15c2797c6be641bb83750f5de87a92ce8672a65364592`
- ASAR SHA256: `9d9ff82720953b9881124e54d55425add77c97d64344697218915f480f7dd760`
- Bundled icon SHA256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`

Ten runtime files match the build byte-for-byte. Packaged app version internal.5, macOS build 20005, icon electron.icns correctly referenced. Local ad-hoc deep/strict signature and DMG checksum verification passed; read-only-mounted app signature and ASAR matched, then the volume was detached. No Developer ID or notarization claim.

Native exact-package first-launch test passed with isolated profile, empty key, default cloud origin, no credentials file and no HTTP requests; app closed afterward. The screenshot was visually inspected. Durable native evidence is in the artifact root's `verification/{first-run.json,internal-first-run.png}`. This is first-launch evidence only: the Steam source UI path was exercised by component integration tests and real API DTO decoders, not a live native import or a production Game mutation.

Coordinator owns deployment, GitHub upload and download-link publication. No previous package was replaced, no production reference data was filled, and no analysis or SMTP was triggered for the user's current Game by this frontend task.
