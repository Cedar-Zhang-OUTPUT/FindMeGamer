# Task-first UI: information reduction

Scope: the current Electron Library, Creator record/forms, Game record/forms, Settings and shared navigation/recovery controls. Existing SwiftUI screens and unimplemented Match/Outreach workflows are not reconstructed by this pass. No backend logic, API contract, provider or sending behavior changes.

## Interaction decisions

| Surface | First view | On demand |
|---|---|---|
| Creator profile | Identity summary, available facts, Edit profile | Account identity, source/manual fields |
| Email addresses | Address, purpose, validation, edit/restore | Source, evidence, raw fields, validation explanation |
| Known works | Title, type, evidence, available metrics, Add/Edit | Record provenance, previous identities, scope of the list |
| Game profile | Existing description, tags, meaningful metadata, Edit game | Source comparisons; references only when present |
| Creator forms | Required entry controls and Save | Display details, audience, notes, source comparison |
| Settings | Current values/status and the relevant action | X test scope, SMTP transport details, route details |

Repeated empty metadata panels and instructional paragraphs have been removed. Field labels, errors and consequential warnings remain. Details use native keyboard-accessible disclosures; optional does not mean unavailable. Appearance, routing and filters retain their existing state.

Source identity changes still require old/new confirmation. Historical contacts and works cannot be edited. An uncertain save preserves its original request; a known successful save whose refresh fails cannot return an editable stale snapshot. Conflict name and confirmation travel together. Credential repair invalidates stale reads and old POST replay.

## Verification

The local Electron fixture journey captures Creator profile, expanded identity, email/work panels, Game detail, connection details and narrow layouts. Screenshots are generated into the Playwright output directory and visually reviewed, not substituted with mockups.

The opt-in real-API test exercises Creator creation, replay, field conflict, name confirmation, multiple emails, hide, known-work create/edit, identity change and historical read-only behavior. It writes only synthetic records to the dedicated integration workspace and never sends mail or invokes providers.

Final verification: 458 unit/component tests, typecheck/build and all 6 packaged Electron journeys passed. Default and dark/20px screenshots were reviewed; Creator keyboard disclosures and tab navigation, 760px responsive layouts, Settings at 720px, errors/retry and return-to-edit protections were exercised. Release limitations and exact evidence are recorded in `creator-v2-unit.md`.

### Integration environment incident

The accepted 18090 API initially failed listing Creators because one existing seed email used the reserved `.invalid` domain and did not pass its existing v2 validator. Under separate coordinator authorization, the backend task conditionally repaired exactly that seed contact's email to `fixture@example.com`, preserving a rollback record. No service rebuild, database reset, backend source change, contract change or mail send occurred. Frontend E2E expectations for that seed were updated accordingly.
