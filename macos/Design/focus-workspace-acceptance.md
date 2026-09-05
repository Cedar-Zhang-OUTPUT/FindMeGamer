# Focus Workspace acceptance

Date: 2026-09-05. Scope: the native macOS client on `codex/task-centered-workspace` and its in-memory Demo. No live provider credentials, SMTP delivery, backend deployment, or database changes were made.

## Implemented experience

The main path is game selection → matching → creator review → recipient choices → message → resolved preview and confirmation → delivery follow-up. Library is the supporting research workspace, not a wall of unrelated dashboard modules. Profile evidence, completed history, response labels, and individual provider settings are discoverable secondary layers.

Business state is expressed through explicit presentation types (`MatchWorkspaceFocus`, `OutreachComposerJourney`, `AnalyzeWorkspacePhase`, profile and settings sections) instead of independent booleans for every stage. Long-lived models own drafts and server state. Narrow and wide presentations keep the same editor subtree where focus preservation matters.

## Native walkthrough performed

| Area / state | Observed behavior |
| --- | --- |
| Library, populated | Type/search/favorites and profile cards are directly available; page chrome no longer pushes the first rows offscreen. |
| Library, empty search | Entering `no-match-demo-xyz` shows a contextual empty state and Clear Search, preserving the typed query. |
| Analyze, editing and invalid input | Inspector reserves its own column instead of covering Library. Return submits. An invalid URL stays in the input with a nearby validation error. |
| Analyze, existing profile | Submitting an existing YouTube channel shows Already in Library with Open and Reanalyze choices. |
| Match, choose and submit | Selecting Neon Harbor reveals Find creators and the no-email consequence. Accepted work becomes the current task; the user explicitly chooses Review creators. |
| Match, processing | The opt-in QA scenario visibly enters Screening. Leaving for Library and opening a profile remains possible; background work does not force navigation. |
| Match, results | Recommended and other creators remain separate. Selecting two creators produces an accurate two-recipient composition summary. |
| Composer, ambiguous contact | Continue remains disabled until an address is explicitly selected. The second Tactical Cedar address was selected, not silently replaced by the first. |
| Composer, back and edit | The selected address and custom subject survive Recipients → Message → Back → Message. |
| Composer, preview and send | Review displays the chosen address and personalized subject. The confirmation states the recipient count and sending consequence. Local Demo Send Now creates the campaign and returns to the result. |
| Composer, failed preview and retry | In `qa-journey`, the first valid preview fails visibly, Send remains disabled, and Try Again produces the correct personalized preview without replacing the draft. |
| Composer, final typography | Screenshot inspection confirms separate salutation/body/signature paragraphs and a bold game name in the native preview. |
| Match, accepted send | The result displays the submitted summary. The sent Indie Orbit row changes to Outreach: Sent and Resend; its new-recipient checkbox is absent. |
| Campaign, completion | The newly created campaign appears alongside the seeded campaign with two sent messages. |
| Empty workspace | Empty Campaigns offers Find creators, which opens Match. Match explains the missing game prerequisite. Empty Library offers Analyze Profile. |
| First profile and return | From `empty-library`, submitting a new YouTube URL creates a profile, shows it in Library, and switches the inspector to its completed activity. Edit Source returns to the exact previously submitted URL. |
| Template, narrow layout | At approximately 699-point window width, with the main sidebar still present, the subject remains editable and the footer wraps with Save and Discard visible. |
| Template, sidebar changes | Hiding/showing the sidebar preserves the exact edited subject and keyboard focus; the editor expands/contracts without its old clipping problem. |
| Library, responsive input | With `Tact` focused in the wide search field, narrowing to about 730 points keeps the same field focused. Typing `ical` immediately produces `Tactical`; expanding again also retains focus. The narrow layout shows type/favorites on one row and search below. |
| Settings, responsive disclosure | Narrow category picker and wide category rail both work. Crossing the width breakpoint retains the expanded Google AI Studio section and focus in its credential field. No credentials were entered or changed. |
| Profile, overview | Creator summary, decision context, risks, and the complete-brief entry are readable without displaying every field at equal priority. |

Issues discovered during this walkthrough were corrected: unbounded detail geometry clipped top/bottom content; template action rows needed an intrinsic-height adaptive footer; native email Markdown parsing collapsed paragraph whitespace; Demo send acceptance did not refresh the exact match's outreach snapshot. The geometry/footer fixes were rechecked in the GUI. Later changes are separately covered by regression tests below and must not be confused with completed visual rechecks.

## Automated regression coverage

The Swift package suite covers existing networking/domain/coordinator behavior as well as the added presentation cases:

