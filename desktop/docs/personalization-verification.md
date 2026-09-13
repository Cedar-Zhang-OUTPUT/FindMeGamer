# Per-draft personalization — internal.11 verification

## Task and state model

Primary path: inspect a prefilled draft → edit this recipient's wording → save →
preview/reopen → review sending requirements. Shared Creator records are sources,
not an equality constraint on this draft's wording.

| State | Focus and main action | Context and disclosure |
| --- | --- | --- |
| No generated values | Source-backed template preview; Edit personalization | Reusable prefill appears when supplied; missing evidence remains visible |
| Editing | Four draft-only fields; Save changes | Shared source editors remain separate; empty fields are allowed |
| Saving | Local saving feedback | Disable repeat submission; keep edits on failure |
| Saved, incomplete | Safe draft preview; continue editing | Not send-ready; no invented filler or human endorsement |
| Saved, complete | Preview; Review sending | Completion does not imply eligibility; applicable facts and recipient checks remain |
| Concurrent change | Retained local edits; Load current values | No automatic rebase or late result overwriting local input |
| Source changed | Existing draft and explicit refresh choice | Editing cannot silently acknowledge changed provenance |
| Uncertain write | Check current version | Exact revision, values, identity, context and confirmation transition must prove the receipt |

Default focus stays on preview. Four fields are disclosed by Edit personalization.
Recorded source/version details remain secondary. Switching people preserves each
person's unsaved session; explicit successful save clears only that session.

## Contract agreed with backend owner

- Same four string keys and PATCH route. Draft values allow empty strings and
  unfinished observation punctuation; bounded safe plain text remains required.
- Shared Creator values and sibling drafts are not mutated by a draft edit.
- Complete generated/sending values remain strict. Draft preview is not sending.
- firstName edits preserve all human confirmations; channelName invalidates
  following; reference invalidates enjoyed and liked; observation invalidates
  liked. No confirmation is generated or checked automatically.
- Source changes still require explicit refresh. Refresh preserves saved manual
  overrides and clears source-related confirmations; unsaved local edits are
  discarded only after the explicit warning and refresh action.
- `input.prefill_values` supplies four bounded safe strings. Work sources carry
  `evidence_kind` (`manual_note`, `metadata`, `unavailable`); historical sources
  without these new fields remain readable. No inferred human endorsement.

## Verification status

- TDD reproduced renderer override/unfinished/source-evidence save deadlocks,
  strict main response rejection, and source-equality/blanket-fact-reset readback.
- Final Vitest: 131 files passed / 1 skipped; 1347 tests passed / 6 skipped,
  60.78 seconds with two workers. Typecheck and build passed. Existing Vite
  >500 KB chunk warning remains; no timeout thresholds were increased.
- One bounded independent review found one P2: human confirmations were labeled
  with the old source channel. Fixed with a red/green test: current saved channel
  wording is displayed, and selecting the recipient reveals saved reference and
  observation separately from the original source identity. No facts auto-check.
- Real packaged `.app` → real IPC → isolated backend API and persistent PostgreSQL:
  1 passed (7.9 seconds), including different-source full edits, unfinished edits,
  per-person unsaved state, saved previews, refresh preserving all overrides,
  reload, unchanged shared Creator and siblings, and blocked qualification.
  This uses backend 14d0a6c, loopback 18743, synthetic data, no worker or SMTP.
- Same packaged app bulk-selection and four 50-row scroll tests: 5 passed
  (21.9 seconds), wide/narrow windows, keyboard and wheel; bulk remains zero HTTP
  writes. Scroll tests expand synthetic IPC rows; they are layout tests, not
  proof of backend pagination. Existing loopback 18093 is GET-only for these runs.
- First native launch timed out at 90 seconds, followed by teardown timeout.
  Retained as failed evidence; the subsequent debug run passed (17.8 seconds)
  and the normal complete run above passed. No underlying cause is claimed.
- Packaged evidence: `desktop/output/playwright/personalization-internal11-final-20260913/`
  and `desktop/output/playwright/internal11-bulk-scroll-20260913/`.
- Existing bulk-selection commits 272bffe and a59e336 remain in this branch.
  Source fix commit: f58a34f. Root owns publication; no release is published by
  this task. See the internal.11 artifact record for DMG acceptance.

No production mail, provider calls, user-data clearing or backend business-code
edits are authorized for this desktop task's verification.
