# Native Discover development acceptance — 2026-09-14

Code tested: `99f3f05306e33b557e956d19d090c817c2025f04` on `codex/native-profile-editing`, following Task 1–6 baseline `fc7235d`. This document is a development handoff, not a production release record. No deployment, production migration, queue change, publication, data reset, spend-limit change, or SMTP delivery was performed.

## Evidence boundaries

| Check | Real components | Simulated or limited components |
|---|---|---|
| Native HTTP lifecycle | Swift generated OpenAPI client, URLSession, loopback FastAPI, isolated PostgreSQL, ordinary Game/Creator/X/Discover/batch/Match worker entry points, all Match stages | Steam, YouTube/X discovery/source adapters, model output, artifact store and email research; explicit stage delivery substitutes for Redis/Celery broker publication |
| Process restart | Actual fixture container restart, native HTTP reopen, duplicate worker execution against persisted rows | No process termination during an in-flight provider request; no real broker-loss injection in this fixture |
| Live discovery | New `YouTubeDiscovery.search` and `XDiscovery.search`, real official upstream HTTP responses and filter metadata | Bounded adapter reads, not a cloud Discover request; no model or business writes |
| Live selected X analysis | One selected real discovery account; local selected-batch API, ordinary worker, `ProductionAnalysisRuntime`, real X account/timeline, real `deepseek-flash`, checkpoints, filesystem artifacts and transactional Creator publication | Synthetic local Game and manually persisted discovery handoff; TestClient rather than Swift for this live batch; broker delivery simulated; final replay copied three validated real checkpoints into a new local job |

The live sources/model are not replaced with a synthetic success. The first live job failed validation and remains preserved. Only the final real model output passed the unchanged schema, citation and contact binding checks and published a Profile. The checkpoint handoff is an acceptance harness operation: the public manual retry API creates a new job and does not copy terminal-job checkpoints. It is not claimed as a product retry feature.

## Native HTTP acceptance

Dedicated fixture: `backend/tests/native_discover_http_fixture.py`; native client tests: `macos/Tests/FindMeGamerCoreTests/NativeDiscoverHTTPAcceptanceTests.swift`.

- Compose project/network `fmg-native-edit` / `fmg-native-edit_default`; Discover fixture container `fmg-native-edit-discover-http-acceptance`; host binding only `127.0.0.1:18765`.
- Exact Discover database `find_me_gamer_discover_http_acceptance` on `postgres-test`. Fixture validates driver, host and database before connecting/migrating. It rejects the standard pytest DB, production host, SQLite, and old Profile fixture DB.
- Existing Profile fixture on `18764` / `find_me_gamer_native_http_acceptance` was left intact. An initial unsuccessful synthetic fixture database was retained as `find_me_gamer_discover_http_attempt1`; no database was dropped or cleared.
- A missing Steam game resolves a name without submitting analysis; Discover then waits in `preparing_game` for its ordinary Game job and resumes with five homepage candidates. Discovery creates no Creator Profiles.
- Native select-all/deselect-all, four-candidate subset, and confirmation Cancel leave the server batch list unchanged. The same Discover key and same selected-analysis key each return the same record.
- Selected analysis joins one already queued ordinary job, reuses one current Library Profile, succeeds for one YouTube and one X Profile, and records one explicit source failure. The fifth candidate remains unanalysed.
- The partial batch links exactly one ordinary Match. Its four locked inputs include an older unselected eligible Library Creator; the fact-only seed is excluded. Screening, pairwise, advancement and ranking all execute to `succeeded`.
- After an actual container restart, reopening and duplicate execution preserve Analysis/Profile/Match counts, the original Match ID, old manual overrides and the edited X title. Native X detail/edit/manual-contact HTTP round trips pass. No SMTP route is enabled and the fake SMTP counter stays zero.

First full lifecycle passed in **3.097 seconds**; process-restart replay passed in **0.444 seconds**. Test red evidence includes absent fixture connection and fixture setup errors (historic helper clock, strict UUID test output), corrected only in the fixture. Fixture database guard red: four missing-module failures before implementation. No backend behavior was changed to make synthetic output pass.

Task 5 already recorded actual native GUI observations for fourth/fifth picker rows, final candidate row, keyboard selection, Escape/Cancel, disabled channels and Match navigation. Those observations are not repeated or presented as external-provider proof. This task supplies the separate real API lifecycle and X edit evidence.

## Bounded real provider evidence

Controller adapter run began `2026-09-14T13:57:31Z`, baseline adapter code `fc7235d` (unchanged in this task). Query `indie horror gameplay` returned YouTube pages of 16 and 5 candidates, **21 unique**, no duplicates. Query `"indie horror" OR "horror game"` returned X pages of 22 and 17 candidates, **39 unique**, no duplicates. Every returned candidate carried observed English metadata and follower count between 1,000 and 1,000,000.

