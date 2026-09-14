# Native Profile Editing Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task. Preserve the approved internal-Demo boundary.

**Goal:** Restore the native SwiftUI product and make Game and Creator descriptive facts, analysis and Briefs manually editable without losing source values or changing historical matches.

**Architecture:** Keep the native baseline source schemas and existing matching workflow. Add a typed manual-override document, an editor revision and a separate editor resource; assemble effective display/matching values with explicit human provenance. The native editor buffers all changes locally until Save.

**Tech Stack:** Python/FastAPI/Pydantic/SQLAlchemy/PostgreSQL, Swift 6.1/SwiftUI/macOS 14+, Swift OpenAPI generator, pytest and Swift Testing.

**Spec:** docs/superpowers/specs/2026-09-14-native-profile-editing-design.md

## Global Constraints

- Work only in `/Users/cedar/Documents/ChatGPT/FindMeGamer/.worktrees/native-profile-editing`, branch `codex/native-profile-editing`, baseline `97bcd95`.
- Preserve acquired source, platform identity, email enhancement, current production, the v2 branch and existing releases.
- English UI; no raw JSON editing; no model requests or emails during Save; no write per keystroke.
- Internal-company Demo: TDD and bounded independent review. Only real business-path failures, data loss, duplicate execution, clear security issues and known migration failures block closure.
- No production cutover or data reset in this implementation. Production schema 0023 is not compatible with native baseline 0007; prepare a separate-database maintenance cutover instead of a downgrade.
- Run one implementation task at a time. All agents use gpt-6-astra with medium effort. Report evidence in the plan-scoped SDD workspace; no implementer-created agents.

## Shared editor contract

New authenticated resource: `GET` and `PATCH /api/v1/profiles/{profile_type}/{profile_id}/edit`, profile_type is `game` or `creator`.

```typescript
type EditValue = string | string[];
type ProfileEditField = {
  key: string; // allowlisted stable name, e.g. facts.name, analysis.themes
  section: "facts" | "analysis" | "brief";
  label: string;
  kind: "text" | "multiline" | "list";
  required: boolean;
  value: EditValue;
  source_value: EditValue | null;
  is_overridden: boolean;
};
type ProfileEditDocument = {
  profile_type: "game" | "creator";
  profile_id: string;
  revision: number;
  fields: ProfileEditField[];
};
type ProfileEditPatch = {
  expected_revision: number;
  changes: Record<string, EditValue>;
  reset_fields: string[];
};
```

GET supplies the explicit field catalog, so source-unavailable fields remain editable. PATCH returns the same document; HTTP 409 means revision conflict. Empty string/list is clearing, reset removes an override; required display name cannot be empty. Duplicate change/reset key is invalid. Protected/nonexistent keys and mismatched value types reject the whole patch. Existing manual email/notes operations stay separate and clearly labelled; this editor does not falsely promise atomic contact saving.

### Task 1: Backend overrides, effective profile reads and immutable Match inputs

**Files:**
- Create `backend/app/schemas/profile_editing.py`, `backend/app/services/profile_editing.py` (catalog, effective projection and match context helpers).
- Modify `backend/app/db/models/profiles.py`, `backend/app/api/routes/profiles.py`, `backend/app/repositories/profiles.py`, relevant source-publication repository and `backend/app/repositories/match.py`.
- Modify the existing matching prompt/input assemblers under `backend/app/matching/` only where needed to consume manual context; do not widen source evidence validation to accept fabricated human citations.
- Create a native-unique migration after 0007, `backend/migrations/versions/20260914_native_0008_profile_overrides.py`.
- Test `backend/tests/integration/test_profile_editing.py` and effective snapshot tests in `backend/tests/integration/test_match_input_lock.py`; unit catalog tests in `backend/tests/unit/test_profile_editing.py`.
- Regenerate `backend/openapi.json` and `macos/Sources/FindMeGamerAPI/openapi.json` using the existing exporter.

