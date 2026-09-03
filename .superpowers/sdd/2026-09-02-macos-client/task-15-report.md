# Task 15 Implementer Report: Shared and Local Settings

## Scope and baseline

- Immutable baseline: `98fe862f35e58073852a0fa390005bb660023984`.
- Required commit subject: `feat: build shared and local settings`.
- Product changes are limited to the seven new Task 15 source files and the one
  new focused Core test file. API protocols, DTOs, copied/generated OpenAPI,
  Package manifest, root composition, Task 14, backend, and all existing source
  and test files are unchanged.
- Task 17 still owns model construction, root composition, Email Settings slot
  injection, current Workspace metadata, and the local AppSession disconnect
  closure.

## TDD evidence

`SettingsModelTests.swift` was the only created file before the initial focused
run. After correcting one test-fixture argument-order compile typo, the repeated
focused command discovered the intended test target and failed because
`SettingsModel` and `AppearancePreferenceStoring` did not exist. The genuine
compile RED is retained in `/tmp/fmg-task15-red.log`; no production Task 15 file
existed at that point.

The focused suite then went GREEN with 9 tests. During UI implementation an
additional observation-publication regression was added first; it failed
because connection presentation stores were observation-ignored, then passed
after the production fix. Final focused runs discover 10 tests / 1 suite and
pass with 0 failures; the GREEN suite was repeated more than twice across the
implementation.

The deterministic coverage verifies local appearance persistence and restore,
mandatory interval defaults/bounds, exact SMTP draft and credential semantics,
SMTP Save/Test/Send single-flight and read fences, exact three-service order and
targeting, replacement identity/secret/failure behavior, connection mutation
fences, re-analysis canonical/draft fencing, profile-page cursor drain and
max-last/min-next activity, observable presentation updates, and injected local
Disconnect single-flight. Test credentials are canaries and are inspected only
inside fake API call captures.

## Implementation

`SettingsModel` is a `@MainActor @Observable` owner with injected API,
appearance persistence, Workspace metadata, and local Disconnect action.
Appearance uses the exact existing `appearance-mode` and `font-size` keys and
never calls the backend. Shared SMTP, service-connection, and re-analysis state
retain independent drafts and canonical responses, serialize mutations/tests,
fence stale reads, and keep plaintext replacement values out of public status
and user-facing error copy. Successful credential writes clear the plaintext
input; failures retain it for an explicit retry.

The native SwiftUI surfaces use `Form`, `Section`, system controls, semantic
styles, `SecureField` replacement inputs, explicit shared-change confirmations,
the one-real-email confirmation, mandatory bounded interval steppers, honest
profile-derived activity, and a local-only destructive Disconnect confirmation.
Only Steam, YouTube, and DeepSeek render, in that order. Offline mode disables
shared writes and network tests while leaving reads, drafts, appearance, and
Disconnect available.

## Verification

- genuine focused compile RED: nonzero because the production model/protocol
  were absent;
- final focused suite: 10 tests / 1 suite, 0 failures, repeated;
- full suite: 166 tests / 17 suites, 0 failures;
- `swift build -Xswiftc -warnings-as-errors`: exit 0; only the established
  generated FindMeGamerAPI target's target-local schema/import diagnostics were
  emitted;
- strict `swift-format` lint on all eight created Swift files: exit 0;
- whitespace, exact-scope, manifest/dependency, credential-pattern, and build
  artifact checks: passed;
- safe launch with `SERVICE_BASE_URL=invalid://local-verification`: bundle
  `com.findmegamer.desktop`, minimum macOS `14.0`, exact URL preserved, exact PID
  `50310` terminated, and no `FindMeGamer` process remained.

The final commit hash is reported in the post-commit handoff because embedding
that self-referential value in this committed report would change the hash.

## Bounded follow-ups

Task 17 must perform the already-planned composition and dependency wiring.

Nonblocking test-harness follow-up: repeated full-suite stress intermittently
surfaced the pre-existing Task 14 gate-entry assertion in
`newerCampaignSelectionFencesHeldOldSuccessAndFailure` under parallel suite
scheduling. The isolated Task 14 suite passed 14/14 in five consecutive runs,
the final full run passed 166/166, and the failure does not execute Task 15
production code. No additional internal-Demo product follow-up is known.

## Fix 01: preserve drafts during loads and require known connections

Fix 01 started from `20b2c092c31637583ce9c85d1420b48cbb02feaf`
and changed only `SettingsModel`, `ConnectionsSettings`, the focused Settings
tests, and this report.

Held-response tests were added before production edits. The first behavioral
RED discovered 13 tests and recorded 25 issues: a first SMTP load failed to
publish canonical status after typing, dirty SMTP refresh replaced all authored
fields and the replacement credential, Test ran before Steam status was known
and synthesized `configured=false`, first re-analysis load failed to publish
canonical settings after editing, and dirty re-analysis refresh replaced both
authored intervals. A wished-for shared connection eligibility query then
produced the expected compile RED because it did not exist. A second focused
RED recorded six clean-refresh failures after an edit was reverted to the exact
baseline, proving that an edit marker alone was too broad.

SMTP and re-analysis loads now separately decide canonical publication and
draft adoption. A current response always publishes its canonical baseline;
editor fields are adopted only when the request started without an unsaved
draft and no edit occurred while awaiting it. First-load and dirty-at-start
drafts remain intact and become saveable, reverted clean drafts adopt refreshed
canonical values, and the existing successful Save/Test mutation generations
still fence older reads.

Connection Test now shares one model eligibility policy with the UI: the exact
service must have known `configured=true` status, no service action may be in
flight, and its replacement input must be empty. Direct ineligible calls make
no request, publish safe actionable copy, and never synthesize status. A valid
test preserves `configured=true`; a successful initial status read clears the
temporary pre-status guidance.

Fix 01 verification:

- focused GREEN repeated: 13 tests / 1 suite, 0 failures each;
- full suite: 169 tests / 17 suites, 0 failures;
- `swift build -Xswiftc -warnings-as-errors`: exit 0 with only the established
  generated-target diagnostics;
- strict format, diff/scope, dependency, and credential scans: passed;
- safe invalid-URL launch: bundle `com.findmegamer.desktop`, minimum macOS
  `14.0`, exact URL preserved, exact PID `61647` terminated, and no process
  remained.

The fix commit hash is reported in the post-commit handoff to avoid a
self-referential report change. The existing bounded Task 14 test-fixture note
above remains unchanged and was not pursued in this fix.