Eight total HTTP requests, all 200: YouTube `/youtube/v3/search`, `/videos`, `/channels` twice each, and X `/2/tweets/search/recent` twice. At most two pages per provider; no promise of filling 100 candidates. These are the new adapters, not the earlier direct-endpoint feasibility probe.

Selected account: public X ID `1555959738566950912`, canonical `https://x.com/i/user/1555959738566950912`, title `KitzuRei || Horror Variety`.

| Phase | Real requests | Outcome |
|---|---|---|
| Initial selected batch, `14:01:03Z` | X account + timeline: 2 HTTP 200; DeepSeek: 3 HTTP 200 | Source, metadata and contact checkpoints validated; synthesis failed with `deepseek_model_output_invalid`; no Profile |
| Synthesis-only diagnostic | DeepSeek: 2 HTTP 200; no new source/metadata/contact calls | Initial 24,345-character output violated inference/compact Brief rules; 22,228-character repair was invalid JSON |
| Corrected prompt checkpoint replay, `14:06:24Z` | DeepSeek: 2 HTTP 200; no new source/metadata/contact calls | Both responses had `finish_reason=stop` (21,875 and 21,563 characters); normal bounded pipeline retry yielded validated synthesis and published a current X Profile |

Total analysis/diagnostic model requests: **7**, all `deepseek-flash`. Total X acquisition reads: **2**. Adding separate discovery gives **17 provider/model HTTP requests** across this acceptance. No credit/cap error occurred and no limits were changed. The first diagnostic did not retain exact finish reasons; absence of a truncation warning is not proof of a specific finish reason. The final replay explicitly recorded `stop`.

The failure identified missing prompt guidance, not an invalid schema requirement: audience claims require `provenance=ai_inference` and evidence `kind=ai_inference`; compact Brief references permit only `kind`, `source_type`, `reference`; Brief lists permit at most three unique values. X prompt version `x-creator-v2` now states those existing constraints and the 8,000-byte Brief budget. Schemas, source identity, citation checks and honest unavailable fields are unchanged. The trusted-prompt regression failed before this change; the covering X tests passed afterward.

Final live batch `a9db2685-e011-416d-8ea1-d159ac337cb1` is `done`; job `6e94e1dc-7c2f-469a-8839-c784a29a7b25` is `succeeded`; Profile `a5fbb766-8435-4d7b-bca3-4a199838e348` has ten Brief fields, current X source, unavailable visual analysis, and one validated `profile_description` contact. Original failed job `23771fdd-ddf7-4327-ad92-ded2f388f6f5` and its failed batch remain intact.

Gemini email fallback was **not exercised**: the account description supplied a validated contact, and there were zero Google API calls. Runtime performed its normal optional-key lookup; the runner did not retain the optional key's presence as evidence. This does not prove live fallback enrichment. SMTP calls were zero in every phase.

Credentials were decrypted in the existing backend read-only session with rollback, transported through process memory, and never emitted to logs, frontend, committed fixtures or reports. Real calls used the existing local proxy via injected HTTP clients; provider URL/response safeguards remained active. No unproxied network route is claimed. Live DB `find_me_gamer_discover_live_acceptance` is separate from both HTTP fixtures and pytest; local public-source artifacts remain under ignored `.local/task7/artifacts`.

## Verification and reproducibility

Run commands from the native worktree unless noted. Logs are ignored development evidence under `.local/task7/`.

```sh
# Dedicated HTTP server, after explicitly creating the exact empty fixture DB once:
cd backend
docker compose -p fmg-native-edit -f compose.test.yaml run -d \
  --name fmg-native-edit-discover-http-acceptance -p 127.0.0.1:18765:8000 \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres-test:5432/find_me_gamer_discover_http_acceptance \
  test python -m tests.native_discover_http_fixture
cd ../macos
FMG_DISCOVER_HTTP_ACCEPTANCE=1 swift test --no-parallel --filter NativeDiscoverHTTPAcceptanceTests
docker restart fmg-native-edit-discover-http-acceptance
FMG_DISCOVER_HTTP_RESUME=1 swift test --no-parallel --filter persistedSuccessSurvivesServerProcessRestartAndDuplicateWorkers
```

The first test requires a fresh dedicated fixture database and is intentionally not a reset endpoint. Reuse the resume test against the retained successful database. Before starting a fresh initial run, explicitly retain/rename the old synthetic DB and provision the exact fixture DB again; never target the old Profile fixture or a business DB.

Verification commands and evidence:

