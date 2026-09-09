# Internal.3 candidate: Match → Outreach navigation

## Scope and state transitions

User trial amendment to cached PRD revision 752: Match is the find-and-prepare task, not a second parallel Invitations destination. A quiet `Open in Outreach` action opens the current activity in global Outreach. Outreach still defaults to Invitations and retains its Prepare & send tab.

The existing App navigation guard owns the transition. Keep working retains unsaved conditions or invitation notes; only explicit Discard abandons edits. The shared MatchWorkspace route and activity component stay mounted, retaining the selected activity, saved draft controller, search scope, candidate state and invitation filters. Failed planning state is not cleared, retried, or replaced by navigation. No new activity, discovery, delivery or contract operation is added.

## Evidence

- TDD: the new no-Invitations assertions failed against the old UI, then passed after implementation. Targeted global-Outreach/collaboration suite: 10 passed, including failed-plan return and explicit retry availability.
- Typecheck and production build passed; existing >500 kB bundle warning remains.
- One bounded independent read-only review found no P1/P2 issues in the navigation, guard, activity ownership or ARIA changes.
- Built production renderer with real local adapters: 1 passed. Same-activity Match → Outreach → Match; invitation filter retention; condition edits and invitation-note edits guarded with Keep working; local edits canceled without saving; 760 px / 135% text overflow check. Match and Outreach screenshots inspected.
- Read-only fixture ledger: `c-renderer-856b6278-484f-4ee9-b57c-08fa5584142b.json`, private fixture folder retained outside Git. Backend pin `5706ad76f924991b80ee2a7fb6806528366be5ce`. 33 GET, zero POST, zero runtime/scope errors, source/build hashes and fixture effects unchanged.
- Screenshots: `desktop/output/playwright-internal3-navigation` (local ignored evidence).

## Limits

This is built-renderer evidence, not native internal.3 package verification. No cloud discovery/model request or email was issued. The backend planning-output failure belongs to the separate backend fix; frontend only checks that an existing failure and Retry remain accessible after navigation. Library/Settings were not changed; Updates is not user-accepted or newly verified. Packaging waits for coordinator alignment with the backend fix. No upload from this task.

The first full-suite run at default parallelism had 11 timeout/initial-DOM wait failures (108 workers); no timeout or assertion was relaxed. A bounded-worker full rerun is recorded separately below.

Final full rerun: `npx vitest run --maxWorkers=2` — 108 files / 1,194 tests passed in 67.80 seconds. No code or assertion changes between the two full runs; only worker concurrency changed.

## Authorized package handoff

After the above navigation verification, the user explicitly authorized direct packaging without waiting for backend deployment alignment. Runtime change: `3e6fb9e`; version-only packaging commit: `95388b0`. The coordinator owns backend alignment and publication. No backend changes or uploads were made here.

- Version: `0.2.0-internal.3`, build `20003`, arm64, macOS 14+.
- Independent artifact root: `/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.3-arm64-o31s9f`.
- App beneath root: `FindMeGamer-darwin-arm64/FindMeGamer.app`.
- DMG beneath root: `FindMeGamer-Electron-0.2.0-internal.3-arm64.dmg`.
- DMG SHA-256: `06f7e2e6e903c287116281198673405c7a49cfba0faf95036b1f53ece8c349a9`.
- ASAR SHA-256: `3b738ed3984df55b1659d6aaf5f6b8cdec8b46944579b8ddeade2fb10e10c0c5`.
- Bundled icon SHA-256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91` (existing project icon, `Contents/Resources/electron.icns`).
- `codesign --verify --deep --strict` passed. Local ad-hoc signature only; no Developer ID or notarization. Old packages were not replaced.
- Real packaged Electron first-run: **1 passed**, isolated profile, packaged version confirmed, default `https://44.233.174.193`, empty key, Connect disabled, no credentials file, zero observed external requests. Screenshot visually inspected. Evidence: `desktop/output/playwright-internal3-native-first-run`.
- Native evidence covers first launch only. The same-activity navigation/dirty-state checks above used the built renderer with real local adapters, not a claimed full native business chain. No real email, discovery or model request was issued during packaging verification.
