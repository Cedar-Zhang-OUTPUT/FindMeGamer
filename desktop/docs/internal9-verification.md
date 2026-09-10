# internal.9 verification — 2026-09-10

## Final artifact

- Runtime source: `313d3ce`, including `204ff96`, `40937d6`, `f58f085` and the independent review corrections in `313d3ce`.
- Version: `0.2.0-internal.9`; macOS bundle build: `20009`.
- Artifact root: `/Users/cedar/.codex/worktrees/c3a0/FindMeGamer/desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.9-arm64-jh9CLT`.
- DMG: `FindMeGamer-Electron-0.2.0-internal.9-arm64.dmg`.
- DMG SHA-256: `68b6d7660a78b53d56b0e202ea3c17c7661b0d663dbd6d7cb204d975c06a522d`.
- ASAR SHA-256: `768822684c480c9748d6bd843240e21e0fec9e04bcbabb6ecff6f20e75858b93`.
- Icon SHA-256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`.

The earlier `nLfZxQ` candidate is obsolete and must not be released. It remains preserved; internal.8 is unchanged.

## Verification

- Full unit suite: 128 files, 1308 passed, 5 gated skips. Local selection targeted tests: 26 passed. Typecheck and build passed.
- Final packaged application: **5 passed (36.2s)**. Tests assert packaged status and internal.9 version, not just a development Electron process.
  - First launch: default origin `https://44.233.174.193`, empty key, disabled Connect, no credential file, zero HTTP requests.
  - Rapid selection: immediate local checkbox changes, no per-click HTTP writes or selection GET; journal survives reload. Synthetic preparation exercises unknown-result retry with identical frozen key/body.
  - Normal full-process quit/relaunch: different process IDs, four choices restored, including a final toggle immediately followed by normal quit. Actual main-process journal; no mocked preparation IPC.
  - Partial results and 50-person source-incomplete mail: retained available results, correct template/person preview, highlighted unconfirmed slots, no permanent gray preview skeleton; narrow layout checked.
  - P4, P9, Creator Library and Game Library tables: comparison columns, disclosure and direct actions checked at wide/narrow sizes.
- DMG verified with `hdiutil verify`, mounted read-only, strict/deep signature verified, mounted ASAR hash matches above.
- **Mounted DMG application full-process restart: 1 passed (9.3s)** using its exact executable and a fresh isolated profile.
- All 10 packaged runtime files matched the build byte-for-byte. The actual ICNS resource matches the source icon. Package archive contains runtime assets, not test profiles or credentials.
- Packaged narrow template and wide Invitations screenshots personally inspected: preview text readable, invitation rows aligned, navigation preserved.

Evidence: `desktop/output/playwright/internal9-packaged-acceptance-20260910/` and `desktop/output/playwright/internal9-mounted-restart-20260910/`, with per-test JSON and screenshots. Development restart evidence is separately under `internal9-process-restart-20260910`.

## Boundaries and limitations

Real Electron IPC and isolated HTTP GET fixtures were used; all HTTP business writes were blocked. Preparation mutations and the 50-draft/template response were synthetic IPC fixtures, not live backend creation/send proof. No real email/provider calls, online business mutations, or cleanup were performed.

The two independent review issues are fixed: existing account aliases reconcile by strict creator/platform/account/revision identity, and confirmed removal of an identity-changed selection uses the explicitly acknowledged selection ID/revision. Additions remain strictly validated.

No backend behavior, API contracts, default origin, credential policy or global credential cache changed. Normal process restart is covered; OS restart, power loss, real concurrent writers and live provider/send behavior are not established by these tests. The application is ad-hoc signed, not Developer ID signed or notarized; unrestricted Gatekeeper acceptance is not claimed.

Upload, tagging and release remain the integration task's responsibility. This worktree has not published the artifact.
