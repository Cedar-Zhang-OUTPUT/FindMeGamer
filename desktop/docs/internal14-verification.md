# internal.14 — Work metadata compatibility hotfix

Release gate cleared for root publication. Source chain: `b517e48` (internal.13) → `8603867` (hotfix and unit regressions) → subsequent package/evidence commit.

## Scope

Only runtime change: accept the backend's existing `source_fields.outreach_observation` object in the Work response decoder. Its exact keys are text, evidence_kind, source_url, excerpt, source_field. It remains read-only metadata, separate from editable fields and sender-watched confirmation. Historical absence remains accepted; malformed values and attempts to write this metadata remain rejected. No backend, API contract, production data, or other UI changes.

The producer `backend/app/outreach/prefill.py` was inspected for the precise shape and bounds. TDD reproduced the unsupported-response failure before the fix (2 failing tests). Afterward the new focused tests passed 16/16, including actual client decoding into CreatorWorks and InlineEvidenceEditor. One bounded independent read-only review reported no findings.

## Verification

- Typecheck, production build, and diff whitespace checks passed.
- Full unit suite: 1,385 passed, 6 skipped; 135 files passed, one skipped; 60.40 seconds.
- Root independently reported a read-only production sample of five real WorkDetail objects: internal.13 rejected 5/5, removing observation accepted 5/5, this decoder accepted 5/5. This is a sample, not a full production scan; the first full-transfer attempt timed out.
- Isolated real API at 127.0.0.1:18745 used three synthetic works containing metadata created by the actual backend helper (description/title/description), retaining existing source URLs and manual overrides. No provider, worker dispatch, SMTP, or production writes.
- Packaged app test passed in 12.9 seconds (13.4 total), PID 30462. Mounted DMG test passed in 14.5 seconds (14.8 total), separate PID 31024. Both decode all three metadata objects via real IPC/API and open Library → Creator → Known works, then exercise Edit personalization → shared Work evidence for all three drafts.
- Both runs retain four-field wording, save/read back source evidence, leave sibling drafts unchanged, preserve data after reload, recover from a controlled PATCH rejection without losing input, and retain empty/invalid sender facts with send_ready false. Each audited 80 HTTP requests, none outside the allowlist. dispatch_attempts, send_attempts, real_provider_calls, and blocked_writes all zero; controlled failures advanced from 2 to 4 across the two runs.
- These are the existing internal.13 fixtures with now-saved overrides and selected works. Case names describing initial no-overrides/no-selected-work do not imply those initial states were reseeded for internal.14. Those initial conditions were established in internal.13 acceptance.
- Initial internal14-app-verified run stopped on a test selector expecting `Creator 1` instead of the actual accessible button name `Open Creator 1`, after metadata reads and before mutation. Fixed only the test selector; runtime bytes unchanged. Failure output retained.

Evidence beneath `output/playwright/`, each in `inline-evidence-native-pac-7c3d9-with-zero-dispatch-and-send/`:

- `internal14-app-accepted/evidence.json`
- `internal14-mounted-verified/evidence.json`

Screenshots of the Works panel and inline evidence were visually inspected. The native tests use the Playwright workflow with explicit packaged executable and isolated credentials; manifests containing credentials are not published.

## Accepted artifact

Root directory: `artifacts/FindMeGamer-Electron-0.2.0-internal.14-arm64-ykGng2/`.

App: `FindMeGamer-darwin-arm64/FindMeGamer.app`. Version 0.2.0-internal.14, build 20014. All 10 archived runtime files byte-match local out/. Deep strict ad-hoc signature verification passed, including mounted app.

ASAR SHA-256: `ce3183217e9a604f3df1fa6f04b5962b1513f097e42e630e91af57ff845ecc18`.

Custom icon `electron.icns` byte-matches build/AppIcon.icns (unchanged). Packager's optional .icon-format warning does not indicate missing .icns.

DMG: `FindMeGamer-Electron-0.2.0-internal.14-arm64.dmg`; 151,389,524 bytes; SHA-256 `d75eda14bd508f7c90bfc83914474c43da3ef76353600bc719d017f8b2a48bd8`. hdiutil verify passed. Read-only mount `/tmp/fmg-internal14-mount-TAatGI` matched ASAR and was detached after testing.

## Limits

Ad-hoc signed, not Developer ID notarized. Native acceptance uses synthetic data, 1440×1000 and reduced motion; no new narrow-window/accessibility matrix, production editing, actual generation, or sending was attempted. No installed user app was replaced. GitHub publication belongs to the designated root task.
