# B / P7 — final qualification and immutable sending

Approved continuation after F8 `383bcc3139fb70b4f8cddde57ff987ed399738eb`. Main explicitly permits local synthetic SMTP capture on its exclusive62611 B fixture, not real mail, push, deployment, native/Keychain changes or backend edits. Immutable contract B `ece2e9d9558dfe057dc40ad58bd98a86e3149dd5`, migration0017. Root fully read `docs/backend-v2-activity-sending.md`, schemas/routes/repository `activity_sending.py`, `activity_qualification.py` and `activity_send_tasks.py`. Do not consume later X/Steam/YT/C interfaces on this old fixture.

## Task and information hierarchy

Current draft set → explicitly check every original member → repair the affected draft or exclude with a reason → review actual sender/addresses/content → explicitly Send N emails → inspect frozen deliveries and handle definite failure or unknown outcome. A compact roster and the current email remain the focus. No mandatory per-person open or preview approval, no client-side shrinking of the qualification.

| State | Main focus / operation | Retained context and disclosure |
|---|---|---|
| Checking | Full original N / wait or return | Exact submitted exclusions; never SMTP probe/send |
| Needs repair | Specific blocking people / repair or exclude | Actual sender, addresses and all people; source details nearby |
| Exclusion edit | Reason for each explicitly excluded person / Recheck | Previous qualification stays visible but cannot authorize sending |
| Ready | Actual From/Reply-To, recipient addresses and full selected email / Send N emails | Counts include excluded people; recall limitation visible before click |
| Final submit uncertain | Original frozen request / Retry same request | Same durable UUID, qualification token, exclusions and key; no fresh submission |
| Delivery history | Frozen content and actual states / inspect | Original full qualification/exclusions on demand; sent means SMTP accepted, not inbox delivery |
| Definite failure / queued dispatch | Affected frozen delivery / Retry or Dispatch queued | Same address/content, current attempt, no Library rebasing |
| Unknown SMTP result | Outcome verification / record source note | No Retry; explicit sent/not_sent selection; not_sent only records a result, separate later Retry |
| Source/credential detour | Retained edits / explicit current recheck | Old tokens cannot authorize current sending; never discard text on credential repair |

Default content is the sender identity, compact all-N recipients/statuses, selected preview and one explicit primary action. Exclusion reasons appear at their people. Immutable source/slot/facts snapshots and full qualification history use named disclosures. No status card stacks or repeated instructional paragraphs. Relevant uncertainty, non-recall and verification consequences stay visible.

## Contract and ownership

New `SendingAPI` methods return `Result<T>`:

```
qualify({compositionId,data:{excluded}}):Qualification
send({compositionId,data:{request_id,qualification_token,excluded},idempotencyKey}):SendBatch
batches({activityId,offset?,limit?}):SendBatchPage
batch(id):SendBatch
retry({id,data:{expected_attempt}}):Delivery
resolve({id,data:{expected_attempt,outcome:'sent'|'not_sent',source_note}}):Delivery
```

Only final send has Idempotency-Key and durable request_id. Qualification POST computes a read-only all-N snapshot. Retry/resolve are non-idempotency-header attempt-bound writes. Queue503 may follow a committed send batch or delivery retry: preserve the original intent and read current state; never create a new final UUID as recovery. Credential replacement fences responses/replays. Full send snapshots remain immutable after Library/draft edits.

Task1 worker owns new shared types/client/validation/transport/fixtures/tests; root owns existing bridge/application/gateway/preload integration. Strict exact routes before credential reads, bounded safe DTOs, UUID/token/attempt validation, scoped all-N qualification counts and eligible delivery ordering, sanitized errors, literal transport tests. No HTTP until explicitly leased.

Task2 worker owns frozen final-send/retry/resolve operation and tests. Final retries keep the same body/key/UUID beyond header cache window, never rebase tokens. Revision/attempt operations do not blindly replay. Confirm readback only with exact frozen identity/content/attempt/effect proof; explicit current review is distinct from proving earlier success. No automatic retry of SMTP unknown or sent states.

