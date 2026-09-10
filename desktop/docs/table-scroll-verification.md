# Table scroll hotfix — 2026-09-10

Scope: P4 Creator matches, P9 Invitations, Creator Library and Game Library only. No backend, service, contract or credential changes.

## Cause and fix

The shared horizontal table wrapper grows to the table's full height. Its `overflow:auto` establishes a scroll container with no vertical scroll range, while `overscroll-behavior:contain` blocked vertical wheel chaining to the real `.main-scroll`. The fixed-height app shell and flex/min-height ancestors were already correct.

Containment now applies only horizontally; vertical wheel input chains normally. Chromium does not similarly forward PageDown from a focused horizontal region, so the main scroll handler forwards six vertical keys only when the table region itself is focused. Descendant inputs/buttons, horizontal keys, modified keys and previously prevented events retain native behavior. No wheel interception or nested fixed-height table was introduced.

## Evidence

- Four 50-row real Electron regression cases first failed at the actual wheel-over-tbody assertion: Creators 0→0, Games 0→0, Matches 150→150, Invitations 0→0.
- After fixing wheel chaining, all four reached their bottom; keyboard PageDown then reproduced a second failure. The scoped keyboard handler resolves it.
- Final development regression: **4 passed (30.2s)**, each at 1440×680 and 760×680. Tests assert real main scroll movement, vertical visibility of the last row, pagination presence and viewport visibility on the three paginated tables, reverse wheel, horizontal wheel/ArrowRight, PageDown progression and no document horizontal overflow.
- P4 automatic search has no bottom pagination; its 50th row is checked rather than inventing a footer.
- Seven keyboard unit tests passed; typecheck and build passed.
- One bounded independent review accepted the CSS and keyboard changes; its two test corrections (vertical-only row visibility and mandatory pagination existence) were incorporated.

Evidence roots: `desktop/output/playwright/internal10-scroll-red-20260910/`, `internal10-scroll-green-20260910/` (intermediate keyboard failure), `internal10-scroll-green2-20260910/` (pass).

Test data is synthetic: isolated HTTP GET fixture seeds expanded through test-only IPC into 50-row pages. Games normally uses a smaller page size; its 50-row response is an explicit layout stress fixture. No server records are created. All HTTP writes and non-fixture origins are blocked. Physical touchpad hardware is not tested; native Electron wheel events exercise its equivalent scrolling path.
