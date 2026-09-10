# P4 / P9 / P12 table restoration — 2026-09-10

## Scope and task path

Restore scan-and-compare layouts from PRD revision 755 without changing backend,
API contracts, credentials, source-of-truth rules, sorting, pagination or mutation
semantics. Original images were inspected at
`/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/prd-ui-audit-20260910/`:
`P4.png`, `P9.png`, `P12.1.png`, `P12.2.png`, and the adjacent `P6.png` / `P7.png`.

- Match: scan creators → select with existing behavior → expand match evidence
  only as needed → review selected people using the existing preparation path.
- Outreach: scan invitation status → open a creator's shared Invitations, or
  explicitly choose Update → edit the existing relationship → save/cancel.
- Creator Library: search/filter → compare records → open profile, works,
  contacts or direct Edit. Direct Edit obtains fresh detail first.
- Game Library: search/filter → compare records → direct Edit or Use for Match.
  Use also obtains fresh detail; it does not create an activity by itself.

## State and information hierarchy

| State | Main focus/action | Supporting information / disclosure |
| --- | --- | --- |
| P4 results | Aligned creator, platform, work, fit, email and language columns; selection | Long match narrative and full evidence behind Match details |
| P9 invitations | Relationship table, status filters, creator name / Update | No permanent right editor; shared creator history opens via name |
| P9 editing | Full-width current relationship below table | Explicit Update moves keyboard focus to the region; Close restores opener |
| P12 creators | Identity, platform, recent work, contact, updated, actions | Profile prose remains in detail; works/contact have direct labeled entry points |
| P12 games | Game/Steam ID, developer, links, updated, actions | Existing Game detail/editor remains the detailed editing surface |
| Loading / failed read | Existing scoped loading/error and retry | Last valid list retained; direct-action retry retains its original intent |
| Empty / filtered empty | Empty state or clear filters / choose creators | No fabricated records or source facts |
| Dirty / unknown write | Existing editor and recovery actions | Cannot hide a dirty or unconfirmed editor through Close; retry keys unchanged |

Global navigation remains stable. Narrow layouts keep the semantic table in a
focusable horizontal scroller instead of overflowing the document or silently
dropping columns. Row actions remain text buttons; controls have accessible names.
Background reads do not move keyboard focus. Creator detours retain edits, and
existing cancellation/unknown-result safeguards remain in force.

P9 retains an on-demand update editor because shared Creator Invitations is
read-only. Removing it entirely would remove existing write functionality. The
recorded-work column uses actual membership snapshots; absent work is an em dash,
not a guessed title. No new per-row requests were introduced for that column.

P6/P7 recipient, template preview and repair behavior from 204ff96 is unchanged.
This unit does not implement the later local-selection performance change.

## Verification

- TDD: new P4 table/disclosure assertions failed against the old card layout,
  then passed with the implementation. Added direct Library action assertions
  and a 50-row keyboard Update/Close focus-return case.
- One bounded independent P4/P9 review found a keyboard focus issue when Update
  appeared above a long list. Fixed explicit focus transfer and return; covered
  by the 50-row test. No ordering, selection, unknown-write or activity-isolation
  regression was reported. Library routing was reviewed locally.
- TypeScript typecheck passes. Build passes (existing large-chunk warning).
- Final unit suite: **125 files passed; 1,282 tests passed, 5 gated skips**,
  52.09 seconds with the local Creator Search DTO contract enabled. One initial
  run exposed a pre-existing Settings test race: a deferred initial category-focus
  callback competed with the test's later manual focus. The test now waits for
  initial category navigation before checking the return path; no Settings runtime
  behavior was changed.
- Native Electron acceptance: **2 passed**, 16.2 seconds, with a private isolated
  profile and synthetic read-only HTTP fixture. Non-GET business requests and
  non-fixture origins were blocked. Both reports record zero writes and zero
  page errors. No production messages, selections, drafts or settings were saved.
- Four-page native path covers 1440×1000 and 760×920, direct edit/cancel,
  works disclosure, Use for Match and guarded cancellation, match details via
  keyboard, creator Invitations, retained unsaved notes and close-focus return.
- Extended native audit covers failed invitation reads/recovery, filtered empty
  results, Creator detours, dark mode, 20px text, Settings guards and reduced motion.

Final evidence root:
`desktop/output/playwright/prd-tables-acceptance-20260910/`.

| PRD page | Actual screenshot, relative to evidence root |
| --- | --- |
| P4 | `prd-tables-native-PRD-P4-P-cfb8b--actions-in-native-Electron/P4-matches.png` |
| P9 | `prd-tables-native-PRD-P4-P-cfb8b--actions-in-native-Electron/P9-invitations.png` |
| P12.1 | `prd-tables-native-PRD-P4-P-cfb8b--actions-in-native-Electron/P12.1-creators.png` |
| P12.2 | `prd-tables-native-PRD-P4-P-cfb8b--actions-in-native-Electron/P12.2-games.png` |

Each has a corresponding `-narrow.png`. Reports are `verification.json` in that
directory and `uiux-readonly-native-read-only-current-task-visual-audit/audit.json`.
Earlier failed runs are preserved. Initial native failures were test navigation
assumptions around the pre-existing New Activity cancellation guard, not bypassed
by forcing clicks. Final screenshots wait for loaded rows and enabled controls.

## Limits

These are built-development Electron checks, not packaged DMG acceptance. Native
fixtures contain six creators/invitations and one game; the 50-row focus case is
a component test, not a real 50-row backend run. No screen-reader session, live
provider request, real save/send or new packaged release was exercised. The other
gated end-to-end suites were updated for table entry points but not all executed.
Horizontal overflow is local and keyboard reachable; the narrow viewport cannot
show every column simultaneously. Existing illustrative application chrome was
not redesigned in this PRD-restoration unit.
