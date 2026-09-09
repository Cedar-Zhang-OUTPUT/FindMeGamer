# Meeting UI changes — verification in progress

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

Current combined typecheck, build, and full Vitest suite passed: 112 files / 1209 tests with `--maxWorkers=2`. Vite retains its existing >500kB chunk warning. New-backend template/Brief/initialization integration, final bounded review, and native package verification are still pending.

## Bounded independent review

One read-only review (`review_meeting_ui`) found a P2: Brief-only manual Game entry did not mark the parent activity form dirty. Fixed by including Brief in the guard. The regression also exposed a source-import leave prompt hidden behind the Game editor; it now uses the existing portal dialog, with focus restoration and keyboard containment. The complete Steam failure → manual form → Brief-only input → leave/stay → game selection path passed, alongside 22 related tests. No second general review was requested.

The later confirmed sender/template repair contract is wired explicitly: missing sender offers Email settings; changed template offers Use current template, keeping the original recipient batch and requiring explicit creation of a new composition. Old fixed text is never overwritten by source refresh. No additional frontend-only sender gate was added; final send readiness follows backend qualification.

Additional actual renderer paths passed on 56257: source disabled retains three Library results; source failure retains six results with visible YouTube failure. Ledger: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-rgunwn5k/private/union-renderer-99c22140-eead-4e99-880f-e44f7573b389.json`.

This is a progress record, not release approval. The coordinator owns final integration and upload.