- Match focus, stable creator selection, same-game submissions with tied timestamps, server-order history, and disabling write actions on retained but stale results.
- Explicit recipient/message/review navigation and its dependency gates; template preview retry without discarding unsaved text.
- Profile section coverage and dirty contact drafts; settings retain their existing mutation and offline safeguards.
- Contextual Library empty states and Analyze transitions. Old active/failed requests remain visible; a request already shown does not collapse merely because it completes.
- Native email paragraph and inline emphasis/link preservation.
- Demo template and recipient HTML share an escaped inline-Markdown renderer; raw tags remain literal and non-HTTP(S) links are not emitted.
- Opt-in Demo scenario parsing, ordered queued/running/completed snapshots, one-time valid-preview failure and recovery, and populating an empty library.
- Demo outreach updates only the requested creators on the corresponding match; selection reconciliation makes already-sent creators ineligible.

Final run: **250 tests in 31 suites passed**, with `swift test --package-path macos -Xswiftc -warnings-as-errors`. `git diff --check` also passed. Source-structure tests are not a substitute for runtime layout or accessibility testing. The existing generated OpenAPI target handles its own generated-code warnings separately; this result is not a claim that third-party/generated sources emit no warnings under other build settings.

The final `FindMeGamer` product build succeeded. Its executable was atomically copied into `dist/FindMeGamer.app` and its checksum verified against the build output; the bundle remains configured for local Demo. After the user unlocked the Mac, the normal Demo was rebuilt and relaunched with `./script/build_and_run.sh --demo`. The QA scenario was then relaunched as a single process and its visible Screening state, navigation away to Library, and creator overview were rechecked.

Three final `TextEditor` accessibility names were added: Profile Notes, Template Message, and Composer Message. The full **250-test / 31-suite** run passed again after these changes.

After the responsive-Library and campaign-navigation corrections, the final full run passed **254 tests in 32 suites**. One preceding full run hit the existing `SettingsGate.waitUntilEntered()` yield-loop timeout in `configuredSMTPSaveRetainsFailureDraftAndSingleFlightsWithBlankPassword`; the focused Settings suite and the subsequent full run both passed. No SMTP production behavior was changed to make that test pass. Its bounded yield-loop remains a test scheduling limitation.

## Not yet manually verified

The Mac initially locked during the final QA scenario; automation stopped without attempting to bypass it. The user subsequently unlocked it. During the resumed walkthrough, native automation failed with `Sky Computer Use native pipe closed before response` when switching the profile section. A fresh observation and a reset/rebind both failed too. The app process remained present and no FindMeGamer crash report was found; this does not establish that the profile interaction succeeded. The remaining manual checks are:

- Return from browsing to a completed QA match. Processing/navigation-away and ready-result review were tested separately, not as one uninterrupted return journey.
- Recheck the corrected View campaign action and direct campaign-list opening path.
- Edit creator contacts/notes, change tabs, return, and exercise the discard confirmation in the GUI (draft logic is tested).
- Complete a keyboard-only and VoiceOver audit; switch the actual system Reduce Motion preference. Existing motion-policy tests cover the reduced-motion branch, not the full runtime experience.
- Run this revision on macOS 14 and inspect release/universal packaging. Current native walkthrough is on the available host only.

No claims are made about real matching latency, external provider success, email delivery, or production send behavior from the local simulation. See [demo-acceptance-scenarios.md](demo-acceptance-scenarios.md) for reproducible processing, recovery, and empty-state fixtures.

## Additional resumed-walkthrough findings

- The preview-failure screen initially offered two equivalent retry buttons. The error-local Try Again remains; the extra Render Preview is now shown only without a preview error. Single-recipient copy was corrected as well.
- View campaign reached the list rather than the target detail, and the original campaign list links only selected a row during QA. Both entry points were changed to a shared root-owned navigation intent consumed after the Outreach stack mounts.
- Narrowing Library while typing preserved the query but lost keyboard focus. The duplicated responsive search-field branches were replaced with one stable control subtree whose layout alone changes; four tests cover wide/narrow/very narrow layouts and count labels.
- The Library input correction was subsequently verified in both directions, including continued typing without refocusing. The final campaign-row click instead triggered the same native automation pipe failure as the profile tab, preventing tool-based observation of the destination. User-visible confirmation was requested rather than treating the attempted navigation as verified.
- A final read-only navigation review found a repeated-click edge during the cross-page transition. The Match callback now marks the request ready if Outreach is already the selected destination, so a repeated click cannot downgrade it back to waiting for an already-completed mount. The complete 254-test suite passed after this correction.
- The profile Contacts & Notes automation failure reproduced on both seeded and newly created Demo profiles. A one-second process sample showed the main thread idle in AppKit's event loop, with no busy layout loop observed. This is diagnostic evidence only, not a substitute for visual verification of that tab.

## Handoff state

The final normal Demo was rebuilt and relaunched after all code changes. Native AX and screenshot observation confirmed the Match start screen, with Choose a game and the two seeded recent matches. The app is left there for direct exploration, not in a fault-injection or empty-library scenario. The last full package run passed 254 tests in 32 suites; the final diff whitespace check passed. Campaign-detail navigation and profile manual editing retain the tool-related verification limits above.
