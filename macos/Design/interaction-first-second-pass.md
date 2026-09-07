# Interaction-first refinement · second pass

## Scope and assumptions

The current client already removed page slogans and most tutorial paragraphs. This pass targets repeated text inside components and replaces explanatory work with useful controls. It preserves the visual identity, actual profile and match evidence, editable content, send confirmations, errors, version checking, and analysis timing.

The existing English interface remains English. No backend, API contract, delivery rule, or production data is changed. Local performance fixtures belong to a separate investigation; their existence is not evidence that window-drag performance has been fixed.

## Main task path

Add a profile → browse its identity and facts → select a game → review matches → explicitly choose recipients → write and review the actual message → confirm sending → inspect the relevant campaign deliveries. Navigation remains freely accessible; this is not a forced wizard.

## State and hierarchy

| State | Focus / primary action | Visible context | On demand |
| --- | --- | --- | --- |
| Empty Library | Add Profile / Browse All | Current profile type or filter | Analysis activity |
| Profile overview | Identity, key facts and fit | Source provenance and uncertainty | Detailed analysis, raw contact sources |
| Match results | Creator fit and selection | Metrics and actionable evidence dimensions | Full reasoning and alternatives |
| Writing | Message fields / review | Selected recipients and unsaved state | Address editing and response labels |
| Reviewing | Actual personalized email / send | Recipient address, position in the batch | Previous/next recipient preview |
| Campaign | Relevant deliveries | Overall counts and chosen filter | Individual email and diagnostics |
| Settings | The selected setting | Current state and its action | Connection diagnostics |
| Failure | Specific error / recovery | Successfully loaded or edited content | Additional diagnostics |

## Transition rules

- Content is not shortened merely because it is long. User-authored text and decision evidence remain complete and accessible.
- Compact fact rows replace repeated headings only when the value is a short fact; narrative fields retain paragraph space.
- When a result contains only Other Matches, those real candidates are the primary group rather than an empty Recommended section followed by a collapsed list. Mixed results retain the user's disclosure preference.
- A named disclosure is preferred to an explanatory sentence. Unknown icon-only controls and hover-only essential functionality are not introduced.
- Required-field errors sit beside their fields. Hidden optional sections must reveal or clearly signal their own validation failures.
- Preview navigation changes the selected preview, not the delivery rules. Moving back keeps the draft and explicitly selected email addresses.
- Campaign filtering is local, retains an All route and does not mutate delivery state or resend anything.
- Workspace connection diagnostics are expandable. Disconnect still requires its existing consequence confirmation.
- Settings uses one observable presentation owner for its adaptive form. Disclosure and confirmation changes invalidate the visible section immediately; they do not rely on switching categories to refresh a previously captured value. Full-row disclosure buttons expose Expanded / Collapsed state and suppress expansion animation under Reduce Motion.
- Update checking has one local activity indicator, and failures remain visible. Manual installation and GitHub access requirements stay next to the download action.
- Workspace entry omits only the exact normal-state hint already expressed by its field and Connect button. Unfamiliar messages and errors remain verbatim.

## Verification

Strict validation: `swift test --package-path macos -Xswiftc -warnings-as-errors` passed **334 tests in 45 suites** on 2026-09-07. This total includes five separately scoped, opt-in local performance-fixture tests; it is not a frame-rate benchmark. `git diff --check` passed. No backend or generated API changes are part of this UI pass.

Root source integration on 2026-09-07: the frozen UI commit `5e7cd2d` was cherry-picked onto `de04415` as `87313a6`. The same strict command passed **329 tests in 44 suites** without the five uncommitted performance-fixture tests. The integrated client sources exactly match the frozen UI commit. Backend, API contracts, Core/API modules, operations, and release scripts remain unchanged from the root baseline. This delivery uploads source only: it does not rebuild or replace the published 0.1.3 package, create a release, or change the live update manifest.

