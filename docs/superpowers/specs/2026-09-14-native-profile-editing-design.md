# Native macOS restoration and editable Profiles

Status: approved by the user; implementation authorized on 2026-09-14.

## Baseline and scope

- Branch `codex/native-profile-editing`, based on `97bcd95b6a5feba558a21f405ef746f4339cd5d5` (native macOS 0.1.4 release closure).
- Preserve `codex/prd-v2-foundation`, Electron sources/releases, uncommitted user files, and the current production service.
- Restore the original SwiftUI/macOS 14+ product and its Library-based matching workflow. Do not reintroduce v2 discovery, activities, four-slot drafting, or Electron navigation merely to obtain editable fields.
- Add structured editing of existing Game and Creator Profiles, including basic information, analysis summaries and Briefs. Creating Profiles without analysis and rebinding platform identities are not part of this increment.
- Internal-company Demo quality target: TDD, one bounded independent review, end-to-end verification. No multitenancy, rolling-upgrade compatibility or speculative hardening work.

## Approach selection

Recommended: the native baseline plus a small, explicit manual-override model shared by both profile types. Adapt useful later fixes individually, rather than cherry-picking the entire v2 model.

Alternatives rejected: editing raw analysis/source JSON would destroy provenance and allow reanalysis to overwrite user intent; retaining the whole v2 backend would preserve the activity/works/draft coupling the user wants to leave behind.

## Editing experience

- An `Edit profile` action is available in the existing native Profile detail, regardless of whether entered from Library or a Match result.
- Reuse the current native grouped detail layout and standard controls. Basic information, AI analysis and Brief are distinct sections in one editor; do not expose JSON.
- Scalar descriptions use text fields or text editors; tags and list claims use editable lists. The exact field mapping must come from the baseline profile schemas and presentation models, not arbitrary JSON keys.
- Game editing covers display name, description, developer/publisher and other descriptive source fields that the native UI exposes, genre/tags/languages, gameplay, themes, visual identity, audience, selling points, content hooks, comparable games, creator fit, risks and Game Brief.
- Creator editing covers display/public name and description, languages/region, content topics/games/genres/formats/style, audience and promotion-fit assessments, Creator Brief, and existing contact/notes capabilities including email purposes.
- IDs, Steam App ID, YouTube channel ID, canonical acquisition identity/URL, source citations, raw acquired media, analysis timestamps, confidence values, diagnostics and model metadata remain protected. A human correction cannot claim the model or a source verified it.
- Use source-backed/manual labels and a per-field `Use analyzed value` action. Clearing a value is distinct from removing an override; required values cannot be blank.
- Edits remain local until explicit Save. Cancel discards the local draft; navigating away with unsaved edits asks whether to keep editing or discard. No write per keystroke.
- Saving does not invoke an AI model, translate the input, submit analysis, or send email. Interface and generated analysis remain English; do not introduce language switching.

## Backend model and contract

- Retain acquired facts, analysis and Brief as source values. Store a separate typed, allowlisted override document and a revision for each Profile.
- Editable sections are `facts`, `analysis`, and `brief`; reference fields by stable schema field names, not array indexes or free-form JSON paths. A list-valued claim is replaced as a whole to avoid unstable per-item merges.
- GET returns effective values plus the source/manual provenance required by the editor. Preserve the baseline native contract where possible; update the checked-in OpenAPI and generated Swift models together for additions.
- PATCH carries the expected revision, explicit changed values, and explicitly reset fields. Validate all changes before a single atomic save. An invalid field must not partially save the rest.
- A version conflict returns an actionable conflict response; retain the local draft and offer a fresh read/review, never silently overwrite another colleague's edit.
- Save response loss is an unknown outcome: reconcile with a read before a repeat write. Do not add a new synchronization framework for this feature.
- Automatic reanalysis updates source data, preserving manual overrides. Failed analysis retains the last successful source and all manual changes. Revision checks cover changes relevant to the editor, including newly published analysis.
- Existing contact edits must participate in the editor's save/revision rules or remain explicitly separate acknowledged operations. Do not promise one atomic save across unrelated existing endpoints without implementing it.

## Matching and historical data

- New matches use effective Game Brief, Creator Brief and relevant profile analysis/facts, frozen consistently at task creation.
- Manual claims are explicitly identified as user supplied. Do not fabricate evidence references or pass them off as validated AI claims; source-only evidence checks remain intact.
- Editing an analysis field must not silently leave screening dependent only on an incompatible old Brief. Define deterministic input assembly: include relevant explicit fact/analysis overrides alongside effective Briefs in screening and deep-match context. An explicit Brief edit takes precedence for that Brief field. No hidden AI regeneration during Save.
- Existing matches, ranking explanations, recipient snapshots and sent emails remain immutable historical results. Indicate when current profile revisions differ and offer a new Match; do not retroactively rewrite a running or completed match.
- Editing from an old Match opens the current Profile with that distinction clear; returning preserves the old Match context.

## Restoration and deployment boundary

- Establish clean native and backend baselines in isolated local resources before adapting later fixes.
- Inventory current DeepSeek model configuration, schema-length fixes, evidence repairs and checkpoint-reuse fixes against this baseline. Carry over only applicable changes with tests; v2-specific services do not belong in this branch.
- Use `deepseek-flash` for restored DeepSeek calls once local configuration and supported request shapes are verified. Do not revive retired model IDs from the old release defaults.
- The restored baseline schema ends at 0007, while current production is 0023. This branch must not point old code at that database or run a blind downgrade. Give the new migration an unambiguous native-branch identifier.
- Before release, prepare and test a maintenance-window migration/cutover plan that preserves current encrypted settings and keys. Prefer a separately created target database initialized from the native branch, with explicit compatible settings import and verified rollback backup. Do not assume production is still empty merely because it was reset previously; inspect it again and escalate if new business data needs migration or would be lost.
- This design and baseline restoration do not authorize a new data reset or an immediate production cutover. Deployment follows tested implementation and an explicit release checkpoint.

## Verification and acceptance

1. Baseline Swift build/tests and isolated backend tests; record setup failures separately from product regressions.
2. Backend TDD: both profile types, scalar/list fields, explicit clearing vs reset, atomic rejection, revision conflicts, reanalysis preservation, failed-analysis preservation, contacts, and source identity protection.
3. Matching tests prove effective overrides reach both screening and deep-match snapshots, with manual provenance, while existing snapshots remain unchanged.
4. Native tests prove editor initialization, local-only input, Save/Cancel, dirty navigation, source reset, conflict and unknown-outcome recovery, and all detail entry points.
5. Real local API and native application walkthrough: analyze or seed source-backed profiles, edit each type, reopen from another session, reanalyze without losing changes, and create a new Match. Paid provider calls only within the agreed test scope; no real email delivery.
6. Before publication, verify restored backend compatibility, package/version/service address, mounted DMG startup, artifact checksums and GitHub asset upload. Do not claim a release is complete merely because source tests passed.

## Non-goals

No v2 workflow reconstruction, new discovery platforms, arbitrary source-identity editing, raw JSON editor, automatic external verification of manual claims, automatic real sending, or deletion of existing releases. No unrelated UI redesign or expansion of the bounded review cycle.
