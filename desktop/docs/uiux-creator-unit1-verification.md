# UI/UX unit 1 — Creator information hierarchy

## Scope

Only shared Creator presentation and its Match return affordance changed.
Exactly two pages remain: Profile and Invitations. Profile no longer contains
an Overview/Emails/Works tab layer. Email and work groups expose record counts
and available previews, and expand in place; works are still fetched only on
explicit expansion. Direct email/work entry restores the intended open group.

Identity/actions are compacted, Match has one correctly named return action,
and an unavailable analysis is a compact expandable state rather than a large
empty highlight. Stale state and unavailable reasons remain accessible. Supported
analysis keeps evidence/coverage and the existing AI label. No backend/API,
mutation guards, send behavior, profile identity or invitation scope changed.

## Verification

- New assertions first failed for nested tablists, absent contextual return
  label and the empty At a glance highlight; passed after implementation.
- Seven related files / 65 tests passed, including creator edit/save return,
  old identities, source safety, lazy works loading and invitation scope.
- Full boundary regression: 122 files, 1253 passed / 5 environment-gated skips;
  actual creator-search DTO validation enabled. Typecheck and build passed.
- Read-only Electron audit against exclusive synthetic 18093: passed in 5.4 s,
  zero HTTP write attempts and zero renderer exceptions. Local isolated-profile
  connection/appearance preferences were the only configuration writes.
- Real keyboard Enter/Space expands the email/work groups. Navigation away and
  back retains the open works group. All captured states had no horizontal
  overflow, including 760 px and dark mode; reduced-motion mode was used.
- Main agent inspected default profile, expanded works, embedded Match creator,
  narrow and dark screenshots. Email/work entry now fits in the default first
  viewport instead of sitting below the former empty analysis card.

Baseline, initial iteration and final screenshots are intentionally distinct:

`desktop/output/playwright/uiux-baseline-20260910/`

`desktop/output/playwright/uiux-creator-unit1-20260910/`

`desktop/output/playwright/uiux-creator-unit1-final-20260910/`

The final directory's `uiux-readonly-native-read-only-current-task-visual-audit/`
contains audit.json and named Creator/Match/Library/Outreach/Settings PNGs. These
paths are not reused by the package first-run suite. No production task, data
mutation, analysis run or email occurred. No internal.6 artifact was overwritten.

## Limits / next units

This unit does not remove the remaining Library framing above a detail, change
the whole-client banner, or restructure Outreach/Settings; those are separate
planned units. Native editing/failure injection was not performed against the
read-only fixture; related component regressions cover those paths. Screen-reader
navigation beyond keyboard/ARIA assertions remains unverified. Independent
coordinator review found no Demo blockers; its five-file, 36-test targeted run
passed, and the coordinator visually accepted the final Creator screenshot.
Source submission is authorized; no package or publication is authorized here.
