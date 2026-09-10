# Meeting UI changes — verification record

## Scope

- Creator records share Profile / Invitations, with activity-scoped history and retained navigation.
- All four platforms support Library discovery, separately from real-time configuration.
- No arbitrary new template editor; existing snapshots remain readable. Game-bound catalog decoding and current-template creation are implemented; final isolated API integration is pending.
- Campaign brief belongs to the activity. Explicit revision-checked saves preserve local input after uncertain outcomes; no Game write or automatic source/model prefill.
- Initial selections are initialized by the backend. The renderer only refreshes reads when initialization is observed; it never bulk-adds on mount.

## Actual renderer evidence (not native Electron)

Built production renderer + actual application clients against isolated API/Worker/PostgreSQL at `http://127.0.0.1:56257`, backend `28595d84805137dabbdadd31f26f9fa5b51d988b`, migration 0019. Provider/model responses are synthetic. No production permission, model-quality, SMTP, Brief or new-template integration claim is made for this pin.

Passed: four selectable platform controls; eight Library/real-time merged candidates and eight evaluations; unavailable real-time status for Twitch/Instagram; Creator opens Profile, switches to Invitations, returns to the same search; 760px viewport has no document overflow; reduced-motion preference enabled. No write request or page exception; fixture effect files unchanged. Screenshots inspected manually. Inspection revealed the old two-platform history-label fallback, corrected separately.

Latest private evidence ledger after the history-label fix: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-rgunwn5k/private/union-renderer-41af4cb7-eb2f-46fc-9992-feef5e8fb49d.json`. Credentials are not stored in repository evidence.

The first renderer attempt failed because its locator used “Open creator” instead of the existing “View creator”; the corrected script passed. Full unit run initially had 1205 passing / one failing test: an old inner Profile-tab locator needed the new Overview label. The corrected targeted run passed 14 tests. Final combined full-suite, independent review, new-backend integration, and native-package evidence remain pending.

## TDD checks

New Brief UI/client and initial-selection read-refresh tests were observed failing before implementation. Brief tests cover empty/manual input, cancel without writes, explicit activity-scoped PATCH, preserving uncertain writes and server/local conflict review, and refusing mismatched success responses. Initial-selection tests cover marker read-back, refresh without local writes, unchanged marker without repeated fetch, and preserving subsequent deselection.

Latest combined typecheck, build, and full Vitest suite passed: 113 files / 1214 tests with `--maxWorkers=2`, after the game-bound adapter, Brief-only guard, and template repair actions. Vite retains its existing >500kB chunk warning. New-backend template/Brief/initialization integration and native package verification are still pending; bounded review is recorded below.

## Bounded independent review

One read-only review (`review_meeting_ui`) found a P2: Brief-only manual Game entry did not mark the parent activity form dirty. Fixed by including Brief in the guard. The regression also exposed a source-import leave prompt hidden behind the Game editor; it now uses the existing portal dialog, with focus restoration and keyboard containment. The complete Steam failure → manual form → Brief-only input → leave/stay → game selection path passed, alongside 22 related tests. No second general review was requested.

The later confirmed sender/template repair contract is wired explicitly: missing sender offers Email settings; changed template offers Use current template, keeping the original recipient batch and requiring explicit creation of a new composition. Old fixed text is never overwritten by source refresh. No additional frontend-only sender gate was added; final send readiness follows backend qualification.

Additional actual renderer paths passed on 56257: source disabled retains three Library results; source failure retains six results with visible YouTube failure. Ledger: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-rgunwn5k/private/union-renderer-99c22140-eead-4e99-880f-e44f7573b389.json`.

This is a progress record, not release approval. The coordinator owns final integration and upload.

## Checkpoint before quota pause

