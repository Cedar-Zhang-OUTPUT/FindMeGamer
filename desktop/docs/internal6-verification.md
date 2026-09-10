# internal.6 package acceptance — 2026-09-10

Coordinator authorized `0.2.0-internal.6`, macOS build `20006`. Read-only checks
found no matching local/remote tag or existing internal.6 package before starting.
The functional source is exactly `2e969cfc58fd090642cf743485c387945644f961`;
no `desktop/src` file changed during this packaging pass. Only package/lock version,
macOS build number, first-run version assertions and verification docs changed.

The previously accepted 1251 tests / 5 environment skips, actual DTO gate,
independent review and two native synthetic workflow paths are reused. This pass
ran typecheck, build and the exact-package native first-launch test (1 passed).
No production activity, provider request or email was initiated.

## Artifact

Absolute artifact root:
`/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.6-arm64-Uy0b2s`

- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`
- DMG: `FindMeGamer-Electron-0.2.0-internal.6-arm64.dmg`
- DMG SHA256: `c91b348e2f6d23c8bf7c85c2e1e848025ba129482a6831982400364f04549085`
- ASAR SHA256: `593eac6c45d9f7800e2eaea574b49c43d4e1db5a1b709b486dc570ae06e2ebde`
- Bundled icon SHA256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`

## Verified

- macOS metadata: build 20006, minimum 14.0, FMGReleaseVersion internal.6.
  Electron `app.getVersion()` returns the complete `0.2.0-internal.6` semver.
- Mach-O arm64; local ad-hoc signature, deep/strict verification passed.
- Exactly ten runtime files in ASAR match the current build byte-for-byte.
  The only other archive file is package.json; no local credentials, fixtures,
  test files or user service settings were bundled.
- `electron.icns` is referenced by Info.plist and matches build/AppIcon.icns.
  Packager's optional `.icon` warning did not prevent the verified `.icns` icon.
- `hdiutil verify` passed. DMG was mounted read-only; the mounted app passed
  deep/strict signature validation and its ASAR SHA256 matched. Volume detached.
- Exact packaged executable launched with an isolated temporary profile:
  default URL `https://44.233.174.193`, no key, Connect disabled, no credentials
  file and no HTTP traffic. App closed afterward. Main agent visually inspected
  the screenshot.
- Durable first-run report and screenshot are copied to artifact-root
  `verification/first-run.json` and `verification/internal-first-run.png`.

The first packaging attempt hit GitHub's connection timeout while checking the
Electron download. Retrying with `NODE_USE_ENV_PROXY=1` used the machine's existing
proxy configuration and succeeded, without changing project or user settings.
The interrupted unique artifact directory was not reused. Existing sealed
internal.1–internal.5 packages were not overwritten.

## Release boundaries

This is not Developer ID signed or notarized and does not claim unrestricted
Gatekeeper installation. Existing large JS chunk warning remains. No new full
regression was run solely for version metadata. The native workflow tests used
synthetic providers; backend real-broker/model and production deployment checks
are separately coordinator-owned. This package's first-run test deliberately
does not establish production-route health. Do not announce availability until
the coordinator confirms those gates. No push or release was performed here.
