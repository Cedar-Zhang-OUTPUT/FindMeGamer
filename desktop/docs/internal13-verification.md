# internal.13 — Inline Observation evidence

Release gate: **cleared for root release handoff**. Packaged real-API save acceptance and a separate mounted-DMG process both passed on the same frozen runtime bytes.

Source chain: `4e0ebc5` (internal.12) → `50683fe` (inline evidence, provenance compatibility, unit regressions). Version/package/native test and this evidence record are in the subsequent packaging commit.

## Scope and interaction

Edit personalization → Observation → Work evidence. The three inline fields are Evidence excerpt, Verification notes, and Source URL. Existing work can be selected without a Creator-detail detour. If no works exist, Add a work in Library remains an actionable entry. Timestamp is optional and preserved unchanged.

Email wording and shared Library evidence are separate. The save button explicitly updates shared evidence, uses this work as the person's selected work, preserves all four visible email fields, and clears sender confirmations. It never confirms viewing or sends email.

Saving records acknowledged stages: work PATCH → selection update if needed → fresh draft read → verify the intended current work/evidence → preserve-values refresh. A later failure does not repeat an acknowledged work PATCH. Rejected work input stays editable; uncertain writes require read-only reconciliation. Draft and evidence buffers survive person switching. Credential changes retain the buffer but block cross-connection continuation; copying input before reopening is currently required.

The server's new `preserve_values: true` refresh mode receives all four explicit values, including empty/unfinished values and local unsaved text. The old default refresh remains unchanged. Backend implementation/deployment belongs to the backend task, commit `6d1bae69301799006ae73a932a72e3931b71f291`; this frontend worktree changes no backend files.

## Review and automated checks

One independent read-only review identified four issues, subsequently fixed: cross-credential continuation, stale clean reload overwriting new evidence, editable recovery after a definitive rejection, and changed source selection during a staged continuation. Regression tests cover these boundaries, explicit preserve request validation, per-person input retention, and staged non-replay.

Real batch reads exposed an existing decoder gap: discovery writes `source_fields.language_source`, while analysis sync writes `language_source_field`. The client now accepts both as bounded nullable read-only provenance (255 characters), never editable fields. The backend importer was inspected and the fixture was not changed to hide this incompatibility. The regression was observed failing before the decoder fix.

Typecheck and build passed. The final full suite passed **1,369 tests, 6 skipped** (133 files passed, one skipped), 60.23 seconds. A preceding full suite before the provenance fix passed 1,368 tests with 6 skipped.

## Isolated real-API acceptance

Fixture: `http://127.0.0.1:18745`, independent Postgres/compose project. Manifest is local, contains a synthetic key, and must not be published. No worker, provider, or SMTP execution is permitted. Its middleware allows only target work PATCH, selection update, and preserve-mode draft refresh. `GET /__fixture/status` reports counters; one controlled work PATCH rejection is available.

Test: `e2e/inline-evidence-native.spec.ts`, opt-in `FMG_INLINE_EVIDENCE_NATIVE=1`, explicit `FMG_INLINE_EVIDENCE_FIXTURE` and `FMG_PACKAGED_EXECUTABLE`. It uses real renderer → preload IPC → main gateway → real API, with no IPC substitution. It covers a generated draft with no overrides, unsaved four-field wording, a partial draft/no selected work, rejected work save retaining input, source/value readback, other drafts unchanged, and reload persistence.

Passed native runs:

