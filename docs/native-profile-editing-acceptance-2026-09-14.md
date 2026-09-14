# Native restoration and Profile editing acceptance

Status: local backend/native implementation verified; release acceptance incomplete. No production deployment/migration, data reset, live-provider validation, email delivery or package publication occurred.

Final independent code acceptance: **approved at `de7e962`**. The whole-branch review found one outreach propagation issue; the single scoped fix wave corrected names and frozen manual Brief precedence, and its scoped re-review marked the issue addressed with no new blocking breakage. This approval does not replace the outstanding actual editor-window and release checks below.

## Baseline evidence

- Worktree: `.worktrees/native-profile-editing`, native base `97bcd95`, design/plan commits `73ed748` and `5ff9190`.
- Native baseline: `swift test --parallel` built successfully; 329 tests in 44 suites passed.
- Backend baseline in isolated Compose project `fmg-native-edit`: 1,818 passed, 3 skipped, 4 failures in maintenance recovery tests. Task 3 corrected the fixed-date fixtures; its full run passed 1,851 tests with 3 skipped. The subsequent capacity correction passed 134 focused tests.
- `bash script/build_and_run.sh --demo` built and launched the bundled native app. Existing OpenAPI nullable/schema generator warnings remain visible; this is not warning-free output.
- Native accessibility walkthrough verified Library's Game/Creator switcher, Game detail for Neon Harbor and Creator detail for Tactical Cedar. Both use the shared Profile sheet with Overview and Sources & Analysis; Creator additionally has Contacts & Notes. The visible Demo banner confirms this walkthrough used sample data, not production.

## Implementation and local acceptance

Backend overrides/Match snapshots: `cef6ceb`; native editor: `4d8a3c7`; contact draft preservation: `1343b2f`; provider/visibility compatibility: `95aaac8`; hundred-Creator prompt budget correction: `9faf788`. Task 4 acceptance tests: `cfff1cd`. Native migration head is `20260914_native_0008`, parent `20260904_0007`, separate from production v2 `0023`.

Final Task 4 backend run: **1,858 passed, 3 skipped, 1 warning**, 107.48 s, exit 0. Final native `FMG_NATIVE_HTTP_ACCEPTANCE=1 swift test --parallel`: **344 tests in 49 suites passed**, including actual HTTP smoke, 1.95 s test time, exit 0. Both ran once on the final Task 4 test implementation (parent `9faf788`, committed unchanged as `cfff1cd`); later changes are documentation only. These results precede the controller-owned outreach fix and whole-branch review described below.

`backend/tests/integration/test_native_profile_editing_vertical_slice.py` exercises real authenticated routes, PostgreSQL and Game/Creator analysis pipeline finalization. It covers editor GET/PATCH, independent reopened GET/detail, stale revision conflict, separate contact/notes Save, source reanalysis, reset to refreshed source, new Match manual context, and unchanged old/already-created Match snapshots. Match detail reports both profiles' snapshot/current revisions 2/4. Steam/YouTube, public pages, model responses and artifact storage are deterministic in-memory fixtures; publication/DB transactions are real. This does not establish live model quality or provider availability.

`NativeProfileHTTPAcceptanceTests` runs the shipping Swift `OpenAPIService`, generated client, auth middleware, URLSession transport and `ProfileEditorState` against real loopback FastAPI/PostgreSQL. It verifies draft/Cancel leave server state unchanged, Save/reopen, stale revision rejection, reset, separate contact Save and old/new Match revision metadata. Only an inert in-memory key is supplied; no Keychain access occurs. This is native HTTP integration, not an app-window walkthrough.

After the final outreach correction, the controller independently restarted only the dedicated HTTP fixture server to load the final code, retaining its DB, and ran `FMG_NATIVE_HTTP_ACCEPTANCE=1 swift test --package-path macos --filter NativeProfileHTTPAcceptanceTests`: **1 test in 1 suite passed**, 1.482 s, exit 0 (`root-final-native-http.log`). The native source/test tree is unchanged from the earlier 344-test run.

Focused evidence: backend vertical slice 1 passed; fixture database guard RED 3 missing-helper failures then GREEN 3 passed; Swift HTTP RED connection refused without server, then GREEN 1 passed in 1.60 s. Logs are under ignored `.superpowers/sdd/2026-09-14-native-profile-editing/`: `task-4-http-red.log`, `task-4-http-green.log`, `task-4-backend-full.log`, `task-4-native-full.log`, `task-4-outreach-probe.log`. Existing Starlette/AnyIO deprecation and OpenAPI nullable/PublicJSON schema warnings remain; successful runs are not warning-free.