The bounded independent source review returned GO with no normal-workflow blockers. It checked explicit multi-email recipient selection, preview invalidation and send confirmation, per-email preview navigation, local campaign filtering, and observable Settings disclosure/confirmation state. This review did not repeat native UI or performance measurements.

Native Demo walkthrough on the local M4 / macOS 26.6.2:

- Profile: Overview still exposes collaboration risks. Sources & Analysis displays one AI group marker and compact chapters; short source facts share rows while descriptions remain complete. A note survives section changes, then Save returns to the summary. Contact Source opens inline with the raw source, accessible external-link label and full selectable URL. An intermediate accessibility-label propagation issue was caught and corrected; final AX output preserves the actual source text.
- Match: Select changes to Selected and reveals the batch action. At a narrow window width, identity, metrics, evidence controls and the bottom action bar wrap without covering the scrollable results. The only-Other, zero-selection cached failure and full-risk policies are covered by presentation tests.
- Campaign: opening from the list succeeds. Accepted shows its corresponding delivery; Awaiting response shows the sent/no-response delivery; Failed yields an empty result with a working Show all deliveries action. Narrow layout switches the filter to a menu, and Down / Return selects Accepted by keyboard.
- Composer: a creator with multiple emails remains unselected until an explicit choice. Two-recipient review shows the correct personalized first and second emails, previous/next boundaries and 1 of 2 / 2 of 2. Send opens the non-recallable queue consequence confirmation; cancelling preserves review and Back preserves the message. No email was sent.
- Composer failure: the isolated qa-journey fixture displays the complete preview error with Try Again and keeps Send disabled. Retry restores the actual recipient, subject, body and response labels before enabling Send. Back preserves the message, including a separately verified edited subject. Both test drafts were cancelled or explicitly discarded; no delivery was submitted.
- Templates: narrow layout keeps the selector above the editor. Clearing Subject places Required beside Subject and disables Save. A new unsaved template exposes validation and an Edit template route; returning shows the affected fields. Discard restores the saved template. An existing saved template can still render a draft with an empty subject, as before; this does not permit saving an invalid template.
- Empty Library: Match shows Add game without a disabled selector/submit stack. Add game navigates to the Game analysis form; no analysis was submitted.
- Software Update: the unversioned Demo reports Development build / Version check unavailable and disables Check for Updates; it does not incorrectly report that the app is current. No update network request or preference change was made during this walkthrough.
- Settings regression found and fixed: an earlier implementation changed disclosure state without refreshing the visible form, which only caught up after a category switch. Explicit observable presentation state now makes Connection details and Refresh activity open/close immediately. Disconnect opens its consequence confirmation and Cancel leaves the session connected. A temporary 14 → 15 day refresh draft opens the shared-change confirmation; Cancel preserves the draft, then restoring 14 returns to Saved without submitting anything.
- Email Settings: Sending limit opens the current value and allowed range. Send a test email opens its recipient input; closing and reopening preserves a typed local test address. That test address was cleared, and no SMTP test or send was submitted.
- Connections: Steam and Google AI Studio expand mutually exclusively; changing sections preserves a synthetic credential draft. Replace Steam opens the shared-impact confirmation and Cancel does not submit. The synthetic draft was cleared, and reopening shows an empty field with Replace disabled. Disconnect, schedule Save and credential Replace confirmations do not reappear after cancelling and returning to their categories. Final Demo was restored to a wide window at Library → Creators with no test drafts or dialogs.

Limitations: no production provider or SMTP call, no actual delivery, no complete VoiceOver traversal, and no separate Intel/macOS 14 hardware run. Campaign menu keyboard navigation was verified; Space activation of disclosure buttons was not exercised because the current system keyboard-navigation preference skips buttons, and that preference was not changed. The system Reduce Motion setting was not changed; existing motion-policy tests pass. Arbitrarily long real-world source URLs and every font-size/display combination were not exhaustively exercised. Window-drag / Stage Manager performance remains a separate unfinished investigation; these UI checks do not establish an FPS improvement.
