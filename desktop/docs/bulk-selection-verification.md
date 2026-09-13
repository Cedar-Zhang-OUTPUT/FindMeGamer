# Scoped object selection — 2026-09-13

## Delivered scope

| Object list | Explicit bulk scope |
|---|---|
| Automatic Match table | Currently rendered, loaded selectable creators; excludes stale/identity-changed results |
| Legacy Match candidates | Loaded eligible candidate rows |
| Saved-list results | Loaded rows in the current saved-list filter |
| Saved-list composer | Loaded candidates only; preserves marks outside that scope |
| Local selected review | Displayed review rows, retained after clearing so selection can be restored |
| Legacy preparation people | Loaded preparation rows; preserves chosen IDs outside scope |
| Preparation known works | Loaded works; clear also removes displayed unavailable selections, select never adds unavailable works |
| Game reference works | Listed reference objects only, when selection mode already exists |

Controls show the scope and selected/total count, with Select all and Deselect all. Empty, fully selected, unavailable/current/locked and capacity states have explicit disabled behavior. Pure single-choice navigation, settings toggles, filter enums, SenderFacts and all truth/cost confirmations remain unchanged.

## State and safety

- A batch computes a complete next local draft, including alias reconciliation and explicit removal revisions, before committing it. It clones once and performs **one local journal IPC write**, not one write per member.
- No selection HTTP write or selection re-read is added to local bulk actions. Existing explicit Prepare remains the server commit boundary.
- All/deselect operate only on passed loaded scope. Outside selections and other query journals are preserved. New pages or appended results are not automatically selected.
- A batch exceeding 600 people is rejected entirely with an error; no partial selection or journal write. Works/reference selection preserves existing 100-item caps, saved lists 600.
- Existing account alias normalization, identity-change review requirements, immutable pending retry, credentials fencing and backend DTO/HTTP contracts remain unchanged.
- Selected review keeps deselected rows in its current component scope to support undo via Select all or individual checkboxes. Leaving review resets that display scope; it does not erase pending selection state.

## Verification

- TDD reproduction: new loaded-scope flow test first failed because `deselectLoaded` did not exist; passed after implementation.
- Unit/integration coverage: atomic batch single write, scope-outside preservation, no appended auto-selection, capacity rejection, account alias deduplication, stale/locked guards, review clear→restore, reference selection without editing form content, works pagination without automatic selection or truth confirmation, and saved-list marks.
- Full suite: **1329 passed / 6 skipped**, 131 files passed / one skipped, 56.60s with `--maxWorkers=2`. Typecheck/build passed. Existing Vite chunk-size warning unchanged.
- One bounded independent review: no blocking findings; an enabled-but-no-op Select all on unavailable review rows was corrected with a separate disabled condition.
- Real development Electron: **1 passed (5.1s)**. Six-person isolated HTTP GET fixture verifies keyboard bulk clear, bulk select, review clear and restore, 760×720 narrow access, persisted reload, zero HTTP writes, zero extra selection reads during bulk actions, zero page errors. No Prepare/send action is performed. Native screenshot personally inspected.
- Native evidence: `desktop/output/playwright/bulk-selection-final-20260913/`. Earlier `bulk-selection-20260913/` retains a test-locator ambiguity failure (`Select all` also matched `Deselect all`); the selector was corrected to exact matching, with no production workaround.

## Limits / handoff

The native run covers development Electron, not a new packaged release. Other object selectors have component-level interaction tests, not native full-path execution for every object type. No backend changes, online mutations, deployment, provider retries or new package version were performed. Activities loading is a separate read-only diagnosis in `activities-loading-diagnosis.md`; no causal OS Keychain conclusion is claimed.
