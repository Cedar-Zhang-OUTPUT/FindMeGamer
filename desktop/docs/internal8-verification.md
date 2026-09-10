# internal.8 package acceptance — 2026-09-10

Version `0.2.0-internal.8`, macOS build `20008`. Local/remote tag and artifact
availability were checked before packaging. This is a metadata-only companion
package: no desktop/src, backend, API, default origin or credential changes.
Business source remains `1206d0f6e822050978f6751cb39a3696e8f0d690`.

The accepted internal.7 regression (1260 passed / 5 environment-gated skips),
DTO gate and native UI/UX audit are reused, not rerun. Typecheck and build pass.
Existing chunk-size and optional .icon warnings remain; bundled .icns is verified.

## Artifact

Root: `/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.8-arm64-spVc4M`

- DMG: `FindMeGamer-Electron-0.2.0-internal.8-arm64.dmg`
- DMG SHA256: `abd3552a06e3f6b0af1a5c16a5ee291db9bd2b8f1cb264e633efe435338b17bd`
- ASAR SHA256: `f58cf4c9b93aa8570a1e5580d0688684f9da3c11fe83061a7a2f4109bf7071b9`
- Icon SHA256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`

## Verified

- arm64, minimum macOS 14.0, build 20008 and full internal.8 release metadata.
- App passes deep/strict ad-hoc signature verification; not Developer ID signed
  or notarized. Unrestricted Gatekeeper installation is not claimed.
- All ten ASAR runtime files match both current out and internal.7 byte-for-byte.
  Only additional archive file is package.json. No source maps, tests, fixtures,
  local settings or credentials. Bundled electron.icns equals build/AppIcon.icns.
- DMG verification passed. Read-only mounted app passes signature verification;
  mounted ASAR SHA matches. Volume detached afterward.
- Exact packaged executable passed its first fresh-profile launch test without
  retries: 1 passed (13.0 seconds total, test 12.6 seconds). Packaged version,
  isolated userData, default https://44.233.174.193, empty workspace key,
  disabled Connect, absent credentials.json and zero HTTP requests verified.
  Successful Settings screenshot visually inspected. No online write, provider
  request or email performed.
- internal.7 DMG remains unchanged, SHA256
  `24a1a2f3f83e20b6da1e35d85a78a039fb27720d19b300eca3f9c155cac84ee1`.
  Existing artifacts and evidence retained.

Evidence: `desktop/output/playwright/internal8-first-run-20260910/` with report
and screenshot copied into the artifact root's verification directory.

Packaging reused the existing Electron 44.2.0 arm64 ZIP through an in-memory
electronZipDir option, without dependency/configuration changes. ZIP SHA256 was
rechecked: `f906dff5d054b1b92e5711781b13cc206fd7139ce66467503b9d0a3e6fbc9b02`.

## Scope and handoff

The intermittent internal.7 Opening workspace timeout did not reproduce in this
single internal.8 launch. No fix or definitive resolution is claimed. Production
backend health and failed-checkpoint resume were not tested by this package gate.
Coordinator owns integration, push and release after its backend health check.
This package introduces no client feature or behavior fixes.
