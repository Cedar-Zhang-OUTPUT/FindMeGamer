# internal.4 acceptance — September 10, 2026

## Source and checks

Runtime source: `aecd922`; release metadata: `64a7c87` (0.2.0-internal.4, build 20004). Earlier scope/fixture evidence is in `meeting-ui-verification-20260909.md`.

- Final typecheck passed.
- Final Vitest: **114 files, 1230 tests passed**, maxWorkers=2, including the four actual backend 29fe65b synthetic DTO tests (FMG_EVIDENCE_CONTRACT_DIR supplied).
- Build passed. Existing 646kB main-renderer chunk warning remains; no performance claim is inferred from build success.
- One bounded review from the prior unit was reused. No new broad review or feature expansion.
- Real renderer/isolated API missing-sender recovery passed, following the already-passed main meeting journey. Sender restored to synthetic_configured; no SMTP sends, production writes or real credentials used.

## Package

Unique artifact directory (older releases untouched):

`desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.4-arm64-hjbBWj/`

- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`
- DMG: `FindMeGamer-Electron-0.2.0-internal.4-arm64.dmg`
- DMG SHA256: `6bdc460cf5e95ef9f25f1411d1b4459e0320f127109baccf336c0f5edbc266c0`
- ASAR SHA256: `b7c3feaedfbc50b8ecc53c9feac39551aa840c6d0b6fb306b6389ee61746ce69`
- Icon SHA256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`

Ten bundled runtime files match the build byte-for-byte. Packaged manifest is 0.2.0-internal.4, Info.plist build 20004, numeric macOS version 0.2.0, minimum macOS 14. Source AppIcon.icns and bundled electron.icns match; Info.plist points to electron.icns. Packager's skipped optional `.icon` format warning does not mean the `.icns` is absent.

Local ad-hoc strict/deep signature verification and hdiutil DMG checksum verification passed. DMG was read-only mounted for checking its app signature and ASAR, then detached. This is an arm64 internal-test build, not Developer ID signed or notarized.

## Native first launch

`e2e/internal-first-run.spec.ts` passed against the exact packaged executable, isolated fresh profile, native Electron isPackaged=true and version 0.2.0-internal.4. Workspace settings default to https://44.233.174.193 with empty key, Connect disabled and no credentials file. Test network guard observed no HTTP requests. Native app closed after test. Screenshot visually inspected.

Evidence: `desktop/output/playwright/internal-first-run-interna-af69b-without-a-key-or-connection/{first-run.json,internal-first-run.png}`.

## Limits and handoff

Native evidence covers first launch/settings, not an entire native authenticated workflow. Business journeys were tested through the production renderer and actual isolated API adapters; newer evidence metadata was verified using actual API-exported DTOs. Live cloud deployment, real provider credentials/model quality, SMTP delivery and notarized distribution are not claimed. Coordinator owns cloud deployment, integration, GitHub upload and download-link publication. This frontend task changed no backend source.
