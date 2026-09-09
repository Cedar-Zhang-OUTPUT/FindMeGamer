# Analyze desktop acceptance — 2026-09-09

Parent C commit287cc27. Scope: desktop only, immutable accepted Steam/YouTube/X/jobs contracts, runtime5706ad76f924991b80ee2a7fb6806528366be5ce and actual migration20260908_0019. No backend, migration, contract, credential, provider configuration, deployment or mail changes. No push. Root and three bounded workers used the requested inherited Astra/Medium workflow.

## Delivered

- Narrow validated main-process/IPC/preload Analyze methods: Steam source import, YouTube first binding, create/detail/changed/retry/resume. Workspace headers never enter renderer; redirects refused, response bounds enforced, late connection generations fenced.
- Library source-only Steam import/refresh or explicit binding to selected Game UUID/revision. YouTube URL-only profile binds its selected UUID before an independent Analyze confirmation. Bound YouTube and numeric X use canonical reanalyze even without an analysis date. Twitch/Instagram remain unsupported; no X handle resolver is invented.
- Retained nonmodal task drawer: explicit confirmation, actual queued/running/stage/waiting states, bounded serialized polling, manual refresh, failed retry/new job, explicit same-job resume, existing-profile outcome, opaque mixed history cursor, explicit View profile. Completion does not navigate/scroll/replace user input.
- Frozen uncertain request/key/body with24h replay window. Unsuccessful replay cannot unlock original source input. Fenced/expired operations can be explicitly acknowledged and retained as **unconfirmed** records for the current window, never treated as success/cancellation or silently resubmitted. Cross-workspace profile links are suppressed. Closing the window loses these local review records and warns while retained. Plain saved task history does not lock workspace connection settings.
- Actual read-only Creator brief/analysis/source coverage and lazy Game analysis. At most three distinct supported observations initially, evidence and remaining/unavailable fields disclosed on demand. X labels one-page recent original posts/sample size/limit/more-available, not full history. No fabricated model observations, language, contact verification, or watched-video claims.

## TDD and bounded reviews

Missing-module REDs preceded source/drawer/adapter implementation; gateway/preload failed before wiring. One bounded cross-review for adapter/integration found the missing accepted Match queue-failure message; exact mixed-feed regression went RED→GREEN. One bounded renderer review found loss of unknown provenance after unsuccessful source replay, and expired/fenced recovery dead ends; focused regressions went RED→GREEN. No second broad review or F8/P7/C rerun.

Actual read-only API acceptance initially failed in existing YouTube works: new nullable provider `language`/`language_source_field` were rejected by desktop source metadata validation. Exact regression RED→GREEN; accepted only as bounded read-only metadata, still rejected in manual writes. Backend unchanged. Root also corrected a demonstrated read-only-history Settings lock and completed drawer button/dark-theme styling from actual screenshots.

Fresh final **15 targeted files,158/158 passed**,9.11s. Includes Analyze client/transport/gateway/preload/workspace, source import, insights, Library entry flow, Creator client/Library/record, Game renderer, navigation guards, collection settings and sending flow. **Typecheck, build and git diff --check passed**. This is not a full product/backend suite. Build124modules;626.38kB JS and115.64kB CSS; existing >500kB chunk warning remains.

## Real isolated acceptance

Private ledger directory (do not publish its client credentials):
`/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-xmmhoufp/private`

1. Failed read-only attempt: `analyze-api-a61804c5-c46a-46ca-810a-4daba1212ab5.json`, no writes, saved jobs/history succeeded before source-work decoder failed. Preserved, not relabeled successful.
2. Corrected real production-client API **1/1 passed**,524ms/888ms runner: `analyze-api-c6afd3be-305b-4a9e-84e2-8ce58fea35ed.json`.11GET,0writes; saved three identities, six report job IDs (five success/one intentional historical failure), seven mixed-feed items,11YouTube works. No upstream effects.
3. Real built renderer **1/1 passed**,10.7s/11.3s runner: `analyze-renderer-64ff41e5-13ee-4166-81f6-25c4e7ffe85b.json`.28GET and **exactly4actual UI POSTs**: one Steam source refresh, then explicit Game/YouTube/X Analyze. Source-only revision3→4, exactly one Steam event and zero model calls; original analysis timestamps/manual/reference/favorite preserved. All three new jobs succeeded on original Library UUIDs and retained manual overrides. Game: one Steam, extraction, image download, visual and synthesis each. YouTube:11videos, two maps, two image downloads, visual, four reductions and Brief. X:21posts, three maps and one reduction. Exact bounded event counts were asserted. No repeated first binding, retry/resume/fault/SMTP writes. Four external profile images suppressed in this run; not artwork acceptance.
4. Final build GET-only renderer **1/1 passed**,1.3s/1.9s runner: `analyze-renderer-0e269376-6bb2-42c1-818a-c078c0f92353.json`.7GET,0POST/upstream events; existing X history→View profile→21-post coverage/Evidence; reopen drawer;760px/135%font/keyboard/Escape/reduced-motion; system dark mode. Measured drawer text contrast12.76:1, primary4.81:1, secondary12.76:1;9pxbuttonradius. Root inspected light profile/evidence and dark narrow screenshots. This final run follows narrow Settings guard/recovery-link and CSS refinements; the earlier four-write evidence is not claimed as a second final-build write run.

All renderer page/console/unexpected bridge/forbidden HTTP/blocked non-image counts0. Source/build/control hashes frozen within each run. Final source SHA256`7494ea2f271ecbafa9050b890f47bce1ced76cd2545d11bdb0ad7072d9e76b7d`, renderer`3ba8e69aa2454beaf52afd70ed5d9d9f62b8f320085800a9b42aa9c7efe86fa7`; final assets`index-KH0GqS5E.css`,`index-BaSw2f8c.js`.

Final fixture readback: actual0019,ownedRedisqueue0,activeanalysis0,nine succeeded/one intentionally historical failed. Controls unchanged, no containers restarted/stopped/reset and no old62611 changes. Latest jobs:Game97087ffd-2162-4c66-8f19-0a9ff38d6e0c;YouTube8ed658b8-3497-4ba0-a5f3-44c7c0e1d098;X445e6696-9e31-4e74-a7e4-5b7845181d87.

## Limits / handoff

API/auth/worker/checkpoints/DB/publication are real with **synthetic upstreams**. Production renderer calls restricted production Node clients, not native Electron/IPC/preload/Keychain/installed-app acceptance. Native business-method wiring has targeted tests only. No live provider permission/model-quality/send claims.

YouTube first binding success/source preservation is component and contract coverage here: the finite fixture already owns the canonical channel, so no duplicate binding was attempted. Failed job history is actually displayed; retry, explicit resume, unknown/expiry/credential fencing/return modification and empty/error states are component-tested, **not actual UI recovery writes** in this run. No fault toggles or collection writes were executed. These limits should remain visible in the coordinator's acceptance summary.

Current screenshots: `desktop/output/playwright-analyze-readonly/analyze-renderer-Analyze-b-4a7f6-e-existing-saved-identities/analysis-readonly-x-evidence.png`, `analysis-readonly-light-narrow.png`, `analysis-readonly-dark-narrow.png`. Initial four-write screenshots in the analogous `output/playwright-analyze-renderer` directory. Main task owns local integration and any subsequently authorized GitHub action; no upload authorization was assumed.