## Outreach correction and release gates

The final review's outreach composition issue is corrected at the new-composition boundary. Authenticated PATCH/preview regressions reproduced two name failures (`Source Creator × Tactics Together` instead of `Human Creator × Human Game`) before the fix. New preview display names, channel names, subjects and new-batch rendered content now use effective names; reset restores source names. Existing recipient addresses and rendered subject/Markdown/HTML remain unchanged after later name edits and resets. The original RED diagnostic remains preserved as `task-4-outreach-probe.py` under SDD.

Summary regressions also reproduced two failures before correction: new outreach ignored manual Brief values frozen at Match creation. Composition now checks frozen manual positioning premise, then frozen manual gameplay loop, using the locked source claim only when that field has no override. An explicit empty override suppresses its old source claim. Later current-profile Brief edits do not change the locked summary; only the no-summary name fallback uses the current effective game name. Tests exercise real PATCH and Match creation to capture inputs, then use the existing deterministic published-result fixture for preview/batch composition; they do not claim a live model run. Covering outreach verification: **197 passed, 1 skipped, 1 existing warning**, 22.72 s, exit 0. Final once-only full backend on the finished correction: **1,862 passed, 3 skipped, 1 existing warning**, 94.47 s, exit 0 (`docker compose -p fmg-native-edit -f compose.test.yaml run --rm test pytest -q`).

GUI release acceptance remains outstanding. Earlier Demo accessibility checks reached Library, details and Edit profile. Opening/reading the editor repeatedly crashed `SkyComputerUseService` (`EXC_BREAKPOINT/SIGTRAP`, Swift `Array.remove(at:)`) while FindMeGamer remained running. Screenshot/reconnect attempts also failed through the native pipe. No further CUA retries or GUI harness were added; no successful editor-save screenshot is claimed.

Before release, manually walk both real API profiles through edit, Cancel, Save, reopen, reset, conflict/reload and separate contacts/notes Save; inspect keyboard/focus/layout/error feedback and Match revision notices. Use in-memory fixture credentials for local acceptance, never overwrite the fixed Keychain entry. The scoped correction is independently approved; live-provider checks, maintenance cutover and packaging/publication still require their separate release checkpoint. Tests do not establish those gates.

## Approved tradeoffs

| Decision | Cost |
| --- | --- |
| Contacts/notes retain a separate explicit Save. | One additional Save; no cross-endpoint atomicity promise. |
| Dedicated typed editor GET/PATCH preserve existing detail routes. | One additional endpoint pair/contract to maintain. |
| Manual matching context is frozen separately from source claims. | Maintain prompt precedence and snapshot tests; no fabricated source evidence. |
| New outreach names follow current effective edits; locked Match summaries/reasons and existing delivery snapshots stay frozen. | A new email name can differ from its historical Match label; the existing revision notice explains the distinction. |

## Reproduce real HTTP acceptance

From the worktree's `backend` directory, use only project `fmg-native-edit`. Check port 18764 is free. Create the distinctly named DB only once; if it exists, retain it and omit `createdb` rather than resetting it:

```sh
docker compose -p fmg-native-edit -f compose.test.yaml up -d postgres-test redis-test
docker compose -p fmg-native-edit -f compose.test.yaml exec -T postgres-test createdb -U postgres find_me_gamer_native_http_acceptance
docker compose -p fmg-native-edit -f compose.test.yaml run -d --name fmg-native-edit-http-acceptance -p 127.0.0.1:18764:8000 -e DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres-test:5432/find_me_gamer_native_http_acceptance test python -m tests.native_profile_http_fixture
```

The host address is `http://127.0.0.1:18764`; only profile reads/edits/manual contact changes, Match create/read and session GET are enabled. `/health` returns 403 intentionally. Dispatchers are inert; no worker starts. Fixture Game ID is `a4000000-0000-4000-8000-000000000001`; Creator ID is `a4000000-0000-4000-8000-000000000002`. The key `test-workspace-access-key` is an inert fixture literal, not an existing credential. Source names are Locked Game / Creator 400040004. Repeated smoke runs reset name overrides and append synthetic Match records; contact data remain local.

From `macos`, run:

```sh
FMG_NATIVE_HTTP_ACCEPTANCE=1 swift test --filter NativeProfileHTTPAcceptanceTests
```

The test skips unless enabled. To stop/remove only the fixture server while retaining its DB:

```sh
docker rm -f fmg-native-edit-http-acceptance
```

Backend full reproduction from `backend` uses the separate ordinary test database:

```sh
docker compose -p fmg-native-edit -f compose.test.yaml run --rm test pytest -q
```
