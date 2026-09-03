# Find Me Gamer internal release acceptance

Complete this record only during the Task 10 release gate. Do not paste access
keys, provider credentials, SMTP passwords, master keys, response tokens,
message bodies, recipient addresses, environment dumps, or database URLs into
this document or its evidence. Every result starts unchecked.

## Release header

- Release version: ___
- Immutable deployed commit: ___
- Service HTTPS origin: ___
- Release artifact: ___
- Release checksum: ___
- EC2 environment label: ___
- UTC start time: ___
- UTC completion time: ___
- Primary operator: ___
- Independent witness: ___
- Final release decision: ___

## Safe data, evidence, and stop conditions

Use only company-owned games/channels and controlled company/test mailboxes.
Record filenames and sanitized counts/statuses, never message bodies or email
addresses. Stop immediately on an uncertain send result, unexpected external
recipient, numeric rank or numeric score exposure, failed restore isolation,
secret-bearing output, deployed-commit mismatch, or checksum mismatch. Do not
repeat a send after an uncertain result.

The following are forbidden during this internal gate: recipients outside the
controlled mailbox set, automated response-token POST requests, destructive
database operations, production rollback experiments, and retries that might
duplicate a send. The response checks below are manual browser actions using
the exact delivered controlled message once.

For evidence recording, Task 10 supplies only these non-secret routing inputs:
`FMG_EC2_HOST`, `SERVICE_BASE_URL`, and
`FMG_RESTORE_RESULT_FILE=release/restore-result-<version>.txt`. The restore
result is a regular non-symlink file with exactly these allowlisted lines:
`result=PASS`, `alembic_revision=<revision>`, and
`required_table_count=6`. Run `ops/record_release_evidence.sh <x.y.z>` only
after this checklist is fully complete.

## Scenario: workspace-key

- id: workspace-key
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: Fresh app state, one deliberately invalid key, and the valid Workspace Key available without writing it into evidence.
- Steps: On first launch reject the invalid key, accept the valid key, quit, reopen, and confirm device-local Keychain reuse without re-entry.
- Expected outcome: Invalid access is safely rejected; valid access opens the workspace; relaunch restores access without displaying or recording the key.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: steam-analyze

- id: steam-analyze
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: One company-approved public Steam game URL and working configured services.
- Steps: Submit Analyze from the macOS app, observe the cloud Job to completion, open the resulting Game profile, and note only sanitized Job/profile identifiers.
- Expected outcome: Steam Analyze completes through the cloud worker and the shared Library shows the usable English Game profile.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: youtube-analyze

- id: youtube-analyze
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: One company-approved public YouTube channel URL and working configured services.
- Steps: Submit Analyze from the macOS app, observe the cloud Job to completion, open the resulting Creator profile, and note only sanitized Job/profile identifiers.
- Expected outcome: YouTube Analyze completes through the cloud worker and the shared Library shows the usable English Creator profile.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: library

- id: library
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: Completed Game and Creator profiles from the controlled Analyze scenarios.
- Steps: Open the shared Library, switch Game/Creator type and All/Only Collection filters, search, paginate if offered, favorite then unfavorite a profile, open details, and verify affected-profile refresh.
- Expected outcome: Filters, search, paging, favorite rollback/removal rules, detail presentation, and refresh remain consistent across the shared Library.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: reanalyze

- id: reanalyze
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: An existing successful profile and a controlled way to make one re-analysis Job fail without changing production data manually.
- Steps: Start re-analysis, observe the deliberate Job failure, confirm the prior profile remains, restore the normal service condition, and re-analyze successfully.
- Expected outcome: Failed re-analyze preserves the prior Profile; later success atomically refreshes that same profile and the Library detail.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: creator-seed

- id: creator-seed
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: Approved live CSV containing exactly 100 unique Creator URLs and no contact content that may enter evidence.
- Steps: Run the documented resumable seed workflow, retain its sanitized atomic report, resume if required, and inspect only final counts.
- Expected outcome: The report covers exactly 100 rows, is resumable, and finishes with zero unresolved or failed rows.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: three-stage-match

- id: three-stage-match
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: One completed Game profile, the seeded Creator set, and the configured matching model.
- Steps: Start a three-stage Match; confirm coarse screening, deep comparisons, and final ordering complete; inspect recommended/other threshold separation and qualitative reasons.
- Expected outcome: The full workflow publishes once with threshold-consistent groups and evidence; macOS and public API evidence expose no numeric rank, numeric score, or backend ordering.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: outreach

