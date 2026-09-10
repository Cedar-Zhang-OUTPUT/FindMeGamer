# UI/UX unit 3 — current invitation focus

## Scope / state organization

On wide surfaces, the bounded invitation roster and current relationship share
one row. The detail receives most of the width; selecting a relationship no longer
puts its detail below the entire roster. At container widths up to 780 px, the
roster becomes a 190 px scrollable list above the detail. Keyboard focus remains
on the selected control; no forced page scroll or editor collapse is introduced.

Creator/work identity and all three sending/response/follow-up states remain in
each compact row. Named status chips, pressed state and aria-controls connect the
choice to the current-detail region. Filters and pagination remain visible.
Existing selection, filter, pagination, edit session, guard and server behavior
are unchanged. A pending new selection shows local loading while prior context
remains disabled. Save failures and uncertain-result recovery move beside the
current relationship. Shared read errors remain visible above the layout.

Empty lists retain Choose creators; filtered emptiness retains the selected
relationship. Response and send-history evidence, qualification, manual response
requirements, stale revisions and retry restrictions are not removed or changed.

## Verified

- Four new presentation tests: list/detail relationship, retained drafts across
  selection and cancel, uncertain save recovery with locked choices, empty start,
  and pending selection context (some tests cover multiple behaviors).
- Full regression: 124 files; 1259 passed, 5 environment-gated skips. Actual
  creator-search DTO gate enabled. Typecheck and build pass.
- Native Electron acceptance audit: 1 passed, 13.5 seconds, on exclusive synthetic
  18093 with all non-GET HTTP requests blocked. Zero write attempts, zero renderer
  exceptions, no document horizontal overflow in all captured states.
- Desktop geometry asserts list/detail aligned side by side. Narrow geometry
  asserts bounded roster and detail entering the first viewport.
- Real keyboard selects the second invitation. Edit progress -> Creator detour ->
  Back preserves the unsaved Notes value; Cancel clears only local test edits.
- A locally blocked invitation-detail GET produces visible error/disabled edit
  controls; Refresh invitations restores access after unblocking. Accepted filter
  returns an empty list while retaining selected detail; clearing restores 6 rows.
- Native 760 px light/dark, keyboard, reduced motion, edit, return, read failure,
  recovery and filtered-empty paths inspected. Main agent visually checked wide
  roster/detail, retained editor, narrow normal/error/empty and dark screenshots.

Final evidence:

`desktop/output/playwright/uiux-outreach-unit3-acceptance-20260910/uiux-readonly-native-read-only-current-task-visual-audit/`

Includes audit.json and named screenshots. Earlier unit evidence is preserved.

## Test diagnostic / limitations

The initial native detour assertion used getByLabel, which failed to resolve the
retained Notes field although the accessibility snapshot and native inspection
showed its value intact. The final audit locates the textbox by accessible role
and name and passes. Failure cleanup initially hit the app's native unsaved-close
guard; diagnostic test instances were isolated/disposable. The harness now kills
only its own Electron child on test failure, preserving original test errors.
Product close protection was not changed. No user window or production task was
terminated, and no real data save or email was attempted.

Uncertain-save and loading injection are covered by component tests; the native
fixture cannot safely inject a committed write response. Native failure coverage
is read-only. Screen-reader testing beyond ARIA/keyboard remains unverified.
The existing bundle-size advisory remains. No backend, API/IPC, contract, send
semantics or package artifact changed. Independent review is requested before
commit; Settings is still the separate next unit.