**Interfaces:** Consumes baseline Game/Creator source dictionaries and validated AI claim schemas. Produces the shared editor contract above; existing detail/card responses show effective values. Source claims remain unchanged in storage. Match snapshots carry explicit manual context and source revisions, without mutating previous snapshots.

- [ ] Establish isolated baseline using `docker compose -p fmg-native-edit -f compose.test.yaml run --rm test pytest -q` from backend; capture failures before edits. Do not reuse or stop another Compose project.
- [ ] Add failing endpoint tests around real migrated PostgreSQL rows. Example assertion sequence, using fixture-owned profile ID:
```python
before = client.get(f"/api/v1/profiles/game/{game.id}/edit").json()
response = client.patch(f"/api/v1/profiles/game/{game.id}/edit", json={
    "expected_revision": before["revision"],
    "changes": {"facts.name": "Human title"}, "reset_fields": [],
})
assert response.status_code == 200
assert next(f for f in response.json()["fields"] if f["key"] == "facts.name")["is_overridden"]
session.refresh(game)
assert game.current_facts["name"] != "Human title"
```
Use the existing authenticated client fixture pattern; include both profile types, reset, blank clearing, protected identity, atomic invalid patch, conflicting revision, reanalysis publication and failure preservation.
- [ ] Run focused tests RED; implement allowlisted fields from actual source/presentation/analysis/Brief schemas. Claims map to text/list values; never expose evidence/confidence/identity editing. Keep manual data in dedicated JSONB with an integer revision; lock rows on revision checking and source publication. Human edits must not violate model-only claim limits just because the model schema uses short summaries.
- [ ] Add failing match tests: create a task before editing, edit a fact and analysis without editing Brief, create another task, and verify only the latter screening/deep-match input contains the override. Repeat with explicit Brief edits and mark human provenance. Preserve old task and recipient snapshots byte-for-byte. Source-only AI validation remains unchanged; include override sidecar context rather than inventing model citations. Show current-vs-snapshot revision difference in the native task later.
- [ ] Implement effective display and immutable matching assembly. Raw source Briefs can remain typed internally, but effective manual text/Brief context must reach both screening and deep match, with explicit Brief overrides authoritative and conflicting source content clearly labelled. New source publication increments revision, failed publication does not. Existing email enhancement and separate contacts API must still work.
- [ ] GREEN focused tests, then one full backend suite and OpenAPI export. Commit exact task files. Write report with RED/GREEN, migrations tested from 0007, changed interfaces and commands; stop for controller review rather than expanding unrelated hardening.

### Task 2: Native local-draft editor and real service integration

**Files:**
- Create `macos/Sources/FindMeGamerCore/Models/ProfileEditingModels.swift`, `macos/Sources/FindMeGamerCore/State/ProfileEditorState.swift` (use existing State directory convention if differently named).
- Modify `macos/Sources/FindMeGamerCore/Services/APIService.swift`, `OpenAPIService.swift`, `DemoAPIService.swift`, and actual domain mapper implementation as needed for generated editor DTOs.
- Create `macos/Sources/FindMeGamer/Views/Profile/ProfileEditor.swift`; modify `ProfileSheet.swift` and owning action wiring.
- Add focused Swift tests alongside existing Core model/state/service tests. Keep existing contacts/notes editor explicitly separate.

**Interfaces:** Consumes Task 1 GET/PATCH shared contract. Add `profileEdit(type:id:) async throws -> ProfileEditDocument` and `saveProfileEdit(type:id:patch:) async throws -> ProfileEditDocument` to APIService using the repository's existing ProfileType and UUID conventions. Models retain section, kind, source, value and revision. Detail refresh after Save reads effective normal Profile.

