# Task 11 implementation report

## Scope and result

Implemented the app-owned Match workflow model on immutable base
`98bf91d4270e9d1d548e708731f1aaea91ebec9a`. The model owns Game selection,
Match creation/history/retry state, exact result reads, and targeted shared-Job
updates. Matching, ranking, Creator discovery, polling, persistence, and UI remain
owned by their existing backend or later client tasks.

Changed files:

- `macos/Sources/FindMeGamerCore/Features/MatchModel.swift`
- `macos/Tests/FindMeGamerCoreTests/MatchModelTests.swift`
- this report

No existing source/test file, UI, API service, OpenAPI/generated output, backend,
Package manifest/resolution, root wiring, JobPoller, or dependency changed.

## Genuine RED evidence

Nine behavior-first `MatchModelTests` were created before production code. The
required focused command discovered and compiled the test target, then exited 1
because `MatchModel` was not in scope and `MatchStage` lacked
`matchWorkflowLabel`. The same compile also showed the dependent result-state
references could not be inferred, confirming that the tested production surface
was genuinely absent rather than skipped or satisfied by a test helper.

## Game and history loading

- Game loading sends exact `(.game, "", false, cursor, 100)` calls, passes opaque
  cursors unchanged, keeps first-occurrence server order, ignores non-Game cards,
  and commits only after the final page.
- Successful reload replaces a selected card with its canonical same-ID value or
  clears a missing selection. Held double load is suppressed; later-page failure
  preserves the committed list/selection and uses the exact required message.
- History starts at nil, drains every `hasMore` cursor, keeps the newest duplicate,
  and sorts by descending creation time then descending UUID like the backend.
- History commits merge with current model state by newest `updatedAt`; an older
  held snapshot therefore cannot erase the task returned by a concurrent Submit.
  Later-page failure preserves all committed tasks.

## Create, Retry, and idempotency

Submit and Retry set their single-flight ownership before the first suspension.
Submit uses the exact selected Game UUID; Retry validates failed/retryable status
and uses the exact source UUID. Each accepted logical attempt owns one UUID-style
key. A response-loss failure retains that key for an explicit same-target retry,
while changing Game/source creates a fresh key. Neither path automatically
retries. Success upserts the returned same-ID task or successor and wakes the
shared poller callback exactly once.

A successful Retry suppresses its still-visible failed source until a later,
newer canonical history/Job representation makes the previous attempt obsolete.
API failures preserve task/result state and expose `APIError.description` or the
specified stable fallback.

## Results and shared Job updates

- Every explicit open selects and reads the exact Match ID. A monotonically
  increasing generation prevents held A success/failure from replacing newer B.
- No-suitable and successful empty arrays use exact
  `No suitable creators found`; active/pending details remain loading. Available
  Recommended/Other arrays are stored without sorting or indexing.
- Analysis changes are ignored. Match changes are de-duplicated to the newest
  representation per ID, and stale summaries cannot overwrite a newer task.
- Known queued/running changes update directly while retaining the committed Game
  header. Terminal or unknown IDs receive one exact-ID detail read each; no Job
  path calls broad Match history. A refresh failure preserves all prior state.
- A selected targeted result update shares the explicit-open generation fence, so
  it cannot overwrite newer navigation.

The production stage policy exposes only `Screening`, `Comparing Creators`, and
`Ranking`. Runtime contract coverage verifies the model has no rank/score-named
state, and no numeric rank, score, Top N, Creator catalog, or candidate reordering
exists in the implementation.

## Verification

- Focused Match suite: 9 tests / 1 suite, 0 failures; three consecutive held/stale
  repeats also passed 9/9 each, followed by a final formatted 9/9 run.
- Full Swift suite: 124 tests / 13 suites, 0 failures.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0. Only the
  existing Swift OpenAPI generator diagnostics appeared under its target-local
  exception; new Core code compiled strictly without warnings.
- Strict `swift-format` lint, `git diff --check`, changed-file scope, unchanged
  manifest, secret, temporary-artifact, and dependency-scope checks passed.
- Safe verification used
  `SERVICE_BASE_URL='invalid://local-verification'
  ./script/build_and_run.sh --verify`, exit 0. The staged bundle contains identifier
  `com.findmegamer.desktop`, minimum macOS `14.0`, and the exact invalid verification
  URL. Exact launched PID `53147` was terminated; `kill -0` failed afterward and no
  `FindMeGamer` process remained.

The commit subject is exactly `feat: manage match workflow state`. The final
commit SHA and immutable review-package byte count/SHA-256 are recorded in the
post-commit handoff because embedding them here would change those identifiers.

## Bounded concerns

No binding internal-Demo defect is known. Task 12 owns Match UI consumption and
later root wiring. Huge histories, malicious cursors, offline persistence,
background polling changes, and defense-only hardening remain explicitly outside
Task 11.
