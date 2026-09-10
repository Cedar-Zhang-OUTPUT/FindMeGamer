# Search failed-node recovery — 2026-09-10

Internal Demo bounded follow-up to e924c52 (model aliases) and e43b6ed
(ordinary narrative validation). No deployment or production retry in this unit.

## Behavior

The existing Search retry API and orchestration remain the entry point. For a
failed, owned YouTube analysis, recovery creates a new queued attempt and copies
every validated successful checkpoint in the same transaction as updating the
Search unit's job reference. The original FAILED job, payloads and checkpoint
timestamps are preserved. Normal executor claiming and pipeline publication
remain in use; terminal jobs are not reopened and Profiles are not directly edited
by recovery. Existing maintenance CLI shares the node-schema registry.

- Same Search/job ownership and Creator platform/account/identity revision are
  required. A queued/running job for the target prevents creating another attempt.
- Source, visual and contact checkpoints are mandatory. Source must be within the
  existing 30-day recovery window. Unknown versions, malformed payloads, wrong
  references or inconsistent dependencies are rejected before model calls.
- Missing map/reducer/Brief nodes are executed; successful ones are loaded from
  copied checkpoints. No implicit YouTube/source, thumbnail or contact reacquisition.
- Failed units that never acquired a job also reject implicit new acquisition.
  The previous profile error remains during the retry wave so this decision is
  available, then normal final status writing clears/replaces it.
- Existing successful Profiles are reused without overwrite. Search candidate
  scope remains frozen; email success/missing and successful evaluation steps
  retain their existing skip/reconciliation behavior. No SMTP path is added.
- Recovery model metadata records the source job and reused node keys, and says
  configured model names describe **new calls only**. Original checkpoint model
  versions were not recorded; copied results are not relabeled as newly generated.

## Explicit recovery errors

| Code | Meaning / next action |
| --- | --- |
| `search_resume_checkpoint_missing` | Source/visual/contact or previous job missing; explicit fresh Analyze required. |
| `search_resume_source_expired` | Saved source exceeds 30 days; explicit fresh Analyze required. |
| `search_resume_checkpoint_invalid` | Saved version/schema/evidence/dependencies invalid; inspect or explicitly Analyze anew. |
| `search_resume_unavailable` | Unsupported platform, unowned/nonretryable or mismatched job; do not silently start again. |
| `search_identity_changed` | Current identity/source no longer matches; use explicit current-identity analysis. |
| `search_profile_busy` | Existing work owns execution; wait and reconcile. |

This node recovery currently supports **YouTube only**. X has no equivalent
persisted map/reduce source checkpoints and is explicitly rejected, not refetched.
Initial Analyze functionality is unchanged.

## Verification

- TDD: new planner tests initially failed collection because the new planner did
  not exist. Integration first reproduced four failures with two existing guards
  passing. The no-job fallback regression separately failed before its fix.
- Final combined suite: **632 passed**, no skips; one existing Starlette warning.
  Includes all analysis/matching unit tests, DeepSeek integration unit tests,
  Creator publication/checkpoint/CLI-resume tests, Search API/worker/enrichment,
  new recovery tests, and three real Redis/Celery delivery tests enabled via
  `FMG_RUN_BROKER_TEST=1` in the owned isolated test stack.
- Synthetic real pipeline tests forbid acquisition entirely: missing reducers
  call four reducers + Brief only; missing batch adds only that batch; a Brief
  failure followed by explicit retry reuses all successful reducers. Repeated
  calls after success perform no new model work. Original payloads remain equal.
- Guard tests cover missing/expired source, missing visual/contact, malformed
  checkpoint, identity change, foreign ownership, running/other active job,
  no-job failure, and successful Profile preservation.
- Saved real failed jobs `92192013-82fb-4275-a3b2-ffeeb86a04f2` and
  `af98a11d-a069-4551-a0c0-e700e8a0be58` pass the new planner with all 11/12 saved
  successful nodes reusable under current schemas/new model configuration.
  This is offline validation, not paid execution. The export contains job times
  but not node times, so its age test conservatively substitutes job start time;
  production uses actual source-node creation time. Raw samples are not committed.
- Independent bounded review and final no-job-path follow-up found no blockers.
  `git diff --check` passed. No new provider HTTP, production writes, deployment,
  retries, emails, concurrency tuning or Service Health work.

## Release boundary

At 17:02:42 Shanghai the original 50-person Search was still running in emails:
30 usable Profiles (15 newly ready, 15 reused), 20 failed (18 output validation,
2 contact validation), 9 emails available, 6 missing, one email running. Not a
terminal snapshot and not permission for maintenance. Deployment must include
this recovery change as well as e924c52/e43b6ed, wait for all active work to stop
naturally, take the normal backup, and obtain coordinator release. Only one
explicit retry of this Search is authorized after release; no full rediscovery,
old 68-person activity, automatic sending, or unbounded retry loop.