- `output/playwright/internal13-app-verified/inline-evidence-native-pac-7c3d9-with-zero-dispatch-and-send/evidence.json`: 1 passed, 9.3 seconds test time (9.8 total), packaged PID 7088. Initially no-override generated and unsaved-target drafts advanced revision 1→2; partial/no-selected-work advanced 0→1. All values and expected work fields persisted, sibling drafts unchanged, reload identical. One controlled PATCH rejection recovered without losing evidence or wording. 74 audited HTTP requests, none outside the allowlist.
- `output/playwright/internal13-mounted-verified/inline-evidence-native-pac-7c3d9-with-zero-dispatch-and-send/evidence.json`: 1 passed, 15.4 seconds test time (16.0 total), separate mounted PID 7728. Repeated all three cases and a second controlled rejection; 73 audited requests, no out-of-scope traffic. The initial no-override state was proven in the first app run; the mounted repeat used those now-saved overrides, not a reseeded claim.
- Both runs: `dispatch_attempts=0`, `send_attempts=0`, `real_provider_calls=0`, `blocked_writes=0`; successful statuses stay succeeded and partial stays needs_repair; sender facts remain empty/invalid and send_ready remains false. Actual screenshots were inspected, including Observation immediately followed by shared Work evidence.

Failures retained under `output/playwright/` (not hidden by the successful reruns):

- `internal13-app`: startup settings-control timeout before fixture writes.
- `internal13-debug`, `internal13-app-diagnostic`, `internal13-batch-diagnostic`: real batch decoder rejected discovery provenance; screenshot shows the recoverable service error. Fixed in subsequent package.
- `internal13-app-final`: rebuilt app remained at Opening workspace; screenshot retained. App close also stalled, and system UI inspection timed out. Only the owned test process was terminated. User was asked to check lock screen/keychain/system prompts. No unsupported claim that the cause was proven.
- After the user handled the system prompt, `internal13-app-accepted` / `internal13-app-progress` reached the draft editor. The fixture's first two supposed completed drafts were actually `pending`, so the processing-state guard correctly withheld evidence editing. Fixture owner was notified; production guards were not weakened. Failed-test teardown was also caught by the app's dirty-form beforeunload protection; the test now explicitly exits only its own isolated app rather than waiting for a user-facing quit confirmation.
- Fixture owner traced this to seed setup replacing the queue-capture hook, then completed only the first two pending fixture drafts with the existing isolated MockTransport worker. Real GET and database readback confirmed succeeded/revision 1/manual_overrides empty before the accepted app run. No production changes, actual provider calls, or relaxed runtime processing guards were used.

## Accepted package

Directory: `artifacts/FindMeGamer-Electron-0.2.0-internal.13-arm64-pMPSBI/FindMeGamer-darwin-arm64/FindMeGamer.app`.

Version `0.2.0-internal.13`, bundle build `20013`. Deep strict ad-hoc signature verification passed. All 10 archived runtime files byte-match local `out/`.

ASAR SHA-256: `129ccea8dff1f6fa08ba6e3433e955f47345c56db9504c3aa7ae38add829a69e`.

Custom app icon is packaged as `electron.icns`, matching `build/AppIcon.icns`: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`.

DMG: `artifacts/FindMeGamer-Electron-0.2.0-internal.13-arm64-pMPSBI/FindMeGamer-Electron-0.2.0-internal.13-arm64.dmg`, 151,389,106 bytes; SHA-256 `b165a929d5ea5d07ce55806004c2aa916541c9f4a5702fd9ae55676fa20ae8a2`. `hdiutil verify` passed.

Mounted UI acceptance passed from `/private/tmp/fmg-internal13-mount-uQ1gHQ/FindMeGamer.app/Contents/Resources/app.asar`. No installed user app was replaced, and no GitHub release was created by this task; root owns publication.

Read-only DMG mount `/tmp/fmg-internal13-mount-uQ1gHQ` passed deep strict signature verification and matched the same ASAR hash. It was detached after the mounted-process test completed.

## Limits

Real-API UI tests used synthetic data, a 1440×1000 macOS window, and reduced-motion mode. No production work edits, real generation, sending, installer replacement, or new macOS accessibility/narrow-window matrix was performed. Unit tests cover cross-credential blocking, staged uncertainty, and changed-source rejection; native tests specifically inject a definitive work conflict, not an actual network loss after commit. Unsupported/ambiguous outcomes remain explicit readback/review paths, not automatic retries.