- [ ] Write state tests RED, using an actual test document and fake service call counters:
```swift
// Given one text field and one list field, edit in local state.
// Expect no API calls until Save; changes includes only edited fields.
// Reset an overridden field => reset_fields contains its key, not a blank change.
// Cancel => persisted document unchanged; save conflict => local text retained.
```
Expand this sequence into runnable Swift Testing cases before implementing. Include unknown-save-response recovery: read, compare desired fields/reset state, only then enable another explicit save; never auto-repeat PATCH.
- [ ] Add Codable/domain mapping and authenticated OpenAPI methods plus DemoAPI equivalent. Tests cover union value mapping, 409, network uncertainty, and source-unavailable fields. Follow existing generated-client plugin, no hand-editing generated Swift.
- [ ] Build grouped native editor sections Basic information / Analysis / Brief with standard text, multiline and list controls. Show Manual or Analyzed per field and `Use analyzed value` reset. Label empty source honestly. Local buffers preserve dirty input on errors; Cancel/back asks discard. Save in flight prevents duplicate Save. Contacts remain a distinct existing action, not part of this save.
- [ ] Wire `Edit profile` from common ProfileSheet used by Library and Match; refresh effective detail and parent list after success. Explain current profile vs historical Match and preserve back context. Surface snapshot revision mismatch using Task 1's metadata without relabelling old results.
- [ ] Run `swift test --parallel` and `swift build` from macos, and smoke the app in Demo mode for both editors, keyboard/save/cancel/reset/error states. Commit task files and report exact test evidence.

### Task 3: Restore provider compatibility without importing v2 workflows

**Files:** Existing DeepSeek defaults/runtime/probe modules identified with `rg -n 'deepseek-v4|deepseek-chat|deepseek-reasoner' backend macos`; relevant runtime/schema/pipeline tests; create `docs/native-provider-compatibility-2026-09-14.md`.

**Interfaces:** Preserve existing AI gateway input/output and original matching workflow; select `deepseek-flash` for all DeepSeek defaults and restored demo configuration. Keep Google/Gemini email research separate.

- [ ] Inventory differences against current v2 for DeepSeek model names, long-text fixes and checkpoint reuse. Record exact source commits and applicability; do not bulk cherry-pick source/provenance/activity models.
- [ ] Write failing focused tests before changing defaults/validators. Text fixtures slightly beyond old short-summary constraints must not fail solely for 320/322-style counts; bad field types and invalid citations still fail. Preserve bounded overall input/output protection. Check existing checkpoint tests before adapting anything: document covered behavior rather than adding a second scheduler.
- [ ] Implement only compatible provider/normal-text fixes required for the native runtime. Keep email enhancement fallback and multi-email purpose/source tests passing. No paid requests required for this task; verify provider ID against existing current implementation and official docs if needed.
- [ ] Run focused tests, full backend suite once after changes, native tests if DTO/defaults touched; commit and report. Record optional performance scheduling/health UI improvements as deferred, not additions to this restoration.

### Task 4: Local vertical slice, release boundary and handoff

**Files:** Create `docs/native-profile-editing-acceptance-2026-09-14.md`, `docs/native-maintenance-cutover.md`; add `backend/tests/integration/test_native_profile_editing_vertical_slice.py` for the reusable integration scenario. Use existing native packaging scripts only after reading their macOS skill.

**Interfaces:** Consumes Tasks 1–3 and existing analysis/match task APIs. No production writes or real mail.

- [ ] Exercise a source-backed Game and Creator through real isolated FastAPI/PostgreSQL, GET editor, PATCH, independent GET, reanalysis source publication, new Match snapshot and old Match preservation. Include contacts plus reset and concurrent edit conflict. Upstream model responses can be deterministic fixtures; label them as such.
- [ ] Run native app against the isolated API and confirm both profiles can be edited/reopened, with no key exposed and no per-keystroke cloud write. Capture concrete screenshots or equivalent native accessibility evidence where available; document any environment limit honestly.
- [ ] Have the controller perform one whole-branch bounded independent review; fix real normal-path/data-loss/security/migration issues, record defensive Minors rather than widening scope.
- [ ] Document a maintenance cutover using a new native database, backup/restore verification, compatible settings import and immutable rollback; never downgrade production 0023. New business data requires an explicit migration decision. Package/publication follows a separate release checkpoint; no implicit live switch or wipe.
- [ ] Record actual commits/tests, baseline comparison, known limitations and next release actions. Do not call local implementation a deployed release.
