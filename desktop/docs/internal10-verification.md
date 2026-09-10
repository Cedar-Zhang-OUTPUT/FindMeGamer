# internal.10 artifact — accepted for integration upload

Date: 2026-09-10. Runtime fix: `5c0f564`. Only the table vertical scroll hotfix and scoped keyboard forwarding are included beyond internal.9.

## Artifact

Root: `/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.10-arm64-gf9qoh`

- DMG: `FindMeGamer-Electron-0.2.0-internal.10-arm64.dmg`
- SHA-256: `b555b4f219ebab7f3eb5e026e12dbaf18af616326a66cfd785d1deed76283891`
- ASAR SHA-256: `a114e577e7c81394778fe64ddd49bab7572fa025f8332bf218fb63a09596802c`
- Version: `0.2.0-internal.10`, bundle build `20010`, arm64.
- Latest published release was internal.9; internal.10 tag lookup returned 404 before packaging.

## Passed

- Typecheck/build, seven new keyboard unit tests.
- Full suite with `--maxWorkers=2`: **1314 passed, 6 skipped**, 128 files passed, one skipped, 57.81s. An earlier unconstrained run alongside Electron had six async UI/time-limit failures; no timeouts or production behavior were altered to obtain the passing rerun.
- Development Electron: four 50-row cases, each 1440×680 and 760×680, **4 passed (30.2s)**. See `table-scroll-verification.md` for RED→GREEN and independent review.
- Final app strict/deep ad-hoc signature check, DMG checksum verification, read-only mount signature check, identical mounted ASAR checksum. Mount detached.
- All ten runtime files match current build byte-for-byte. Packaged icon matches `build/AppIcon.icns`. Archive version matches internal.10.

## Packaged acceptance completed after user handled the system blocker

The first packaged restart test timed out before reaching the task, displaying `Opening workspace…` in a fresh isolated profile. A subsequent packaged scroll test also stalled at startup. A system UI inventory request independently timed out. A lock-screen/keychain prompt is suspected, not established. User was asked to inspect/unlock the Mac; credential policy was not bypassed. The current packaged regression run was interrupted rather than treating failures as passes.

Initial evidence remains preserved at `desktop/output/playwright/internal10-packaged-scroll-20260910/`.

After the user reported the blocker handled, the same artifact (no runtime or credential changes) passed:

- Four 50-row table cases in actual packaged Electron, each at 1440×680 and 760×680: wheel over tbody, last row vertically visible, pagination and bottom buttons visible, horizontal wheel/ArrowRight retained, reverse wheel, PageDown and Home/End. Individual durations: Creators 3.6s, Games 3.0s, Matches 4.2s, Invitations 4.0s.
- Actual normal process quit/relaunch: 5.5s. PIDs 96924→96941, same isolated profile, four selected records restored including the final pending toggle, zero HTTP writes and zero page errors.
- The first-run case initially timed out once more in that combined run; subsequent isolated rerun passed in 1.4s (1.7s suite). It verified default origin, empty key, disabled Connect, no credential file and zero HTTP requests. No timeout thresholds were changed. The precise system cause of the transient startup blockage remains unconfirmed.

Evidence: `desktop/output/playwright/internal10-packaged-final-20260910/` (five passing cases plus preserved first-run failure), and `desktop/output/playwright/internal10-first-run-confirmed-20260910/` (first-run pass). JSON asserts `packaged:true`, version internal.10 and the exact gf9qoh ASAR path. Packaged narrow Invitations screenshot personally reviewed: final rows, horizontal scrollbar and Next button are reachable.

No production HTTP writes, analysis interruption, backend deployment/restart or API contract changes. Fixture reads and test-only synthetic 50-row IPC data only. No Developer ID signing, notarization, physical touchpad or OS reboot claim. Integration task owns upload; this artifact is **ready for integration upload**. This worktree has not published it.
