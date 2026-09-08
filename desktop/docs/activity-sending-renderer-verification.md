# P7 headless renderer verification

Status: root executed and visually reviewed; **HEADLESS passed**. This is separate from API verification and does not establish native Electron, Keychain, inbox delivery, production SMTP permissions, or real UI writes.

`e2e/sending-renderer.spec.ts` serves the frozen built production App and exposes a narrow bridge backed by production clients, including SendingClient. Credentials remain in Node; raw responses, addresses, console details and traces are not persisted. Only GET and the exact fixture composition’s read-only qualification POST can reach fixture62611. All other bridge methods and HTTP mutations are rejected.

Root execution prerequisites:

- Completed P7 API fixture ledger (0600) under the existing private fixture directory, with `status: "passed"` and `renderer_fixture: {activity_id, composition_id, recipient_batch_id, send_batch_id}`. Its Activity name must start with `P7 `, full-N membership must agree, and all selected batch deliveries must be terminal rather than queued/submitting.
- Set `FMG_P7_API_LEDGER` to that exact ledger and `FMG_P7_RENDERER_FROZEN=62611` only after an explicit source/build freeze and exclusive fixture lease.
- Run only this specification with a fresh unique `--output` directory. Keep prior failure ledgers/screenshots. No automatic rerun or production fixes are authorized by the harness.

Planned checks: open the labeled Activity; sending history and each frozen email’s exact server HTML, status and full original qualification; draft history and explicit Review sending; all-N roster; local exclusion reason; SMTP settings detour and retained reason with mandatory recheck; wide and 760px/135% font, reduced motion and keyboard focus. No Send, dispatch, retry, resolve, SMTP test or settings save is invoked.

The API harness owner confirmed the planned input is `p7-sending-<run UUID>.json`, pointing to the first `P7 desktop verified_sent …` Activity: three original members, one excluded repair member and two terminal sent deliveries (SMTP capture and explicitly verified sent). The renderer harness derives labels from each immutable delivery record instead of treating both outcomes as inbox delivery.

One unique sanitized physical ledger is written in `finally`, including stage/pass/fail, fixture IDs, per-route HTTP and bridge counts, mutation count, runtime/blocked-request counts, screenshots and source/build hashes. Control/model/SMTP file hashes are compared before/after, including on failures. Composition, frozen send batch and saved Activity source are reread and compared. Screenshots are synthetic-fixture evidence and require root visual review before acceptance.

Authoring check: TypeScript `tsc --noEmit --pretty false` passed. No browser or HTTP execution was performed during harness authoring.

## Actual frozen-source run, 2026-09-09

Root fully read the harness and successful API ledger before running it. The first headless run completed its UI, layout and durable-unchanged checks but failed the strict runtime ledger: the harness omitted the production App’s initial read-only `creators.list` method. Page errors, console problems, forbidden HTTP and blocked browser requests were zero; unexpected bridge count was1. Original physical ledger `private/p7-renderer-5d3f8354-3ec1-4691-9443-99cf612caa77.json` and screenshots under `desktop/output/playwright-p7-20260909/` are preserved. Root added only that production CreatorClient read to the harness, without changing app source or build.

Corrected headless result: **1/1 passed,3.9s** (4.6s runner), physical ledger `private/p7-renderer-7b9ed0b5-996f-41c8-be11-4f61b2aaf3fa.json`. Root read the physical ledger and both images. It made36 GET and1 read-only qualification POST, zero mutation requests. All runtime/bridge/network error counts were zero. All3 original members and2 frozen deliveries remained visible; labels correctly distinguished **Accepted by SMTP** from **Recorded as sent**. SMTP detour opened Email directly and returned with the local exclusion reason intact and recheck required. Keyboard access, reduced-motion preference,760px window and135% font fit passed. No backend writing, SMTP testing or real mail occurred in the renderer run.

Root-reviewed screenshots:

- `desktop/output/playwright-p7-final-20260909/sending-renderer-P7-built--619c9-SMTP-detour-without-sending/sending-wide.png`
- `desktop/output/playwright-p7-final-20260909/sending-renderer-P7-built--619c9-SMTP-detour-without-sending/sending-narrow-135.png`

Source SHA256 before/after: `62b3901d81373f7b16aca6b3c8f9853101a6b0c134433bf657742f6a1f7b5af4`; renderer bundle SHA256 before/after: `e379d31ca86bba8d8201f4115f0379383f22a7bf3ab331eb8a4dcdfeacbb1bc7`. Source-control, model-event and SMTP-event bytes were unchanged, as were composition, frozen batch and Activity source snapshots. The installed native package was not launched, replaced or accepted. UI write paths were covered with mocks and API writes separately, not through this read-only headless bridge.
