# Local selection / Prepare — 2026-09-10

## Task and scope

Selection is now local in the native desktop app: compare → toggle immediately →
review the desired people → Prepare once → continue to the existing draft flow.
No backend endpoint, HTTP DTO, default origin, credential policy, saved collection
or shared setting changed. Two narrowly scoped local IPC methods persist selection
journals; they do not provide arbitrary filesystem or network access.

The backend contract used is
`/Users/cedar/Documents/ChatGPT/FindMeGamer/docs/local-selection-prepare-contract-2026-09-10.md`.
Prepare uses the existing bulk-selection and recipient-batch APIs. The native local
path does not make the old per-click add/cancel calls or evidence-filter writes.
  It freezes an explicit set rather than relying on stopping discovery to define
  membership. It does not auto-confirm names, contacts, works or viewing evidence.

## Information / state model

| State | Main action | Preserved context / recovery |
| --- | --- | --- |
| Local choices | Toggle in results, Review selected | Local journal, creator identity and query context |
| Review | Prepare N | Compact people list; View creator / Remove; “On this Mac · not sent” |
| Bulk pending | Wait or retry original preparation | Complete desired set plus exact bulk body/key, saved before dispatch |
| Readback | Read current selections | Bulk already acknowledged; do not blindly repeat it |
| Freeze pending | Wait, retry original, or check saved preparation | Exact recipients, revisions, context tokens, request ID and key |
| Known conflict | Review changed selections | Desired set stays; removed/account-changed members need explicit correction |
| Done | Existing composition flow | Returned immutable recipient batch; no automatic send |

Ordinary background reads cannot reselect a manually removed member: removals are
explicit tombstones. They remain after a successful cancellation; its old active
revision is cleared so an intentional later re-selection can work. Newly saved
selections acquire their acknowledged baseline revisions after readback.

### Scope and concurrency

- A file is scoped by opaque service-origin/credential fingerprint, activity ID
  and query ID. Different pending query drafts are never merged. Switching away
  and back loads that query's journal. A different credential or origin cannot
  read/write the earlier scope through this API.
- Each query's initial desired set includes the activity's already-active shared
  selections, including hidden pages. Local changes only apply to explicitly
  toggled candidate IDs. This retains shared existing members rather than treating
  filtered-out rows as cancellations.
- If Prepare sees a new active server selection that was not represented in the
  draft, it reports a conflict, not a cancellation. Explicit review can adopt the
  freshly read activity context; unsubmitted drafts from other queries are still
  separate files.
- Cancellation uses the observed selection revision. A concurrently deleted,
  revised or identity-changed chosen member blocks preparation and names the
  affected creator. Missing outreach evidence alone does not block freezing.
- Local changes and context-changing navigation are locked during submission.
  Generation checks fence old continuations. Pending replay first validates the
  original local workspace scope again; it cannot replay into new credentials.

### Persistence and unknown outcomes

The journal lives under Electron userData `selection-drafts/<opaque-scope>/`.
Directories use mode 0700 and files mode 0600. Writes use same-directory temporary
files and atomic rename, serialized in the main process. There is no generic path
input. The journal contains local choices and recovery payloads, not credentials.
It is **not an encrypted data vault**; userData and machine-account access remain
the protection boundary. No automatic deletion or history cleanup was added.

Every local edit sends its IPC immediately, so later edits do not remain trapped
in a renderer-only promise queue during reload. Prepare waits for durable writes;
a failed checkpoint prevents the next outbound request. Normal app quit drains
the main-process journal queue. A forced process kill/power loss is not claimed
to preserve an edit that had not yet reached durable storage.

Bulk and freeze have separate keys. An uncertain response preserves the exact
stage/body/key; replay does not recalculate a new delta. Bulk replay is limited to
the existing 24-hour window; after expiry the check-saved path requires proof.
Freeze recovery can page recipient-batch history by persistent request ID and
verify snapshots. A definite rejection requires explicit review/new intent.
If bulk succeeds but freeze fails, no compensating cancellations occur.

Corrupt local journals are not silently overwritten. Disk/scope errors are shown;
the saved local choices remain visible where available. Existing remote save,
draft creation and send behavior is unchanged. The optional local bridge permits
older test/preview adapters to retain their prior behavior; the shipped native
preload always exposes the new local journal methods.

