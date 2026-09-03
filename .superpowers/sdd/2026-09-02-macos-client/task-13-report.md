# Task 13 implementation report

## Scope and result

Implemented the preview-first Outreach composer on immutable base
`e3ff299ddefc0e94586a7757a065af25fd7c694b`. The Core model owns one logical
Match/Creator composition context, shared Template selection, send-only drafts,
server previews, explicit confirmed Send Batch acceptance, and ambiguity-safe
idempotency. The native Sheet presents that state without wiring itself into the
root application; Task 17 retains that responsibility.

Created implementation files:

- `macos/Sources/FindMeGamerCore/Features/OutreachComposerModel.swift`
- `macos/Sources/FindMeGamer/Views/Outreach/OutreachComposerSheet.swift`
- `macos/Sources/FindMeGamer/Views/Outreach/RenderedEmailPreview.swift`
- `macos/Tests/FindMeGamerCoreTests/OutreachComposerModelTests.swift`
- this report

No existing source, test, manifest, dependency resolution, API/OpenAPI/generated,
backend, Match, root, Profile, Campaign, Template-management, Settings, or polling
file changed.

## Genuine RED/GREEN evidence

The behavior-first test file was created before production. The initial focused
run exited nonzero at compile time because `OutreachComposerModel` was absent.
After correcting an independent fixture name shadow before production existed, a
second run failed only with `cannot find 'OutreachComposerModel' in scope` across
the seven real tests.

Two later mutation checks also followed isolated RED/GREEN cycles:

- editing a draft and refreshing changed the selected recipient from the retained
  second Creator to the first response item; the gated test failed two state
  assertions before selection retention was fixed;
- changing draft, Template, context, refreshing, and confirming while the first
  Send was held cleared `isSending` and made a second Send call; the deterministic
  gate test failed nine state/call/identity assertions before all composition
  mutation entry points were locked during Send.

Final focused verification passed 9 tests in 1 suite. Three additional complete
focused repeats each passed 9 tests in 1 suite. The full Swift suite passed 142
tests in 15 suites.

## Context, Template, and exact draft behavior

The model preserves first-occurrence Creator order, rejects counts outside 1...30
without API calls, selects the first default Template or falls back to the first
server item, and copies its immutable subject/body into independent send-only
drafts. Empty and failed Template loads expose the required safe states. Separate
context, composition, preview, and send generations fence late load/preview/send
success and failure.

Canonical `SendBatchDraft` construction uses the exact Match, ordered Creator IDs,
and selected Template UUID. Subject/body overrides are independently nil only when
byte-for-byte equal to the Template and otherwise preserve the exact draft. Tests
prove both subject-only and body-only overrides without any `saveTemplate` call.

## Preview identity and ordering

Only `previewSendBatch` produces recipient previews. A response becomes ready only
when every requested Creator appears exactly once with no extra identity. Server
recipient order and exact subject/Markdown/HTML are retained. Recipient selection
survives edits and refreshes when still present and otherwise falls back to the
first response. Held old context, Template, success, and failure responses cannot
publish over newer work or re-enable Confirm.

## Explicit confirmation and idempotency

Load and preview never create a Send Batch. Confirm is enabled only for the exact
accepted preview and is single-flight before suspension. The Sheet's `Send
Outreach` action only opens a native recipient-count confirmation; only `Send Now`
calls the model, while Cancel never sends.

A failed explicit confirmation keeps its preview and logical-draft key, and a
second explicit confirmation reuses that key. Editing, switching Template, or
changing context requires a new preview and key. Exact returned Match and ordered
Creator identity are validated before acceptance. A mismatch does not set
`acceptedBatch`. While Send is in flight, the View disables editing and dismissal,
and the model independently rejects draft, Template, context, and preview mutation
so a queued UI task cannot unlock a duplicate Send.

The Sheet calls `onAccepted` once per accepted batch ID and dismisses only after a
valid `acceptedBatch`. Copy describes server acceptance as queued delivery, never
as delivered.

## Native preview and system CTA

The resizable system Sheet uses native controls, horizontal server-order recipient
buttons, and a plain `AttributedString` Markdown fallback. It presents exact
server-rendered recipient name/email, subject, and Markdown. The selected shared
Template's accepted/declined labels appear in a visually separate, disabled
`System-managed response buttons` block and are never editable bindings. No
WebKit, SMTP client, local persistence, or second Template representation was
introduced.

## Verification

- focused model suite: 9 tests / 1 suite, 0 failures;
- held/fence repetition: 3 runs, each 9 tests / 1 suite, 0 failures;
- full Swift suite: 142 tests / 15 suites, 0 failures;
- warnings-as-errors build: passed; only the generated target's existing scoped
  diagnostics remained;
- strict `swift-format` lint on all four Swift files: passed;
- diff whitespace, exact scope, manifest/dependency, secret, and artifact checks:
  passed;
- safe invalid-URL launch: passed with bundle identifier
  `com.findmegamer.desktop`, minimum macOS `14.0`, and exact URL
  `invalid://local-verification`;
- launched PID `95512` was terminated exactly and no `FindMeGamer` process
  remained.

The required commit subject is `feat: compose match outreach`. The final commit
SHA and immutable review-package byte count/SHA-256 are recorded in the post-commit
handoff because embedding self-referential identifiers here would change them.

## Bounded concerns

Task 17 still owns root Sheet wiring and app-level acceptance refresh. Campaign
management, Delivery polling, Resend, Template editing, rich WebKit rendering,
draft persistence/autosave, and defensive extreme-input hardening remain outside
Task 13. No binding internal-Demo concern is known.