Root owns the qualified-recipient editor, same-Activity workspace/controller, immutable delivery history/preview, explicit outcome verification and existing navigation/credential guards. Workers may then take independent components with fixed props. Major business phases use a discriminated state rather than independent display toggles. UI must preserve local exclusion/resolution input and successful recipients during polling, partial failures and return paths.

## Verification and limits

Use focused RED→GREEN tests and one bounded independent Medium review. Main now asks necessary targeted verification, not another repeated full suite. Build/typecheck/diff check once integrated, rerun only affected checks for fixes. Use own labeled fixture Activity/composition for synthetic capture; never send/retry main's prior successes, never change baseline SMTP or controls without explicit lease and finally restoration. Actual capture events, MIME content, unknown resolution and no duplicates get a sanitized physical ledger. Final headless production-renderer evidence stays distinct from API writes and native/package/Keychain acceptance. No push or GitHub action; main owns local integration and any later separately authorized release.

## Implementation and source verification

Implemented all six business methods through strict client → gateway → preload, with qualification POST classified as a read before credential fencing. The Activity owns three primary modes: drafts, recipient review, frozen deliveries. Exclusions are composition-bound; verification notes are delivery/attempt-bound. SMTP opens the Email category directly and retains the original Match task while disabling workspace replacement. No navigation/background update generates or sends mail.

One independent Astra/Medium unit review covered operation semantics and integrated controller/UI/wiring; no Important/Critical findings. Root then added a synchronous-event regression: a previously rendered Send callback could dispatch old choices in the same React batch as an exclusion change. The test failed with one actual mock send, then passed after synchronous invalidation and current-ref checks before freezing the request. No backend changes.

Verification is segmented, not a new broad full-suite claim: adapter15, operation22, qualification7, delivery8 focused tests passed; root controller8 passed after the callback fix. The initial integration group had48/49 passes: its sole failure was a pre-existing `/^Send/` action assertion matching the new read-only **Sending history** label. The assertion now matches `Send` as a word (not `Sending`), preserving the no-send-action check. The corrected outreach file plus actual App sending/SMTP detour flow, Settings host and retained drafts passed19/19 across4 files. Typecheck and production build111 modules passed; JS571.96kB size warning remains.

Final new-unit test group: **69/69 across10 files passed**. A bounded follow-up found no issue in the synchronous callback fix. Production source remained frozen after typecheck/build111; final source hash `62b3901d81373f7b16aca6b3c8f9853101a6b0c134433bf657742f6a1f7b5af4`, renderer hash `e379d31ca86bba8d8201f4115f0379383f22a7bf3ab331eb8a4dcdfeacbb1bc7`.

Actual API/worker/capture passed1/1 after a harness-only JSON object-order hashing correction. All6 accepted sending operations were exercised; successful run recorded4 exact MIME captures, including a clearly labeled synthetic not-sent operator override and its deliberate second capture. Read [the API evidence](activity-sending-real-api-verification.md) for original failure, exact side effects and interpretation.

Frozen-source headless App passed1/1 after adding the omitted initial read-only `creators.list` bridge to the harness:36 GET +1 read-only qualification POST, **zero mutations**, no runtime/bridge/network errors. Root inspected both wide and760px/135%-font images; actual identities, exact email preview, all-N/exclusions, SMTP detour, retained local reason and keyboard/reduced-motion geometry passed. Controls, model and SMTP event bytes and durable records remained unchanged. See [renderer evidence](activity-sending-renderer-verification.md). This is not real UI-write or native acceptance; API writes and mocked App write-path tests are separate evidence segments.

Neither native Electron/IPC/preload/Keychain nor a rebuilt installed package has been accepted. The current round has no upload/deploy authority. No backend or API contract files were modified. P7 keeps its62611 pin; subsequent C/Analyze work has a separately authorized64692/0019 fixture and must not silently upgrade the old one.