## Verification

TDD began with the new core module absent. Core, real-filesystem store and React
integration tests now cover synchronous toggles, no per-click requests, tombstones,
query isolation, hidden shared members, exact bulk delta/order, no-op bulk skip,
missing evidence, deletion/identity/revision conflicts, unknown-stage replay,
readback, failed persistence, expired bulk, credential fencing, remount recovery,
cross-scope writes and path validation. Final suite: **128 files passed, 1,302
tests passed, 5 gated skips**, 51.27 seconds. This includes 20 tests added for this
unit. TypeScript and the production build pass; the existing large-chunk warning
remains. Final native acceptance: **3 passed**, 23.4 seconds.

Native acceptance runs the built Electron application against the isolated
read-only fixture at loopback port 18093. All real HTTP business writes and
non-fixture origins are blocked. Preparation IPC is replaced with synthetic
records and 500ms read/bulk delays; this is **not a live backend write test**.

The native path performs 31 actual checkbox clicks. Each changed its checked
state and stayed enabled; no selection re-read or HTTP write occurred per click.
The journal was then read through the local bridge, the page reloaded, and five
desired people were recovered. Prepare emitted exactly one synthetic bulk call.
A lost freeze acknowledgement required a retry with the identical freeze payload
and key, without repeating bulk. No page errors were observed.

Final click-plus-assertion timings were 17–25ms (median 21ms); these are fixture
automation measurements, not a guaranteed real-world latency. The final report
retains the complete timing sample rather than extrapolating a performance claim.

Evidence root: `desktop/output/playwright/local-selection-acceptance-20260910/`.
The `local-selection-native-nat-827e2-ays-only-the-unknown-freeze` folder contains
`local-toggles.png`, `unknown-freeze-preserved.png`, and `verification.json`.
The same acceptance run also executes the four-page table and extended UI audit,
covering narrow/dark/reduced-motion states and navigation/editing recovery.
The main agent inspected the native screenshots, not only test exit codes.

## Limits / packaging handoff

- Built-development Electron, not DMG acceptance; no new version/tag/release here.
- Native persistence proof is a page reload; filesystem and hook tests independently
  recreate the store and hook. An actual OS reboot/full-process restart was not
  exercised in this unit.
- Real online bulk/freeze and multiple real colleagues were not exercised. The
  existing backend contract tests and synthetic conflict cases cover those rules.
- The corrupted-journal case retains the file and reports the problem; there is
  no destructive reset button. Recovery may need a deliberate user/support action.
- The 24-hour expiry check is automated unit coverage, not a day-long wall-clock run.
- No global credential caching or unrelated request-chain optimization was added.
- No screenshots or local synthetic workspace credential file are staged in Git.

## Independent-review corrections before packaging

The bounded review identified two real blockers in f58f085 despite the original
tests passing. Both were reproduced with failing tests before fixing them:

1. A creator account rediscovered in another query has a new candidate ID, while
   the backend may reuse the activity's old selection and retain its old candidate
   ID. Local selection and readback now reconcile by creator plus account identity
   (platform, account ID and revision), not candidate ID alone. They deduplicate
   aliases without combining different query draft files. Source candidate IDs
   remain unchanged in frozen bulk requests; a lost bulk acknowledgement can also
   be checked against the retained server selection by identity.
2. An identity-changed old selection could not be removed because validation of
   the cancellation path applied the same identity gate as additions. An explicit
   Remove now records the currently observed selection ID and revision. Only that
   acknowledged cancellation can pass the identity-changed gate. Additions and
   chosen recipients retain strict identity/creator checks; there is no automatic
   selection of the new identity.

Three core regressions initially failed, then passed. Two additional hook tests
exercise alias checkbox state/query isolation and review → explicit removal →
preparing the remaining person. No backend behavior or contract was changed.
Post-review verification: **128 files / 1,308 passed / 5 gated skips** (53.76s),
**26 local-selection tests passed**, typecheck and build passed. A deleted-activity
404 test additionally verifies that stale journals cannot recreate cleared server
records. Full-process/package acceptance is recorded separately for internal.9.
