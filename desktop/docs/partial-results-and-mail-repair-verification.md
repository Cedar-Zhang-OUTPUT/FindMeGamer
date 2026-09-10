# Partial results and source-incomplete mail — 2026-09-10

## Scope and state model

No backend, API contract, credential handling, default origin, provider concurrency
or real sending changes. No package/version/release change in this unit.

| State | Primary content | Action / safety |
|---|---|---|
| Search processing | Current stage and real counts | Existing stop and business retry semantics |
| Terminal search, some reads fail | Each successfully loaded complete source; previously loaded failed sources retained | Source-specific public errors; Reload results performs reads only; selection and append remain unavailable |
| All terminal reads succeed | Results plus current membership/email context | Existing selection gates become available |
| Search/history switch | New task context | Generation guards reject late data and late errors from the old task |
| Mail needs sources / generation failed | Full fixed template for this composition's exact version | Known channel retained, unknown slots explicitly unconfirmed; no invented observations; repair links go to existing sources |
| Mail pending / running | Template while the real status remains visible | Never implies terminal source failure is still generating |
| Rendered mail exists | Unmodified saved HTML | Existing send qualifications / source / confirmation rules |
| Template read fails | Local error and read-only reload | Does not invalidate composition or trigger regeneration |
| Editing | Mail plus explicitly expanded personalization form | Dirty input stays expanded/preserved; all existing save gates retained |

Search snapshots are atomic **within** each paginated source, not across all
three sources. Failure on page two does not publish a half-source or discard the
last complete one. Results/people determine the search roster; the broader query
candidate collection is never unioned into the current search's displayed people.
All three sources must finish successfully before `current=true`.

The sidebar now says Workspace linked, with a tooltip clarifying that its last
connection verification does not prove every request is healthy.

## PRD visual comparison

Main agent directly inspected P6, P7, P9 and P12.1 from PRD revision 755 under
`/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/prd-ui-audit-20260910/`.
P6 requires readable fixed text even when all personalization evidence is absent.
P7 correctly uses recipient list plus full mail, without a permanent third field
column. This unit implements those two requirements: mail first, Edit
personalization on demand, source-repair links adjacent to the missing facts.
The 50-person roster is height-bounded; narrow windows use the existing horizontal
roster. P4/P9/Library table restructuring is a separate following unit, not claimed
complete here.

Backend team independently reported that the production 50 source-incomplete
drafts had no confirmed public name, selected work/evaluation or email and that
their input snapshots equalled live source input. This client unit does not
reinterpret those missing facts as a transfer failure or fabricate them.

## Verification

- TDD first reproduced the all-or-nothing bug: a failed membership request left
  a successful match-results response invisible. New regression then passed.
- One bounded independent review found two issues: late old task completion
  clearing a new task error, and pagination inconsistency classified as network
  failure. Both fixed and covered by explicit regressions.
- Full suite: **125 files, 1279 passed, 5 environment-gated skips**, with the
  recorded actual creator-search DTO opt-in. This is not a production performance
  measurement or a new production DTO capture.
- Typecheck/build pass; existing chunk-size advisory remains.
- Real Electron test: **1 passed, 4.3 seconds**, with fresh isolated userData,
  reduced motion, 1440px and 760px windows. HTTP writes blocked and none attempted;
  zero page errors. No real provider or email calls.
- Match uses the existing isolated HTTP fixture, intentionally failing the
  membership GET: six cards remain visible, append stays disabled, read-only
  reload restores selection.
- Mail uses explicitly synthetic IPC read responses for 50 needs_repair drafts:
  full template DOM and known channel verified; no skeleton; source slots remain
  unconfirmed; editor defaults collapsed; Save changes disabled when opened;
  switching people reuses one template GET; no horizontal document overflow.
- Main agent inspected the final wide/narrow screenshots and compared their
  list-plus-mail composition with P6/P7. The complete template remains scrollable
  within its sandboxed preview; this does not claim every paragraph fits at once.

Final evidence:
`desktop/output/playwright/partial-repair-native-50-20260910/partial-results-repair-nat-636e9-stay-visible-without-writes/`

Contains partial-results.png, needs-repair-template.png, needs-repair-narrow.png,
and verification.json. A prior one-person run passed (4.8s) under
partial-repair-native-final-20260910. Initial partial-repair-native-20260910 used
an intermediate build with the old iframe title, so its locator failed; that
failure evidence is retained, followed by rebuilding and the successful runs.

## Remaining boundaries

No installed new DMG acceptance yet: this is a built development Electron run.
No live production prepare/create/send, source editing, model generation or
backend repair was performed. Missing source evidence still needs genuine user
confirmation and the existing explicit refresh flow.

Separate read-only performance diagnosis found POST-then-full-selection refresh
for each toggle, serial stop/freeze/template phases in Prepare, and serialized
credential reads before fetch. Plain draft preview is local iframe rendering;
sending review is a distinct server qualification request. These request costs
are not changed or measured as production timings in this commit.
