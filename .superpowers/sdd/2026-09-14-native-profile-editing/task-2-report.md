# Task 2 — native profile editing

Implemented the shared native editor for Game and Creator Profiles in the common ProfileSheet (Library and Match entry points). Standard grouped facts / analysis / Brief controls use the backend field catalog; list fields use one item per line. Save and Cancel remain fixed below the scrollable content. Contacts and notes keep their separate acknowledged action, with the profile editor disabled while a contact draft is dirty.

## Interfaces and behavior

- APIService adds `profileEdit(type:id:)` and `saveProfileEdit(type:id:patch:)`; OpenAPIService calls generated `getProfileEdit` / `updateProfileEdit` through existing authentication middleware. No generated Swift output was hand-edited. The handwritten operation-name inventory and pinned backend digest test were updated for the approved schema.
- Core adds ProfileEditValue / Field / Document / Patch and observable ProfileEditorState. Inputs remain local until Save; patches contain edited fields and explicit resets only. Required validation applies only to changed values, so unavailable unchanged source fields cannot block unrelated edits.
- Single-flight Save disables mutations/dismissal. Conflict retains input and requires a fresh read/review. Unknown write outcome requires read reconciliation of desired values plus override/reset state before another explicit Save. No automatic repeated PATCH.
- PATCH acknowledgment immediately marks the draft saved. ProfileSheet refreshes effective detail separately; a failed refresh reports “saved, refresh failed.” Parent Library and selected Match refresh afterward without global settings/history reload or navigation replacement.
- Profiles/cards retain profileRevision and typed manualOverrides; MatchResult retains nullable snapshot/current revision comparisons. Known differences show a historical-results notice; unknown versions are not called changed.
- Manual source facts and analysis/Brief claims display Manual provenance; stale Creator detail retains only manual values and hides source content. Manual inference is not labeled AI inference.
- Demo service has the same typed catalog and revision checks, local persisted overrides, reset-to-frozen-source behavior, and metadata preservation across Favorite/contact operations. Demo storage remains in memory, matching existing Demo behavior.

## RED / GREEN evidence

Commands run from the worktree `macos` directory:

1. `swift test --filter ProfileEditorStateTests`: RED because draft types/state were absent; GREEN 4 tests after implementation (local draft/reset/cancel, conflict read-before-retry, response-loss reconciliation, failed read blocking retry).
2. `swift test --filter ProfileEditingServiceTests`: RED because editor service methods/Demo conformance were absent. `swift test --filter 'ProfileEdit|staleCreatorRetainsManual'`: GREEN 9 tests, including existing wire regression plus actual authenticated GET/PATCH JSON text, list, null source, 409, Demo save/reset for both types, and stale/manual presentation.
3. `swift test --filter ProfileRevisionTests`: RED missing comparison model; covered GREEN in final suite.
4. `swift test --filter demoEditsBothTypesAndResetRestoresSource`: RED found Favorite dropping manual metadata and unedited Demo source claims being reconstructed; corrected to preserve metadata and original source sections. Covered GREEN in final suite.
5. `swift test --filter unavailableRequiredSource`: RED blocked unrelated changes with absent required source; changed validation to edited fields only. Covered GREEN in final suite.
6. `swift test --parallel`: initially identified stale 42-operation catalog / old schema digest assertions (3 issues). Updated against verified `shasum -a 256 backend/openapi.json`. Final GREEN: **340 tests in 48 suites passed**, build 11.07s, tests 0.301s.
7. `swift build`: successful. `git diff --check`: clean.

An intermediate build was invalidated by a test-file edit while compilation was running; the subsequent full run above was clean. Generator nullable-schema warnings are preexisting and remain unchanged.

## Handoff / remaining integration

- Root owns the actual Demo CUA walkthrough and any packaging. No CUA, app relaunch, real workspace key read/write, provider calls, email sends, production actions, or backend source changes were performed by this task.
- **Confirmed backend follow-up:** stale editor GET/PATCH currently exposes source through `edit_document`. Root accepted Task 3 correction: source_value null and nonmanual effective editable values empty when stale; manual values remain. Native editor honors those fields, and its changed-only validation is ready for this contract. Detail filtering is already implemented. Do not claim end-to-end stale editor closure before that backend change.
- Root-owned untracked maintenance/provider/acceptance docs were not staged.

## Review fix round 1 — delayed refresh vs contact drafts

Fixed the Important review finding: the asynchronous post-profile-save read could finish after Done and contact typing, reset manualDraft, and silently mark the new draft clean. ProfileSheetState now preserves a dirty contact draft when accepting profile detail, rejects refresh replacement while a contact save is in flight, and uses a generation token to reject older reads. A newer profile-save acknowledgment starts a new generation; contact-save start and acknowledgment invalidate outstanding profile reads. The same token fences obsolete refresh-error messages. Save acknowledgment still does not wait for refresh.

Focused regression evidence, from `macos`:

- RED: `swift test --filter delayedProfileRefreshPreservesNewContactDraft` reproduced 2 assertion failures: typed notes became `Existing private note`, and hasUnsavedManualChanges became false (build 11.77s).
- Additional RED: `swift test --filter delayedProfileRefresh` failed compiling the absent generation API before implementation.
- GREEN: `swift test --filter ProfileFieldCoverageTests` — `Build complete! (8.59s)`; `18 tests in 1 suite passed after 0.006 seconds`. Covers dirty input during pending read, older read after newer profile refresh, and delayed read during/after an acknowledged contact save, alongside existing contact behavior tests.
- `git diff --check` clean. No whole-suite repeat, CUA, Keychain, backend or unrelated feature changes in this fix round.
