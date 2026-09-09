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