Source HEAD `47af49d`. Actual production-renderer/client integration passed against frontend-exclusive `http://127.0.0.1:60016`, backend `6d8425a99d7bd050424904a1492166b14f2ee5ac`, migration `20260909_0021`. Synthetic providers only, no SMTP send. Ledger: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-3g7w9lta/private/prd-ui-db5b9304-9fb1-4410-bc6c-3ac8e47ae517.json`.

Verified activity Brief PATCH without changing the Game or old plan; stale-template repair; current Game preview without historical LIMINAL/Toki text; explicit new composition using the same recipient batch; empty/default and manual new Brief; server first-terminal-batch selection initialization; cancellation preserved across continuation and reopening; 760px viewport without document overflow. First Library batch contained three, not two: batch target is soft and existing Library results may exceed it. Tests wait for server checkbox writes and source completion rather than assuming synchronous state. Screenshots are under `desktop/output/playwright/meeting-renderer-Meeting-B-aad4d-plate-through-real-adapters/`. These are browser renderer checks, not native workflow verification.

Missing-sender test remains incomplete. The missing-name qualification showed Email settings, no Send action, and successfully returned from Email settings. The next template-repair step encountered the unsaved-changes guard. A first test assumed no guard; its follow-up alertdialog locator timed out. Latest failed ledger: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-3g7w9lta/private/prd-ui-7fff45b5-a2a2-4438-8d75-8ded9d3a1332.json`. Do not count this as a pass. Both tests closed their browser/server. Fixture helper `sender-configured` completed successfully after testing, restoring synthetic sender metadata. No real identity was configured and no SMTP was sent.

New backend `29fe65b` evidence-priority contract was read, but compatibility is NOT implemented or verified. `drafts-validation.ts` work exact decoder currently rejects the added `game_id`, `relation`, `evidence_status`, `evidence_tier` fields; the same decoder is shared by qualification/delivery source validation. Backend was asked for actual sanitized new-version DTOs, without upgrading the owned 60016 fixture. Preserve old seven-field historical snapshots while validating the new metadata explicitly. Do not claim old 60016 proves this contract.

Quota snapshot: Codex used 89%, remaining 11%; coordinator relayed user stop boundary at remaining 10%. No further broad tests/package work started. Version stays internal.3/build20003. Internal.4/build20004 is reserved, not built. Pending: finish missing-sender guard test, narrowly implement/test new evidence DTO compatibility, final combined gates, native internal.4 package/first-launch evidence, then coordinator integration/upload. No release approval has been given.

## September 10 resumed acceptance (supersedes pending items above)

User resumed the finite release work. `aecd922` accepts complete new evidence metadata while preserving old seven-field snapshots. New metadata requires all four fields, validates nullable Game UUID/relation/status and the explicit evidence-tier enum, and continues rejecting unknown fields. The actual backend `29fe65b` API-exported synthetic draft, unverified draft, composition and qualification in `.local/frontend-contract-29fe65b` (coordinator workspace) passed unchanged through the production decoders. Tests were first red (9 failures) before the compatibility change, then 29 targeted tests passed. This is real DTO decoding, not a claim that 60016 runs 29fe65b.

Missing-sender recovery passed actual renderer/API acceptance: qualification blocks sending; Email settings and Return to Match work; confirming the unsaved-changes guard opens the current neutral template; Create drafts remains enabled without fabricating sender identity. No SMTP send occurred. The guard held an old busy controller closure while the settings-return read finished; confirmation now reads the latest controller through a ref. Regression failed before this runtime fix and passed after it. Final ledger: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-3g7w9lta/private/prd-ui-6a6e1d8b-8591-4a1c-beb1-727ecd3ec74f.json`. Synthetic sender was restored with the fixture's sender-configured helper (exit 0); fixture pins remain unchanged. Neutral-template screenshot visually inspected.

Release metadata commit `64a7c87` selects internal.4/build20004. Native-package evidence and final regression results are recorded separately in `internal4-verification.md`. Only the coordinator publishes/deploys. No backend files were changed by this frontend unit.
