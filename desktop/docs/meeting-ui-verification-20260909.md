# Meeting UI changes — verification in progress

## Scope

- Creator records share Profile / Invitations, with activity-scoped history and retained navigation.
- All four platforms support Library discovery, separately from real-time configuration.
- No arbitrary new template editor; existing snapshots remain readable. Final game-bound backend catalog integration is pending.
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

This is a progress record, not release approval. The coordinator owns final integration and upload.
