# Task 14 Implementer Report: Campaigns and Templates

## Scope and baseline

- Immutable baseline: `c3385ce28feb5220bbb110d419b497a667e2829c`.
- Required commit subject: `feat: manage campaigns and templates`.
- Production changes are limited to the six new Task 14 source files, with one
  new focused Core test file. No API protocol, DTO, OpenAPI/generated output,
  root composition, Package manifest, backend, or existing source/test file was
  changed.
- Task 15 still owns real Email Settings content and Task 17 still owns root
  composition. `OutreachManagementView` supplies the required generic
  `@ViewBuilder` Email Settings slot and a typed Campaign route without nesting
  a `NavigationStack`.

## TDD evidence

The focused test file was created before production code. The first test-only
compile exposed and corrected a fixture-label typo; the immediately repeated
RED, still before any production file existed, discovered the non-empty focused
surface and failed because `OutreachManagementModel`,
`OutreachManagementTab`, and `TemplatePreviewState` did not exist. This was the
expected genuine missing-model RED, not a zero-test pass.

The 9 deterministic tests cover:

- Campaigns as the default tab, exact insertion-variable order, and exact new
  Template CTA defaults;
- full opaque-cursor drain, backend order, first-UUID de-duplication, atomic
  failure retention, and A/B detail response/failure fencing;
- default Template selection, independent drafts, and failed-refresh retention;
- exact 300 ms clock-driven preview cancellation, exact submitted draft,
  saved-only preview, and stale failure fencing;
- canonical Save upsert and held-request single-flight behavior;
- exact Duplicate/Set Default/Delete UUIDs, canonical default enforcement,
  server ordering, and delete-refusal retention;
- exact source Delivery/key resend calls, failure/mismatch key reuse,
  double-click suppression, accepted-success suppression, and accepted resend
  ownership despite a selected-detail refresh failure.

Focused GREEN was repeated after the complete production/UI implementation:

- `swift test --filter OutreachManagementModelTests`: 9 tests / 1 suite,
  0 failures;
- immediate repeat: 9 tests / 1 suite, 0 failures.

## Implementation

`OutreachManagementModel` is a Swift 6 `@MainActor @Observable` state owner. It
atomically commits complete Campaign pages and Template lists; fences Campaign
detail and preview generations; keeps canonical Templates separate from local
drafts; locks shared Template mutations; and owns explicit, non-retried,
ambiguity-safe Delivery resend idempotency.

The native SwiftUI surface provides segmented Campaigns/Templates/Email Settings
selection, ordered Campaign rows and detail batches, required metrics and
response history, backend-gated Resend controls, offline write disabling, and a
split Template list/editor with creation, duplication, validation, variable
insertion, confirmations, canonical actions, and clear load/empty/error states.
Email send-state copy uses `Sent`; the Task 14 source has no `Delivered` copy and
does not expose match scores/ranks.

The live preview is a target-local, minimal `NSViewRepresentable` around
`WKWebView`. It accepts only the server `RenderedEmail.html`, compares exact HTML
before reload, disables JavaScript, uses `WKWebsiteDataStore.nonPersistent()`,
and permits only the initial `about:` document navigation while cancelling link
navigation. No global WebKit object, raw author HTML path, local persistence, or
new dependency was added.

## Verification

- full suite: `swift test` passed, 151 tests / 16 suites, 0 failures;
- strict build: `swift build -Xswiftc -warnings-as-errors` passed; only the
  generated FindMeGamerAPI target's pre-existing target-local permitted unused
  public-import diagnostics were emitted;
- plain `swift build` passed after the WebKit delegate's exact Swift 6
  `@MainActor @Sendable` signature was applied;
- `xcrun swift-format lint --strict` passed on all seven created Swift files;
- `git diff --check`, source literal checks, status/scope review, and manifest /
  dependency checks passed;
- safe launch passed with `SERVICE_BASE_URL=invalid://local-verification`, bundle
  identifier `com.findmegamer.desktop`, and minimum macOS `14.0`; exact launched
  PID `15262` was terminated and no `FindMeGamer` process remained.

The final commit SHA and immutable controller review-package byte count/SHA-256
are recorded in the post-commit handoff because embedding either self-referential
value here would alter the commit/package itself.

## Bounded concerns

Task 17 must compose this feature into the root and supply Task 15's Email
Settings view. Pixel tuning, external-resource policy beyond the binding blocked
navigation requirement, and defensive behavior for corrupt cursor cycles or
extreme history sizes are deliberately outside the internal-Demo boundary. No
binding internal-Demo concern is known.

## Fix round 01: preserve unsaved Template edits

Independent review identified that successful Duplicate and Set Default actions
called `adopt` and silently replaced a normal unsaved Subject/Body draft. The
fix started from `78ac2b173dd388371db7906d7f50870298ba76d8` and stayed within the
management model, Template UI, focused tests, and this report.

The first test-only focused run discovered 10 tests and produced four genuine
behavior failures: Duplicate and Set Default each contacted the API and the
model replaced the authored draft with returned canonical content. The final
regression adds observable dirty-state expectations and covers selection,
Create, Duplicate, Set Default, Delete, dirty refresh, existing/new draft
discard, and post-discard action eligibility. A second test-driven correction
captured two failures proving a clean refresh must still adopt its updated
canonical Template rather than becoming spuriously dirty.

The model now derives `hasUnsavedTemplateChanges` from the independent draft and
selected canonical Template. State-replacing actions refuse while dirty;
Template refresh atomically updates canonical data while preserving a draft that
was dirty or changed during the request; and `discardTemplateChanges()` restores
the exact selected canonical Template, otherwise the backend default/first or
ordinary empty state, without server contact. The Template list/Create and
Duplicate/Default/Delete controls are disabled while dirty. The editor shows an
unsaved indicator and a native destructive `Discard Changes` confirmation while
leaving valid Save available.

Fix verification:

- focused GREEN repeated twice: 11 tests / 1 suite, 0 failures each;
- full Swift suite: 153 tests / 16 suites, 0 failures;
- `swift build -Xswiftc -warnings-as-errors`: passed, with only the generated
  target's pre-existing scoped diagnostics;
- strict `swift-format` on all four touched Swift files and `git diff --check`:
  passed;
- safe invalid-URL launch: bundle `com.findmegamer.desktop`, macOS `14.0`, exact
  PID `23821` terminated, with zero remaining `FindMeGamer` processes.

The separate concurrent different-Delivery resend-feedback attribution Minor is
explicitly parked under the agreed boundary. Campaign, WebKit, API/DTO, root,
Package, and backend behavior were not changed. The fix commit SHA and immutable
review-package hash are reported in the post-commit handoff to avoid
self-referential package changes.
