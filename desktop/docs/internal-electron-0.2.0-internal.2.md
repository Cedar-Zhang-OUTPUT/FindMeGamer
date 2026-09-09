# 0.2.0-internal.2 — trial handoff

Scope: finish the current front-end iteration and let the user try it. This is not full PRD acceptance. Backend, migrations, API contracts, production data and email delivery are unchanged.

## Changes

- P1: dedicated game selection, Library / Steam inputs retained across tabs, direct Library management return and refreshed results.
- P2: game review before explicit Continue creates an activity; optional activity name; short reference dialog with cancel, duplicate focus, optional similarity criteria and one-to-one reference selection. Save-and-leave cannot implicitly create an activity.
- P3/P4: quieter contextual tools, compact comparable creator rows, direct Draft N emails action, query/usage details below primary results. Prepared selections open template editing directly.
- P9: invitation roster with creator, recorded work and separate sending/response/follow-up statuses; existing editors and contracts retained.
- Existing pixel artwork and app icon retained. YouTube/X active and Twitch/Instagram unavailable remain the approved scope. Actual email Settings remains available.

## Verified

- Full unit suite: 108 files, 1,192 tests passed; typecheck and production build passed. Build reports a non-blocking >500 kB chunk warning.
- Bounded review: save-and-leave activity creation, stale Library return and expanded reference selection fixed with regression coverage.
- Final built-renderer read-only game entry: Library handoff to P2, P1, tab input retention and 760 px / 135% text / reduced-motion overflow check passed. P1/P2 screenshots visually inspected.
- Final built-renderer global Outreach check passed, read-only; existing collaboration navigation and narrow layout checked.
- Real synthetic local adapters: game-to-discovery, candidate selection, creator detail return, freeze/template composition and missing-source send blocking exercised. P7 to SMTP settings and back, then P6 return exercised successfully before an additional navigation assertion failed.
- Final read-only evidence: `output/playwright-internal2-entry-final`, `output/playwright-internal2-c-final`.

## Not yet verified / limitations

- The extra P6-to-global-Outreach navigation encountered an unsaved-change confirmation; that end-to-end run is NOT green. Investigate dirty-state expectations after trial.
- Synthetic creator lacks public name and work evidence: full rendered email was correctly blocked. No extra shared creator data was written to bypass this. Complete email and real delivery remain unverified; no email was sent.
- Full native business chain, all PRD states and exhaustive visual/accessibility acceptance are not completed. Built-renderer adapter checks are not native Electron business-flow certification.
- Existing profile/history interaction is not claimed to match every PRD detail.

## Distribution constraints

- Independent internal.2 package; never overwrite internal.1 or daily installation.
- Default cloud origin stays `https://44.233.174.193`; no bundled workspace key, no automatic connection or writes on fresh launch.
- Local ad-hoc signature only, not Developer ID signed or notarized. macOS 14+, Apple Silicon.
- Coordinator task `01a05d57-6a9a-7f41-9095-d7d3e97837f0` owns GitHub integration/publication.

## Final packaged evidence

- Runtime source commit: `2c29e4b`.
- Artifact root: `/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.2-arm64-hFYFuV`.
- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`; DMG: `FindMeGamer-Electron-0.2.0-internal.2-arm64.dmg` beneath that root.
- DMG SHA-256: `5f15869b7931706b24e3cb9bd7067c539b860fdc7b79262836e7cd6af27cb6ce`.
- app.asar SHA-256: `0a2fb1f72cbe3a8d4f69c33427c9e92075c490213c70bfef62a205382b6705e3`.
- Bundled `Contents/Resources/electron.icns` matches `build/AppIcon.icns`: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`. The legacy filename is expected and is referenced by CFBundleIconFile; no missing icon.
- `codesign --verify --deep --strict` passed. Plist release internal.2 / build 20002; Electron reports packaged version `0.2.0-internal.2`.
- Native packaged first-run test: 1 passed, isolated profile, empty key, Connect disabled, no credentials file, zero observed external requests. Screenshot visually inspected. Evidence: `output/playwright-internal2-native-first-run`.
- Final P1/P2 and narrow Outreach screenshots visually inspected. No claim of complete native business-flow acceptance.
