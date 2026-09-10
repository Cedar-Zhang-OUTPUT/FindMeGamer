# UI/UX unit 2 — Match / Library contextual headers

## Scope and transitions

Library title, Creators/Games selection and Analysis tasks now share one wrapping
header. Opening an object changes Library from a competing heading to a quiet
context label. Each retained tab reports only its presentation mode; selecting
the other tab uses that tab's mode. Returning restores the list heading without
resetting the search or replacing existing route/dirty/scroll guards.

Match utilities occupy the list heading, activity breadcrumb or creator return
row, according to the current route. New/edit/loading routes retain their
existing utility row. No utility entry was removed; hidden retained routes do
not introduce duplicate visible controls. Shared Creator receives an optional
presentation slot, not a new business state or API contract.

No backend, IPC/shared DTO, mutation, sending, task polling or release artifact
changes are included. Outreach only inherits the shared header placement; its
relationship layout and Settings remain separate planned units.

## Verification

- Two focused tests pass: contextual header placement through list/activity/
  creator routes; Library title priority and retained search across tabs/back.
- Full regression with actual creator-search DTO gate enabled: 123 files,
  1255 passed, 5 environment-gated skips. Typecheck and production build pass.
- Read-only native Electron audit on exclusive synthetic fixture 18093: final
  run passed in 6.3 seconds. Zero HTTP write attempts, zero renderer exceptions.
- Real keyboard email/work disclosure, retained expansion after navigation,
  1440 px desktop and 760 px narrow/dark states pass. All captured states have
  no document horizontal overflow. Reduced-motion preference was enabled.
- Main agent visually inspected Library list/detail, Match list/results/creator,
  dark/narrow Creator, and dark/narrow Library/Match lists/results. Header tools
  and main actions stay accessible without competing title rows.

Final screenshots and audit.json:

`desktop/output/playwright/uiux-headers-unit2-final-20260910/uiux-readonly-native-read-only-current-task-visual-audit/`

Initial screenshots remain separately under
`desktop/output/playwright/uiux-headers-unit2-20260910/`; unit 1 and baseline
evidence were not replaced.

## Limits and handoff

The fixture audit deliberately blocks mutations; native save/failure injection
was not performed. Component regression covers existing dirty/retry/return
behavior. Screen-reader testing beyond keyboard/ARIA assertions remains open.
The build retains the existing large-chunk advisory, not a build failure.
Independent review is requested before source commit/integration. No package or
GitHub upload was performed for this unit; internal.6 remains unchanged.
