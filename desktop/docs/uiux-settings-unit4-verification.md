# UI/UX unit 4 — focused Settings controls

## Scope

Service identity, configuration status, test and credential entry share one
named control group. Visible buttons no longer repeat the adjacent provider
name; accessible names retain it. Test is visually secondary, X keeps the more
specific Test usage access label, and Steam's testing restriction remains.
Nonempty operation/test status is still displayed; empty status rows lose only
their margin. Credential editor, confirmation, failure/reload, secret clearing
and disabled conditions are unchanged.

At supported narrow desktop widths, Settings categories remain beside the
current panel instead of becoming three rows above it. Labels and Shared badges
wrap when needed. Below 700 px the prior stacked fallback remains. Existing
category selection, per-category scroll, pending edits, recovery, return and
keyboard behavior are unchanged; no configuration defaults or API changed.

## Verification

- New red/green test verifies provider identity/status/action grouping, short
  visible labels with full accessible names, disabled testing during credential
  entry, shared confirmation and cancel preserving the draft without a write.
- Five relevant files / 42 tests passed. Full regression: 124 files, 1260 passed,
  5 environment-gated skips; actual creator-search DTO gate enabled. Typecheck,
  build and diff whitespace checks pass. Existing large-bundle advisory remains.
- Final native Electron read-only audit: 1 passed, 11.2 seconds. Zero HTTP writes
  or renderer exceptions. All screenshots have no document horizontal overflow.
- Native Settings paths: keyboard Workspace -> Services; open/close credential
  editor without typing a secret; edit refresh interval, leave category/return,
  confirm shared impact then cancel; try Library, keep editing, verify draft,
  restore original interval locally. No settings mutation was submitted.
- All seven categories inspected at 760 px after their relevant content loads.
  Geometry verifies categories and current connection panel remain side by side.
  Dark Services and extra-large 20 px text verified; local font preference is
  restored afterward. Reduced-motion was enabled throughout.
- Main agent visually checked desktop Services, narrow Workspace/Services/
  Collection/Auto-refresh/Email/Updates/Appearance, confirmation and unsaved
  dialogs, dark Services and extra-large text. Disabled tests reflect unconfigured
  synthetic services, not a new availability restriction.

Final evidence:

`desktop/output/playwright/uiux-settings-unit4-acceptance-20260910/uiux-readonly-native-read-only-current-task-visual-audit/`

Earlier baseline and all unit evidence remain separate. This final audit also
walks the previously verified Creator, Library, Match and Outreach read-only
paths including Outreach edit return, read failure/recovery and filtered empty.

## Limits / final handoff

Real secret replacement, service tests, shared saves, SMTP tests and email sends
were deliberately not executed. Component regression covers pending mutations,
uncertain saves, authentication handling, draft guards, SMTP warnings and lazy
reads; native validation only enters/cancels the relevant safe local states.
Screen-reader testing beyond ARIA/keyboard remains unverified. All native work
uses isolated preferences and synthetic 18093, not user or production activity.

The four planned UI/UX units are implemented; unit 4 awaits independent review
and source commit authorization. No new package/upload occurred. The coordinator
owns final integration and any subsequent demo package/publication decision.