- `docker compose -p fmg-native-edit -f compose.test.yaml run --rm test pytest tests/unit/test_native_discover_http_fixture_guard.py tests/integration/test_creator_identity_migration.py tests/integration/test_discover_migration.py -q` — 7 passed; `migration-guard.log`.
- Expanded populated migration `pytest tests/integration/test_creator_identity_migration.py -q` — 1 passed; `migration-expanded-green.log`. Starts at deployed lineage `20260914_native_0008`, inserts synthetic Game, Creator/manual overrides, contact, successful Analysis history and frozen Match history, then upgrades to `20260914_native_0012`. All existing row columns match exactly; only new Creator identity columns are added. Standard isolated pytest DB only.
- Prompt regression red: `pytest tests/unit/analysis/test_x_creator_pipeline.py -q` — 1 failed / 2 passed; `x-prompt-red.log`. Covering green with `tests/integration/test_x_creator_analysis.py` — 29 passed; `x-prompt-green-final.log`.
- Native first-flow/restart logs: `http-green.log`, `http-restart.log`.
- Real evidence: `live-analysis.log`, `synthesis-diagnostic.log`, `synthesis-retry.log`; backend-only scratch runners `live_analysis.py`, `diagnose_synthesis.py`, `retry_synthesis.py`. They are historical bounded probes, not unattended monitoring commands. Re-running them incurs new provider calls and requires a fresh scoped acceptance plan.
- Final backend: `docker compose -p fmg-native-edit -f compose.test.yaml run --rm test pytest -q`; `backend-full.log` — **1,986 passed, 3 skipped, 1 existing warning, 148.07 seconds**.
- Final native: `swift test --no-parallel`; `swift-full.log` — **358 tests / 54 suites passed, 6.807 seconds**. Opt-in live/HTTP tests are separately covered above.
- API snapshot: committed Swift source digest equals backend OpenAPI SHA-256; `openapi-snapshot.log`. The final backend contract tests verify the exported contract as well.
- Native app build: `./script/build_and_run.sh --demo`; `native-build.log` — **passed, 12.09 seconds**. `dist/FindMeGamer.app` is an arm64 local Demo bundle (`FMGDemoMode=true`); it is not a universal, notarized or published colleague package.

## Future authorized release and maintenance

Release execution remains a separate action after independent review. Use the current native deployment described in `docs/native-release-0.3.0-2026-09-14.md`: source `/opt/find-me-gamer-native-030`, env `/etc/find-me-gamer/native.env`, native DB `find_me_gamer_native_20260914`, Redis `/1`. Do not repeat the original empty-DB cutover/settings import or run the old `ops/deploy.sh`.

For a future approved maintenance release: stage the reviewed commit and image; verify the explicit native DB/Redis configuration; stop API, Worker and Beat together; take and verify a fresh complete native backup and protected configuration/image record; then run the additive migration. There is no zero-downtime compatibility claim. Retain both the current native data and the old v2 DB.

```sh
cd /opt/find-me-gamer-native-030
sudo docker compose -p find-me-gamer --env-file /etc/find-me-gamer/native.env \
  -f compose.yaml -f runtime.override.yaml stop api worker beat
sudo systemctl start find-me-gamer-backup.service
sudo systemctl status find-me-gamer-backup.service --no-pager
# Verify the fresh native dump/checksum and protected configuration backup before proceeding.
# Point all three application services at the staged reviewed image, preserving DB and Redis /1.
sudo docker compose -p find-me-gamer --env-file /etc/find-me-gamer/native.env \
  -f compose.yaml -f runtime.override.yaml run --rm --no-deps api python -c \
  'from app.core.config import get_settings; from sqlalchemy.engine import make_url; assert make_url(get_settings().database_url).database == "find_me_gamer_native_20260914"'
sudo docker compose -p find-me-gamer --env-file /etc/find-me-gamer/native.env \
  -f compose.yaml -f runtime.override.yaml run --rm --no-deps api alembic upgrade head
sudo docker compose -p find-me-gamer --env-file /etc/find-me-gamer/native.env \
  -f compose.yaml -f runtime.override.yaml up -d --no-deps api worker beat
```

Then verify readiness, authenticated Discover/Library/Match reads and retained business row inventories. Do not test real SMTP as a deployment smoke test. If migration/startup fails, keep all three services stopped, preserve new evidence/writes, and restore the verified pre-upgrade native backup and matching image/configuration as an explicitly approved maintenance rollback; do not automatically downgrade/drop data.

After a release version is approved, build a real-service internal package using the existing release workflow, for example with explicit `APP_VERSION`, `SERVICE_BASE_URL=https://44.233.174.193`, `ADHOC_RELEASE=1`, `RELEASE_ARCHITECTURES=universal`, `RELEASE_FORMAT=dmg`, then `./script/build_release.sh`. Verify checksum, mounted bundle, both architectures, OS minimum, Demo-off metadata and signatures before separately authorized upload/update-feed promotion. Physical Intel/macOS 14, notarization, real broker delivery, broad provider coverage and live Gemini fallback remain outside this sample.
