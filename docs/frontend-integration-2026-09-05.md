# Interaction-first client source handoff — 2026-09-05

## Source integration

- Frozen frontend baseline: `4e72084eda3ed929cb2eaa95e5432e7bc4f421d0`.
- Client refinement: `371a434c06fe64a01b1e81234a4d56cbfc12f958` on
  `codex/task-centered-workspace` (48 UI, presentation-test, and design files).
- Integration merge: `3e40ec01aafdc52579f5cbd2a43930906d64c2a2` on
  `codex/ec2-ip-deployment`.

The integrated `macos/` tree is identical to the frozen client commit. Its
`backend/` tree is identical to the previously verified cloud source
`c8849ebfbc3a056b35277cb27bc0d70dc2918ad0`; no backend change was introduced.
The earlier frontend baseline is also included in the merge. One overlapping
release-test insertion was resolved by retaining both public-IP HTTPS checks
and app-icon packaging checks. Release builder/verifier implementations match
the previously published cloud-client source `888f1f2`.

## Verification

- The frozen source passed `swift test --package-path macos -Xswiftc
  -warnings-as-errors`: 284 tests / 37 suites.
- The same command was independently rerun in the integrated workspace: all
  284 tests / 37 suites passed again.
- Independent read-only review of `4e72084..371a434`: GO, no blocking normal-flow
  regression in drafts, recipient selection, preview/send confirmation, or
  navigation. No backend, API, Core, or script edits in this refinement itself.
- Merged release-script contracts passed, including public-IP origins, icon
  validation, simulated Developer ID/notary handling, and ad-hoc packaging.
- `git diff --check` passed. The source worktree was committed without unrelated
  edits or changes to other worktrees.

See the [frontend acceptance record](../macos/Design/interaction-first-refinement.md)
for the author's native Demo walkthroughs and their limits. No real email or
live-provider analysis was initiated for this source-only integration.

## Deferred minor feedback

When a Match result retains selected rows but becomes read-only or is refreshing,
the visible **Clear** button can remain enabled while its callback declines the
action. This is a feedback issue, not a send-authority bypass or data loss. It
does not block the agreed internal Demo handoff; writable-state clearing works.
Locations: `BatchOutreachBar.swift` and `MatchResultView.swift`.

## Release boundary

This handoff uploads source branches only. It does not redeploy EC2, change the
running backend (`660e662`), update `main`, replace the existing `0.1.2` DMG,
or publish a new release. A future client packaging pass should build from the
integrated source with `SERVICE_BASE_URL=https://44.233.174.193`.
