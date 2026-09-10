# internal.7 package acceptance — 2026-09-10

Authorized version `0.2.0-internal.7`, macOS build `20007`. No matching local or
remote tag, or internal.7 artifact, existed before packaging. Functional source
is frozen at `1206d0f6e822050978f6751cb39a3696e8f0d690`: the four independently
reviewed UI/UX units. No desktop/src changes occurred during this packaging pass.
Only package/lock version, macOS build number, first-run version assertions and
this record change. No backend/API/default-origin or credential changes.

The accepted 1260 passed / 5 skipped regression, actual creator-search DTO gate,
independent reviews and final native UI/UX audit are reused, not rerun solely
for metadata. Typecheck and build pass. The existing chunk-size advisory remains.

## Artifact

Absolute root:
`/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.7-arm64-vUnD8B`

- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`
- DMG: `FindMeGamer-Electron-0.2.0-internal.7-arm64.dmg`
- DMG SHA256: `24a1a2f3f83e20b6da1e35d85a78a039fb27720d19b300eca3f9c155cac84ee1`
- ASAR SHA256: `0d6652a3e9c5b916c130170eeeb9808f53d5b9541c6add611d0773b2e758d48f`
- Bundled icon SHA256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`

## Package verification

- Mach-O arm64; build 20007, minimum macOS 14.0, full release semver internal.7.
- App local ad-hoc signature passes deep/strict verification. Not Developer ID
  signed or notarized; unrestricted Gatekeeper installation is not claimed.
- All ten runtime files in ASAR equal the current build byte-for-byte. The only
  other archive file is package.json, carrying full internal.7 semver. No source
  maps, tests, local settings, fixtures or credentials are in the archive.
- Info.plist references electron.icns; it equals build/AppIcon.icns. Packager's
  optional .icon-format warning does not affect the verified bundled .icns.
- hdiutil verify passed. Read-only mounted app passes deep/strict codesign and
  mounted ASAR has the same SHA256. The volume was detached after verification.
- Existing sealed internal.6 was not overwritten or repackaged.

## First launch and observed limitation

The first packaged audit timed out waiting for Open Settings: the renderer
showed Opening workspace while initial connection status had not completed.
No source or package changes were made in response. Initial status includes an
asynchronous secure-storage availability probe, but the exact cause was not
established; a cold-start delay on this machine is not ruled out. Observed facts:
the click waited 30 seconds (whole failed test 44.7 seconds); the failure capture
had fmg://app/index.html, a present bridge, Not connected and Opening workspace.
No OS Keychain prompt was captured or verified. The reported failure was a
locator timeout, not a main-process crash, and the test closed the app afterward.
This run did not collect comprehensive main-process/OS diagnostic logs.

The identical executable then passed three consecutive fresh-profile launches:
one test in 1.8 seconds, then two repeats in 2.9 seconds total. Each verifies
app.isPackaged, version, isolated userData, default `https://44.233.174.193`, empty
key, Connect disabled, no credentials.json and zero HTTP requests. The main
agent visually inspected the successful first-run screenshot. No connection,
online write, provider request or email was performed.

Evidence remains in separate output directories:

- `desktop/output/playwright/internal7-first-run-20260910/` — initial timeout
- `desktop/output/playwright/internal7-first-run-recheck-20260910/` — passed
- `desktop/output/playwright/internal7-first-run-confirm-20260910/` — 2 passed

Durable success report/screenshot and repeat reports are copied into the artifact
root's verification directory. UI/UX evidence under uiux-settings-unit4-acceptance
and earlier unit directories is untouched. Native workflows use synthetic
providers; this first-run gate does not test production-route health.

## Packaging environment

The normal packager stalled during its remote Electron check despite using the
existing proxy environment. That packaging process was stopped; its empty unique
directory pf4hSn was left untouched. The next invocation used the existing
Electron 44.2.0 arm64 ZIP cache via an in-memory electronZipDir option, without
editing the build script beyond buildVersion or changing dependencies/proxy.
ZIP integrity passed; its executable matched the installed Electron executable.

Cached ZIP SHA256:
`f906dff5d054b1b92e5711781b13cc206fd7139ce66467503b9d0a3e6fbc9b02`

Both executable SHA256 values:
`d3762bdff983315f18c07c3754175c4aa5b49d80977e1c33eb226b8189b447ed`

No push, tag or release was performed. Coordinator owns final integration and
publication and has been informed of the initial first-launch timeout.
