# C / P9 — invitation and collaboration records

**Resumed and verified (2026-09-09).** User restored execution and64692exclusive lease. Both paused failures are fixed: fallback queries only selected tabs, and the renderer test captures a nonoptional page before polling. Existing regression12/12, typecheck/build pass. Built renderer1/1 passes3.7s/4.5s runner:38GET+1actual notesPOST, revision6; selected-tab/opening-button focus return, retained edits/filter/Creator detour, Cancel, blank sourced-response gate,760px/135%font/reduced-motion/nooverflow. All runtime error counters0; controls/events unchanged. Full details in `activity-collaboration-verification.md`; historical failure evidence remains in the pause handoff.

Approved ordered continuation after P7 `047734f` (main integrated identical desktop tree as86f3e84). Consume immutable C `9259d448819e076557e5bb5228104b63fcae543b` without backend changes. Root fully read the contract, schemas/routes/repository and `docs/analyze-frontend-fixture.md`. The newly authorized exclusive64692 fixture is pinned to5706ad7/actual0019 and includes C;62611 is finished and must not be upgraded or reused for C.

Task path: Activity → Invitations → selected relationship → record an actual response or adjust progress/notes → saved state and retained history. Creator profiles expose their associated invitation history read-only. No response is inferred from SMTP, clicks or another Activity. No inbox sync, email follow-up, new send or Analyze action is added here.

| State | Focus / primary action | Kept context and disclosure |
|---|---|---|
| Empty / initial | Invitation list / return to choose people | No GET creates tracking; filters have explicit All |
| Browsing | Selected relationship / record response or edit progress | Stable list/filter/page; compact sending/reply/progress labels |
| Editing | Current changes / Save | Notes retained; actual reply source/time required only in response form |
| Saving / uncertain | Original request / inspect or retry same request | Frozen revision/body/key; no new revision or guessed receipt |
| Conflict | Current record beside retained edits / explicit rebase | Never automatic latest-revision resubmission |
| Complete | Saved result / next relationship | Older sourced responses and frozen mail remain discoverable |
| Creator detour | Creator detail / return | List selection/filter/page/scroll and local edits remain owned by Activity |

Default display: relationship name, current reply/progress and one selected editor. Sending details, original recipient memberships, older response evidence and fixed email history are nearby named disclosures. Manual response requires explicit accepted/declined, nonblank source note and timezone-aware event time; server recording time is distinct. Acceptance never advances cooperation automatically. Excluded/canceled historical members remain represented by server rows.

Five APIs: `list({activityId, sending_state?, invitation_state?, follow_up_state?, limit?, offset?})`, `detail({activityId,selectionId})`, `creatorHistory({creatorId,activityId?,limit?,offset?})`, `update({activityId,selectionId,data:{expected_revision,follow_up_state?,cooperation_state?,notes?},idempotencyKey})`, `respond({activityId,selectionId,data:{expected_revision,outcome,source_note,responded_at},idempotencyKey})`. Updates require at least one non-null field; empty notes clear. Both writes have HTTP idempotency but no durable request UUID; frozen old-revision replay/readback must not fabricate a new response event.

Bounded work: adapter worker owns types/client/validation/transport fixtures and tests; UI worker owns controlled relationship editor and tests; root owns frozen operation/session, integration, creator history, relevant tests and fixture verification. Reuse existing B Delivery decoding/preview and guards. One limited independent review; targeted TDD/tests, no repeated broad suite or new visual design round. Verify actual API writes and any actual renderer writes separately; no native/Keychain/release claim. Preserve all failed evidence and fixture controls; no push or deployment.
