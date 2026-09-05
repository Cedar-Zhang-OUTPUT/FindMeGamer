# Interaction-first UI refinement

## Scope

This pass removes repeated instructional copy and reorganizes existing client information around actions. It does not change backend code, generated API code, public contracts, Core models, delivery rules, recipient selection, or shared-setting semantics. Existing visual assets and reduced-motion policy are retained.

The design assumption is that Library, Match, and Outreach are a connected workflow, not a mandatory wizard. Experienced users can still enter any section directly. Critical consequences, uncertain data labels, errors, and recovery actions remain visible when relevant.

## Main path and states

Library → game selection → matching → creator review → explicit recipient choice → message → rendered review → send confirmation. Profile inspection and editing remain available alongside this path.

| State | Main focus and action | Supporting information and disclosure |
| --- | --- | --- |
| Empty Library/Match | Analyze Profile or Add game/creators | Directly opens the relevant analysis form. No tutorial paragraph or automatic submission. |
| Analysis request | Source URL and Analyze Profile | Type selector, shared destination, local validation. Activity opens after submission and remains accessible after completion. |
| Profile Overview | Positioning, fit, and collaboration risks | Source metrics appear on Overview; remaining fields are grouped under More Details. Analysis timestamps are in Analysis Details. |
| Contacts | Email choices, purpose, availability, notes | Edit explicitly opens the manual editor. Sources and uncertain metadata remain accessible. |
| Profile editing | Current fields and Save | Draft survives section changes. Cancel confirms discarding edits; failed saves keep input; successful saves return to summary. |
| Match start | Game selector and adjacent Find creators | Recent matches form a quiet list. Empty-state add actions navigate directly to Library. |
| Match processing | Current game and actual stage | User may leave. Completion offers Review creators without automatically opening results. No invented progress percentage. |
| Match results | Creator fit and selection | Content/Audience/Performance open the corresponding evidence. Selection reveals the batch action bar. Full evidence and risks remain available. |
| Compose recipients | Explicit email choice when multiple addresses exist | Purpose, source, and verification remain visible. No automatic first-address selection for ambiguous recipients. |
| Compose message | Subject and native text editor | All supported variables insert at the current selection and support native Undo. Response labels have a noninteractive preview. |
| Review | Actual rendered recipient, subject, and body | Stale/failed previews prevent sending and expose Retry. Sending still requires the existing consequence confirmation. |
| Templates | Selected template and Edit/Preview | Dirty state shows Save/Discard; existing conservative switching guard is retained. New unsaved templates expose Edit template / Save & preview with validation. |
| Campaign | Relevant deliveries and response state | Expanded details retain complete selectable subject, body, and diagnostics. |
| Email settings | Connected mailbox summary | Edit opens configuration; low-frequency limits/test-email options expand on demand. Dirty drafts stay open across navigation and do not collapse when a field returns to its saved value. |
| Appearance | Visual System/Light/Dark options | Font-size selection has a live sample instead of explanatory text. |

## Information hierarchy and transitions

- Page headers contain the page identity and useful actions, without mandatory slogans, eyebrows, or subtitles. The sidebar has no tagline.
- Data replaces instructions: counts, actual stages, selected objects, saved/unsaved status, and errors are shown where they affect the task.
- Auxiliary information uses named controls rather than unexplained icons or hover-only entrances. Accessibility labels/help are retained even when visible prose is removed.
- Profile risks are not hidden to make the page shorter. Detailed source fields are not discarded, and grouping does not invent new scores or conclusions.
- Editing is explicit. Input remains model-owned; width changes retain stable editor identity. Completed edits return to a summary only after successful save or explicit discard.
- Shared changes, deleting stored contact information, sending email, and uncertainty labels retain their relevant warnings. Cosmetic simplification must not remove decision-critical facts.

## Verification — 2026-09-05

Automated: `swift test --package-path macos -Xswiftc -warnings-as-errors` passed **284 tests in 37 suites**. `git diff --check` passed. The diff against the starting commit contains no backend, `FindMeGamerAPI`, or `FindMeGamerCore` changes.

Native Demo walkthroughs, using only in-memory fixtures:

- Profile: full collaboration-risk section visible on the initial Overview; contact summary → edit → another section → back retains draft; discard confirmation works; successful note save returns to summary.
- Match: evidence chips open the corresponding section; selection reveals Compose and Clear; processing can continue while browsing Library; completion exposes Review creators without forced navigation.
- Composer: ambiguous recipient choices start unselected and block advancement; explicit selection survives Back; replacing selected text with a variable and one Cmd-Z restores the original text; all seven supported variables are present.
- Review: resolved recipient and personalized content match the selection; irreversible-send confirmation is shown and can be cancelled. In `qa-journey`, the first preview fails, Try Again succeeds, and returning to Message preserves the draft.
- Templates: crossing the compact-layout breakpoint preserves subject focus and text; a subsequent keystroke reaches the same field. Dirty state retains Save/Discard, confirmed Discard restores saved content, and new unsaved preview exposes validation plus an Edit action.
- Settings: appearance previews fit the narrow layout. SMTP dirty draft survives leaving and returning; manually restoring the original value keeps the editor and focus in place; only Done returns it to summary.
- Empty Library: Match Add game opens the Game analyzer; invalid URL errors stay next to the request; a valid local submission exposes Completed and Open Profile. The add route also selects the matching Library tab.

Limitations: these are local Demo and unit/presentation tests, not live provider or real SMTP acceptance. No real email was sent. Full VoiceOver traversal, IME composition on every keyboard, every display/font-size combination, and a separate macOS 14 machine were not exercised. Existing reduced-motion behavior remains covered by policy tests; this pass did not toggle the user's system preference. Passing this scope does not establish that every pre-existing navigation or backend issue is resolved.