- id: outreach
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: NetEase SMTP configured for the approved sender, a saved template, matched Creators, and only controlled company/test mailboxes as recipients.
- Steps: Save and preview the exact draft, send one individual delivery, then create and send one batch to distinct controlled recipients while observing each delivery status.
- Expected outcome: Preview-before-send is enforced; individual and batch NetEase delivery use the intended template/recipient identity and produce one delivery per intended recipient.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: accepted

- id: accepted
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: One controlled delivered message whose Accepted action has not been used.
- Steps: Open the exact Accepted link manually once, confirm the browser result, and refresh the corresponding campaign metrics without copying the capability URL.
- Expected outcome: A final Accepted confirmation is shown and the campaign Accepted metric increments exactly once without exposing the response token.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: declined

- id: declined
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: One different controlled delivered message whose Declined action has not been used.
- Steps: Open the exact Declined link manually once, confirm the browser result, and refresh the corresponding campaign metrics without copying the capability URL.
- Expected outcome: A final Declined confirmation is shown and the campaign Declined metric increments exactly once without exposing the response token.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: duplicate-send

- id: duplicate-send
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: One controlled recipient/draft already sent successfully and its completed client action state.
- Steps: Attempt the same action again through the ordinary UI path without changing the draft or recipient; do not retry if the original outcome is uncertain.
- Expected outcome: Exact idempotency and successful-action locking prevent duplicate email; the server and UI still show only the original delivery.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: cloud-continuation

- id: cloud-continuation
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: A controlled long-running Analyze or Match Job that has safely reached a durable server stage.
- Steps: Start the Job, close the macOS app, wait for cloud continuation, reopen the app, and refresh the Job/profile or Match workspace.
- Expected outcome: Work continues in the cloud while the app is closed and the completed canonical result is recoverable after relaunch without duplicate execution.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: offline-reconnect

- id: offline-reconnect
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: An authenticated retained workspace and a reversible local network-disconnect procedure.
- Steps: Disconnect networking, confirm the offline banner and read-only retained workspace, verify Analyze/Favorite/Match/Outreach writes are disabled, reconnect, and use Retry once.
- Expected outcome: Offline state preserves local navigation and disables only unavailable writes; reconnect revalidates once and restores normal operation without losing the saved key.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: macos-14

- id: macos-14
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: A supported macOS 14 device and the checksum-verified release artifact.
- Steps: Install and launch through Gatekeeper, authenticate, navigate all four workspaces, open profile/Outreach sheets, and exercise the standard SwiftUI fallback controls.
- Expected outcome: The notarized app launches and normal flows remain usable with native standard SwiftUI materials and no unavailable Liquid Glass API use.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: macos-26

- id: macos-26
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: A macOS 26 device and the same checksum-verified release artifact.
- Steps: Install and launch through Gatekeeper, authenticate, navigate all four workspaces, and inspect the conditional header/actions/sidebar treatment while exercising normal flows.
- Expected outcome: The official Liquid Glass path is active on macOS 26 without changing hierarchy, accessibility, navigation, or write behavior.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: backup-restore

- id: backup-restore
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: A freshly produced encrypted-at-rest backup object and checksum, Instance Role access, and the exact isolated restore rehearsal database name.
- Steps: Run the documented isolated restore rehearsal, verify checksum before database work, confirm current Alembic head and all six required tables, and confirm exact cleanup.
- Expected outcome: Restore succeeds only in the isolated test database, reports the current revision and required tables, and leaves production data and the test database unchanged/clean afterward.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Scenario: master-key-recovery

- id: master-key-recovery
- Responsible operator: ___
- UTC timestamp: ___
- Environment/device/OS: ___
- Prerequisites/test data: Authorized operator and witness with access to the company password manager metadata but not a need to reveal the key.
- Steps: Confirm exactly one current master-key recovery copy exists in the approved company password manager and confirm object-storage inventory does not hold that key; record only boolean confirmation.
- Expected outcome: Both people confirm a recoverable copy in the password manager and explicitly confirm it is not S3, without recording the key or vault secret.
- Actual outcome: ___
- Evidence filenames: ___
- [ ] PASS
- [ ] FAIL

## Final two-person sign-off

Distribution is allowed only when all 17 PASS boxes are checked, every FAIL box
is unchecked, there is no unresolved binding issue, the deployed commit and
release checksum exactly match the header and evidence, and isolated restore
proof is present. A failed or blank scenario means no coworker distribution.

- [ ] Primary operator approval — name / UTC: ___
- [ ] Independent witness approval — name / UTC: ___
