# Match capacity and Creator content evidence repair

Scope: a stable internal company Demo, preserving the existing Library, credentials, favorites, and task history. No Twitch support, bulk reanalysis, email sending, or unrelated migration hardening was added.

## Changes

Match screening and final ranking preserve the complete global candidate set while grouping complete JSON items into messages of at most 120,000 UTF-8 bytes. The complete message budget is 512,000 bytes. There is no per-chunk ranking or discarded candidate data. Screening still selects at most 30 candidates. Output budgets are explicitly 16,384 / 16,384 / 65,536 tokens for screening, pairwise analysis, and ranking.

Creator content-format reduction now provides exact current-stage citation targets alongside the existing validated batch values and their original evidence. A failed evidence-binding check can use one bounded correction request, changing only citation reference/source type/kind; claim values, observations, evidence count/order, statuses, and confidence must remain identical. Existing evidence validation is not relaxed. Logs contain only code-owned failure reasons, not model/source payloads.

The maintenance recovery command supports `--mode content-format`. For the three diagnosed failures it creates a new job, copies 11 validated checkpoints, and recomputes only content-format and the dependent Brief. It never reopens terminal jobs or directly writes a Profile.

## Verification and deployment

- Match-specific isolated tests: 286 passed; independent review: 28 passed, GO.
- Content evidence/recovery independent review: 21 passed, GO.
- Combined full backend suite: 1,809 passed, 3 skipped, 1 warning. Three initial log-capture test failures were resolved using the existing logger-restoration fixture pattern; no business code was changed for that test issue.
- Complete isolated end-to-end runner: passed in 91 seconds, including Analyze, Library, Match, capture-only Outreach, Yes/No, duplicate protection, and task recovery. No real emails were sent.
- Source commits: Match `66254623c50dd093d75ebda33858f610bfd00661`; content repair `a0fc644`.
- Backend-only deployed commit: `1e84f9f2d17e875fc76a88f6f3c7ca528f55ade8`.
- Database remains at `20260904_0007`; the migration command completed successfully.
- Pre-migration backup: `s3://zhangyue-data-493392056671-us-west-2/backups/20260907T051725Z-1e84f9f2d17e-pre-migration.dump`.
- Deployment began only after DB and worker/broker checks reported no active, reserved, scheduled, or queued work.
- All 17 business-table fingerprints were identical before/after deployment: 19 Creators, 1 Game, 29 analysis jobs, 1 Match, and 0 deliveries were preserved. All three recovery sources passed schema and evidence validation for their 11 checkpoints.
- HTTPS readiness and the anonymous 0.1.3 update manifest passed after deployment.

## Live recovery acceptance

All three targeted recoveries succeeded and published readable Profiles and Briefs:

| Creator | New recovery job | Published Profile |
| --- | --- | --- |
| LaurenZside | `d2f0b7e3-0347-44c2-a507-ec36f011a638` | `f71871a5-390f-4ac7-b7bc-e0e20acaed41` |
| jun channel | `ff6ed111-5f18-4cf1-9d0e-41ba67930fa7` | `0522cd35-ef26-48ad-8cb3-727d4ac03d6d` |
| 大蒙 | `067e229d-0b11-4026-a97d-6be853caf641` | `b23406d8-a6cf-4583-b843-f94bbfc7cffc` |

The Library now contains 22 Creators and 1 Game. All baseline rows across 17 tables remain byte-for-byte equivalent under PostgreSQL row-JSON SHA-256, with no missing or changed rows. Recovery added exactly 3 jobs, 3 Profiles, 39 checkpoint rows, and 7 contacts. Credentials, favorites, prior Profiles, and original failed-job history remain unchanged. Deliveries remain zero.

LaurenZside's reused visual analysis is available. jun channel and 大蒙 retain their earlier unavailable visual checkpoints; this content-format recovery deliberately did not recompute them or claim a successful visual recovery.

A real Match for LIMINAL: Within was submitted against the 22-Creator Library as `7e7f6a83-2071-4864-a9ed-6e65db630400`. It completed the valid zero-selection path in 1.13 seconds, without exercising pairwise/ranking; this is not recorded as positive full-path acceptance.

Independent read-only reconstruction proved that all 22 IDs and Briefs were preserved exactly once and the Game appeared once. The user message was byte-identical to the previous prompt implementation (67,548 bytes); this request did not use multiple user messages. The provider returned HTTP 200 once, with no schema repair or truncation. A bounded diagnostic replay of the identical current prompt selected 19 candidates, while the previous system wording with the same inputs/budget selected 9 (after one schema repair). Neither replay wrote business data. These observations show that the initial empty result is not evidence of genuinely unsuitable Library contents; they do not establish an error frequency or a deterministic wording regression.

A minimal, separately verified non-empty-pool/empty-selection confirmation is in progress. It will not force candidates or alter ranking thresholds. The 50/100-Creator capacity cases are isolated fixtures, not claims of 50/100 production Creators.

The four identity-correction candidates (Shenpai, Rose Matter, Gigi Murin, NicoB) remain paused by user instruction. No substitute channel was submitted.
