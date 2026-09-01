# Backend Foundation, Library, and Analyze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-shaped FastAPI/Celery backend that authenticates the shared workspace, stores the shared Library, analyzes Steam games and YouTube creators, polls Jobs, refreshes Profiles, and seeds the initial Creator set.

**Architecture:** A synchronous FastAPI API and Celery worker share SQLAlchemy repositories backed by PostgreSQL; Redis is used only as Celery's broker. External Steam, YouTube, DeepSeek, and S3 gateways sit behind protocols so pipelines can be tested with deterministic fakes. Profile replacement and Job state changes are transactional, while acquisition and model calls occur outside long-running database transactions.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, Celery 5, Redis, HTTPX, boto3, argon2-cffi, cryptography, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-02-find-me-gamer-design.md`

## Global Constraints

- The backend base path is `/api/v1`; internal requests use a bearer Workspace Access Key.
- PostgreSQL is the sole source of truth for business state; Redis never owns final Job status.
- Job states are exactly `queued`, `running`, `succeeded`, and `failed`.
- Analyze deduplicates globally by Steam App ID or YouTube Channel ID.
- A failed Re-analyze never replaces the previous current Profile.
- All prompts and generated content are English.
- YouTube analysis uses official API metadata for the 50 most recent public videos and about 12 official thumbnails; it never downloads video/audio, extracts frames, or uses unofficial transcripts.
- Creator automatic Re-analyze is mandatory at 1–30 days, default 14; Game automatic Re-analyze is mandatory at 1–90 days, default 30.
- Temporary acquisition artifacts use an S3 prefix with a lifecycle of no more than 30 days.
- Secret plaintext is never returned by an API or written to logs.
- Every task follows TDD and ends with a focused commit.

## File Map

- `backend/pyproject.toml` — Python package metadata, runtime dependencies, pytest configuration.
- `backend/Dockerfile` — reproducible Python 3.13 API/worker image.
- `backend/compose.test.yaml` — PostgreSQL, Redis, and test runner for local verification.
- `backend/alembic.ini`, `backend/migrations/` — database migrations.
- `backend/app/main.py` — FastAPI application and middleware assembly only.
- `backend/app/core/` — configuration, database sessions, security, encryption, errors, and idempotency.
- `backend/app/db/models/` — SQLAlchemy persistence models grouped by business area.
- `backend/app/schemas/` — public Pydantic request/response contracts and internal AI output schemas.
- `backend/app/repositories/` — database query and mutation boundaries.
- `backend/app/api/routes/` — thin HTTP resource handlers.
- `backend/app/integrations/` — Steam, YouTube, DeepSeek, and S3 gateways.
- `backend/app/analysis/` — URL resolution, prompts, pipeline orchestration, and Profile assembly.
- `backend/app/workers/` — Celery application, tasks, and Beat schedule.
- `backend/app/cli/seed_creators.py` — resumable CSV import command.
- `backend/tests/unit/` — pure domain and gateway tests.
- `backend/tests/integration/` — PostgreSQL/API/Celery contract tests.
- `backend/openapi.json` — deterministic generated client contract, committed after API completion.

---

### Task 1: Reproducible backend scaffold and health endpoints

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/Dockerfile`
- Create: `backend/compose.test.yaml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/api/routes/health.py`
- Create: `backend/tests/unit/test_health.py`

**Interfaces:**
- Produces: `app.main:create_app() -> FastAPI`
- Produces: `app.core.config:get_settings() -> Settings`
- Produces: `GET /health/live` and `GET /health/ready`

- [ ] **Step 1: Write the failing health tests**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_live_health_is_process_only() -> None:
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_title_is_stable() -> None:
    assert create_app().title == "Find Me Gamer API"
```

- [ ] **Step 2: Run the test and verify the scaffold is missing**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_health.py -q`

Expected: FAIL because `app.main` does not exist.

- [ ] **Step 3: Add the package, image, test Compose file, settings, and app factory**

Use Python `>=3.13,<3.14`. Declare FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy, psycopg, Alembic, Celery Redis support, HTTPX, boto3, argon2-cffi, cryptography, markdown-it-py, bleach, email-validator, and pytest dependencies. The app factory must include the health router:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Find Me Gamer API", version="1.0.0")
    app.include_router(health.router)
    return app


app = create_app()
```

`compose.test.yaml` must expose isolated `postgres-test` and `redis-test` services and run tests with `DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres-test:5432/find_me_gamer_test`.

- [ ] **Step 4: Run the health tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_health.py -q`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "build: scaffold backend service"
```

---

### Task 2: Database session, enums, and first migration

**Files:**
- Create: `backend/app/core/database.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/models/enums.py`
- Create: `backend/app/db/models/profiles.py`
- Create: `backend/app/db/models/jobs.py`
- Create: `backend/app/db/models/settings.py`
- Create: `backend/app/db/models/idempotency.py`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/20260902_0001_initial.py`
- Create: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `app.core.database:session_scope() -> Iterator[Session]`
- Produces: `TargetType`, `JobMode`, `JobStatus`, and `AnalysisStage` string enums.
- Produces: tables `game_profiles`, `creator_profiles`, `creator_contacts`, `analysis_jobs`, `shared_settings`, `service_secrets`, and `idempotency_records`.

- [ ] **Step 1: Write a migration smoke test**

```python
def test_initial_migration_creates_core_tables(database_inspector) -> None:
    names = set(database_inspector.get_table_names())
    assert {
        "game_profiles", "creator_profiles", "creator_contacts",
        "analysis_jobs", "shared_settings", "service_secrets",
        "idempotency_records",
    } <= names
```

- [ ] **Step 2: Verify it fails before the migration exists**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_migrations.py -q`

Expected: FAIL with missing table names.

- [ ] **Step 3: Implement models and migration**

Use UUID primary keys, timezone-aware timestamps, PostgreSQL JSONB for current facts/analysis/brief payloads, unique constraints on `steam_app_id` and `youtube_channel_id`, and a PostgreSQL partial unique index on `(target_type, canonical_target_id)` only where Analysis Job status is `queued` or `running`. This preserves Job history while preventing concurrent duplicates. Define the central enum exactly:

```python
class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
```

Seed one `shared_settings` row with Creator interval 14, Game interval 30, hidden recommended threshold `0.70`, and SMTP rate 10.

- [ ] **Step 4: Upgrade from an empty database and run the test**

Run: `docker compose -f backend/compose.test.yaml run --rm test sh -c 'alembic upgrade head && pytest tests/integration/test_migrations.py -q'`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/database.py backend/app/db backend/alembic.ini backend/migrations backend/tests/integration/test_migrations.py
git commit -m "feat: add core database schema"
```

---

### Task 3: Workspace authentication, error envelope, and correlation IDs

**Files:**
- Create: `backend/app/core/security.py`
- Create: `backend/app/core/errors.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/app/core/rate_limit.py`
- Create: `backend/app/api/dependencies.py`
- Create: `backend/app/api/routes/session.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_security.py`
- Create: `backend/tests/integration/test_session_api.py`

**Interfaces:**
- Produces: `hash_workspace_key(raw: str) -> str`
- Produces: `verify_workspace_key(raw: str, encoded_hash: str) -> bool`
- Produces: authenticated `GET /api/v1/session`
- Produces: errors shaped as `{"error":{"code":str,"message":str,"retryable":bool,"correlation_id":str}}`.
- Produces: Workspace-key rate limiting and secret-safe structured request logs.

- [ ] **Step 1: Write failing key and API tests**

```python
def test_workspace_key_round_trip() -> None:
    encoded = hash_workspace_key("demo-key")
    assert verify_workspace_key("demo-key", encoded)
    assert not verify_workspace_key("wrong", encoded)


def test_session_rejects_missing_bearer(client) -> None:
    response = client.get("/api/v1/session")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "workspace_key_invalid"
    assert response.headers["x-correlation-id"]


def test_request_log_redacts_authorization(client, captured_logs) -> None:
    client.get("/api/v1/session", headers={"Authorization": "Bearer never-log-me"})
    assert "never-log-me" not in captured_logs.text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_security.py tests/integration/test_session_api.py -q`

Expected: FAIL because security and session routes are absent.

- [ ] **Step 3: Implement Argon2id authentication and exception middleware**

Use `argon2.PasswordHasher` and `hmac.compare_digest` where raw digests are compared. Generate or propagate `X-Correlation-ID` per request and keep public error messages safe. Apply a Redis-backed fixed-window limit keyed by Workspace-key hash and client address; Redis holds only counters, never business state. Structured logging allowlists method, route template, status, duration, and correlation ID and rejects authorization headers, query response tokens, credentials, request bodies, and email bodies. Session output contains only workspace name, API version, and sanitized connection-state booleans.

- [ ] **Step 4: Run focused tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_security.py tests/integration/test_session_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core backend/app/api backend/app/main.py backend/tests
git commit -m "feat: authenticate shared workspace"
```

---

### Task 4: Encrypted shared service connections and schedule settings

**Files:**
- Create: `backend/app/core/crypto.py`
- Create: `backend/app/schemas/settings.py`
- Create: `backend/app/repositories/settings.py`
- Create: `backend/app/api/routes/settings.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_crypto.py`
- Create: `backend/tests/integration/test_settings_api.py`

**Interfaces:**
- Produces: `SecretCipher.from_file(path: Path) -> SecretCipher`
- Produces: `SecretCipher.encrypt(plaintext: str) -> EncryptedValue`
- Produces: `SecretCipher.decrypt(value: EncryptedValue) -> str`
- Produces: `GET/PATCH /api/v1/settings/reanalysis`
- Produces: `GET/PUT/POST /api/v1/settings/connections/{service}` for status, replacement, and tests.

- [ ] **Step 1: Write failing encryption and redaction tests**

```python
def test_aes_gcm_round_trip_and_random_nonce(tmp_path) -> None:
    cipher = SecretCipher(bytes(range(32)))
    one = cipher.encrypt("secret")
    two = cipher.encrypt("secret")
    assert one.nonce != two.nonce
    assert cipher.decrypt(one) == "secret"


def test_connection_read_never_returns_plaintext(auth_client) -> None:
    auth_client.put("/api/v1/settings/connections/youtube", json={"secret": "yt-key"})
    body = auth_client.get("/api/v1/settings/connections/youtube").json()
    assert body["configured"] is True
    assert "yt-key" not in str(body)
```

- [ ] **Step 2: Run tests and see them fail**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_crypto.py tests/integration/test_settings_api.py -q`

Expected: FAIL because encryption and routes are missing.

- [ ] **Step 3: Implement AES-256-GCM storage and validated settings**

The master key file must decode to exactly 32 bytes. Store ciphertext and nonce separately. Validate schedules with constrained integers:

```python
class ReanalysisSettingsUpdate(BaseModel):
    creator_interval_days: Annotated[int, Field(ge=1, le=30)]
    game_interval_days: Annotated[int, Field(ge=1, le=90)]
```

Connection reads return `configured`, `last_test_status`, and `last_tested_at` only. Connection tests call an injected gateway probe so integration tests never use real secrets.

- [ ] **Step 4: Run encryption and settings tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_crypto.py tests/integration/test_settings_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/crypto.py backend/app/schemas/settings.py backend/app/repositories/settings.py backend/app/api/routes/settings.py backend/app/main.py backend/tests
git commit -m "feat: manage encrypted service settings"
```

---

### Task 5: Profile schemas, Library queries, favorites, and manual contact

**Files:**
- Create: `backend/app/schemas/common.py`
- Create: `backend/app/schemas/profiles.py`
- Create: `backend/app/repositories/profiles.py`
- Create: `backend/app/api/routes/profiles.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_profiles_api.py`

**Interfaces:**
- Produces: cursor-page `GET /api/v1/profiles/games` and `/creators`.
- Produces: `GET /api/v1/profiles/{type}/{id}`.
- Produces: `PATCH /api/v1/profiles/{type}/{id}/favorite`.
- Produces: `PATCH /api/v1/profiles/creators/{id}/manual`.

- [ ] **Step 1: Write failing Library API tests**

```python
def test_creator_library_search_collection_and_cursor(auth_client, creators) -> None:
    response = auth_client.get(
        "/api/v1/profiles/creators",
        params={"query": "strategy", "only_collection": True, "limit": 1},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["next_cursor"] is not None


def test_manual_contact_takes_priority(auth_client, creator_id) -> None:
    response = auth_client.patch(
        f"/api/v1/profiles/creators/{creator_id}/manual",
        json={"contact_email": "team@example.com", "notes": "Warm lead"},
    )
    assert response.json()["contact"]["source"] == "manual"
```

- [ ] **Step 2: Run tests to verify missing endpoints**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_profiles_api.py -q`

Expected: 404 failures.

- [ ] **Step 3: Implement typed card/detail schemas and queries**

Use opaque base64 cursors containing `(sort_name, id)`, stable ordering, `limit` constrained to 1–100, case-insensitive server search, and a shared favorite flag. Creator output must choose the active manual contact before discovered contacts. Hide YouTube-derived facts when `source_status == "stale"` while retaining manual contact and notes.

- [ ] **Step 4: Run Profile tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_profiles_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/app/repositories/profiles.py backend/app/api/routes/profiles.py backend/app/main.py backend/tests/integration/test_profiles_api.py
git commit -m "feat: expose shared profile library"
```

---

### Task 6: Analyze URL resolution, Job creation, and idempotency

**Files:**
- Create: `backend/app/analysis/targets.py`
- Create: `backend/app/core/idempotency.py`
- Create: `backend/app/schemas/jobs.py`
- Create: `backend/app/repositories/jobs.py`
- Create: `backend/app/api/routes/jobs.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_targets.py`
- Create: `backend/tests/integration/test_analysis_job_creation.py`

**Interfaces:**
- Produces: `canonicalize_target(target_type: TargetType, raw_url: str) -> CanonicalTarget`.
- Produces: `POST /api/v1/jobs/analysis` with required `Idempotency-Key`.
- Produces: `POST /api/v1/jobs/analysis/{job_id}/retry`.

- [ ] **Step 1: Write failing canonicalization and deduplication tests**

```python
@pytest.mark.parametrize(
    ("target_type", "url", "expected"),
    [
        (TargetType.GAME, "https://store.steampowered.com/app/1245620/ELDEN_RING/", "1245620"),
        (TargetType.CREATOR, "https://www.youtube.com/channel/UCabc123", "UCabc123"),
        (TargetType.CREATOR, "https://www.youtube.com/@ExampleCreator", "@examplecreator"),
    ],
)
def test_canonical_target(target_type, url, expected) -> None:
    assert canonicalize_target(target_type, url).canonical_id == expected


def test_duplicate_active_job_is_returned(auth_client) -> None:
    headers = {"Idempotency-Key": "same-request"}
    payload = {"target_type": "game", "url": "https://store.steampowered.com/app/1245620"}
    first = auth_client.post("/api/v1/jobs/analysis", headers=headers, json=payload)
    second = auth_client.post("/api/v1/jobs/analysis", headers=headers, json=payload)
    assert first.json()["id"] == second.json()["id"]
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_targets.py tests/integration/test_analysis_job_creation.py -q`

Expected: FAIL with missing target resolver and endpoint.

- [ ] **Step 3: Implement strict resolution and transactional creation**

Reject unsupported hosts and malformed IDs. A YouTube Handle is resolved to Channel ID before global deduplication by the YouTube gateway. For a completed existing Profile and `mode=create`, return a response with `existing_profile_id` and no new Job. For `mode=reanalyze`, create a Job unless one for the canonical target is already queued/running. Persist the idempotency response with a hash of method, path, and canonical request JSON; reuse of a key with a different request returns HTTP 409.

- [ ] **Step 4: Run target and Job creation tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/test_targets.py tests/integration/test_analysis_job_creation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/targets.py backend/app/core/idempotency.py backend/app/schemas/jobs.py backend/app/repositories/jobs.py backend/app/api/routes/jobs.py backend/app/main.py backend/tests
git commit -m "feat: create deduplicated analysis jobs"
```

---

### Task 7: Steam, YouTube, S3, and DeepSeek gateway contracts

**Files:**
- Create: `backend/app/integrations/errors.py`
- Create: `backend/app/integrations/steam.py`
- Create: `backend/app/integrations/youtube.py`
- Create: `backend/app/integrations/s3.py`
- Create: `backend/app/integrations/deepseek.py`
- Create: `backend/app/analysis/contracts.py`
- Create: `backend/tests/unit/integrations/test_steam.py`
- Create: `backend/tests/unit/integrations/test_youtube.py`
- Create: `backend/tests/unit/integrations/test_deepseek.py`
- Create: `backend/tests/unit/integrations/test_s3.py`

**Interfaces:**
- Produces: `SteamGateway.fetch_game(app_id: str) -> SteamGameSource`.
- Produces: `YouTubeGateway.resolve_channel(target: CanonicalTarget) -> str`.
- Produces: `YouTubeGateway.fetch_creator(channel_id: str, video_limit: int = 50) -> CreatorSource`.
- Produces: `DeepSeekGateway.complete_structured(model: str, messages: list[Message], schema: type[T]) -> T`.
- Produces: `DeepSeekGateway.complete_vision(model: str, prompt: str, image_urls: list[str], schema: type[T]) -> T`.
- Produces: `ArtifactStore.put_json(job_id: UUID, name: str, payload: Mapping[str, Any]) -> str`.

- [ ] **Step 1: Write failing gateway contract tests with HTTPX MockTransport**

```python
def test_youtube_fetches_only_fifty_recent_videos(youtube_gateway, requests_seen) -> None:
    source = youtube_gateway.fetch_creator("UC123", video_limit=50)
    assert len(source.videos) == 50
    assert all(request.host == "www.googleapis.com" for request in requests_seen)


def test_deepseek_rejects_invalid_structured_output(deepseek_gateway) -> None:
    with pytest.raises(InvalidModelOutput):
        deepseek_gateway.complete_structured("deepseek-v4-flash", [], GameExtraction)
```

- [ ] **Step 2: Run gateway tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/integrations -q`

Expected: FAIL because gateways do not exist.

- [ ] **Step 3: Implement bounded, timeout-aware gateways**

Use explicit connect/read timeouts, translate HTTP 429/5xx/timeouts into `TransientIntegrationError`, translate invalid/not-found targets into `PermanentIntegrationError`, and never log request authorization headers. YouTube calls only official `channels`, `playlistItems`, and `videos` endpoints. Keep every external base URL injectable through server `AppSettings` so integration tests can point the same production gateway code at local stubs; these base URLs are not exposed in the macOS Settings UI. S3 keys use `acquisition/{job_id}/{name}` and attach a lifecycle class/prefix expected by deployment. DeepSeek parses model output directly into the provided Pydantic schema and performs exactly one repair request on schema failure.

- [ ] **Step 4: Run all gateway tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/integrations -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations backend/app/analysis/contracts.py backend/tests/unit/integrations
git commit -m "feat: add external analysis gateways"
```

---

### Task 8: Strict English AI schemas and prompt builders

**Files:**
- Create: `backend/app/schemas/ai_game.py`
- Create: `backend/app/schemas/ai_creator.py`
- Create: `backend/app/analysis/prompts/common.py`
- Create: `backend/app/analysis/prompts/game.py`
- Create: `backend/app/analysis/prompts/creator.py`
- Create: `backend/tests/unit/analysis/test_prompts.py`
- Create: `backend/tests/unit/analysis/test_ai_schemas.py`

**Interfaces:**
- Produces: `GameExtraction`, `GameVisualAnalysis`, `GameSynthesis`, `CreatorMetadataAnalysis`, `CreatorVisualAnalysis`, and `CreatorSynthesis` Pydantic schemas.
- Produces: pure prompt builders returning `list[Message]` with prompt version constants.

- [ ] **Step 1: Write failing schema and prompt tests**

```python
def test_game_prompt_fixes_language_and_evidence_rules() -> None:
    text = render_messages(build_game_synthesis_prompt(sample_game_source()))
    assert "Return English only" in text
    assert "Do not invent wishlist counts" in text


def test_creator_schema_requires_brief() -> None:
    with pytest.raises(ValidationError):
        CreatorSynthesis.model_validate({"short_summary": "Strategy channel"})
```

- [ ] **Step 2: Run prompt tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/analysis/test_prompts.py tests/unit/analysis/test_ai_schemas.py -q`

Expected: FAIL because builders and schemas are absent.

- [ ] **Step 3: Implement versioned prompts and complete output schemas**

Represent every Profile field listed in the specification. Require evidence-backed inference, explicit `unavailable` values where source data is absent, and an `english_language_check` field that must be true. Prompt constants are immutable strings such as `GAME_SYNTHESIS_PROMPT_VERSION = "game-synthesis-v1"`. Creator prompts explicitly prohibit transcript assumptions and distinguish facts from audience inference.

- [ ] **Step 4: Run schema and prompt tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/analysis/test_prompts.py tests/unit/analysis/test_ai_schemas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/ai_game.py backend/app/schemas/ai_creator.py backend/app/analysis/prompts backend/tests/unit/analysis
git commit -m "feat: define analysis prompts and schemas"
```

---

### Task 9: Transactional Game Analyze pipeline

**Files:**
- Create: `backend/app/analysis/game_pipeline.py`
- Create: `backend/app/analysis/service.py`
- Create: `backend/tests/unit/analysis/test_game_pipeline.py`
- Create: `backend/tests/integration/test_game_analysis_commit.py`

**Interfaces:**
- Produces: `GameAnalysisPipeline.run(job_id: UUID) -> UUID` returning the Game Profile ID.
- Consumes: gateway contracts from Task 7 and schemas/prompts from Task 8.

- [ ] **Step 1: Write failing atomicity and Vision fallback tests**

```python
def test_game_reanalysis_failure_preserves_current_profile(game_pipeline, existing_game, failing_ai) -> None:
    with pytest.raises(TransientIntegrationError):
        game_pipeline.run(existing_game.reanalysis_job_id)
    assert reload_game(existing_game.id).analysis == existing_game.analysis


def test_game_vision_failure_is_non_fatal(game_pipeline, vision_failure) -> None:
    profile_id = game_pipeline.run(queued_game_job_id())
    assert reload_game(profile_id).source_status["visual_analysis"] == "unavailable"
```

- [ ] **Step 2: Run Game pipeline tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/analysis/test_game_pipeline.py tests/integration/test_game_analysis_commit.py -q`

Expected: FAIL because `GameAnalysisPipeline` is absent.

- [ ] **Step 3: Implement fetch, Flash extraction, optional Vision, and Pro synthesis**

Set stages to `fetching_data`, `analyzing`, and `finalizing`. Store raw source JSON before model work. Do not hold a database transaction during network/model calls. At finalization, open one transaction that upserts by Steam App ID, replaces facts/analysis/Game Brief/model metadata, calculates `next_analysis_at`, and marks the Job succeeded. Any exception before that transaction leaves the previous Profile unchanged.

- [ ] **Step 4: Run Game pipeline tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/analysis/test_game_pipeline.py tests/integration/test_game_analysis_commit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/game_pipeline.py backend/app/analysis/service.py backend/tests
git commit -m "feat: analyze Steam game profiles"
```

---

### Task 10: Transactional Creator Analyze pipeline

**Files:**
- Create: `backend/app/analysis/creator_metrics.py`
- Create: `backend/app/analysis/creator_pipeline.py`
- Create: `backend/tests/unit/analysis/test_creator_metrics.py`
- Create: `backend/tests/unit/analysis/test_creator_pipeline.py`
- Create: `backend/tests/integration/test_creator_analysis_commit.py`

**Interfaces:**
- Produces: `select_representative_thumbnails(videos: Sequence[VideoSource], count: int = 12) -> list[VideoSource]`.
- Produces: `CreatorAnalysisPipeline.run(job_id: UUID) -> UUID` returning the Creator Profile ID.

- [ ] **Step 1: Write failing selection, preservation, and fallback tests**

```python
def test_thumbnail_selection_balances_recency_and_performance(videos) -> None:
    selected = select_representative_thumbnails(videos, count=12)
    assert len(selected) == 12
    assert any(video.id == videos[0].id for video in selected)
    assert max(v.view_count for v in videos) in {v.view_count for v in selected}


def test_reanalysis_preserves_manual_contact_and_notes(creator_pipeline, creator_with_manual_data) -> None:
    creator_pipeline.run(creator_with_manual_data.reanalysis_job_id)
    saved = reload_creator(creator_with_manual_data.id)
    assert saved.manual_notes == "Warm lead"
    assert active_contact(saved).email == "team@example.com"
```

- [ ] **Step 2: Run Creator tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/analysis/test_creator_metrics.py tests/unit/analysis/test_creator_pipeline.py tests/integration/test_creator_analysis_commit.py -q`

Expected: FAIL because Creator pipeline code is absent.

- [ ] **Step 3: Implement official-metadata analysis**

Fetch at most 50 recent public videos, compute average/median views and posting frequency, choose up to 12 thumbnails with deterministic recency/performance buckets, and store source JSON in S3. Run Flash metadata analysis, optional Vision thumbnail analysis, and Pro synthesis. Extract candidate business emails only from the public channel description and linked public websites; mark their source URL. Finalization atomically replaces analyzed fields and discovered contacts while preserving manual contacts and notes.

- [ ] **Step 4: Run Creator pipeline tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/analysis/test_creator_metrics.py tests/unit/analysis/test_creator_pipeline.py tests/integration/test_creator_analysis_commit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/creator_metrics.py backend/app/analysis/creator_pipeline.py backend/tests
git commit -m "feat: analyze YouTube creator profiles"
```

---

### Task 11: Celery execution, retry semantics, and changed-Job polling

**Files:**
- Create: `backend/app/workers/celery_app.py`
- Create: `backend/app/workers/analysis_tasks.py`
- Modify: `backend/app/api/routes/jobs.py`
- Create: `backend/tests/unit/workers/test_analysis_tasks.py`
- Create: `backend/tests/integration/test_job_polling_api.py`

**Interfaces:**
- Produces: Celery task `run_analysis_job(job_id: str) -> None`.
- Produces: `GET /api/v1/jobs?changed_after=<cursor>&status=<status>`.
- Produces: durable safe failure metadata and Retry behavior.

- [ ] **Step 1: Write failing retry and polling tests**

```python
def test_transient_failure_retries_without_marking_final_failure(task_context, transient_pipeline) -> None:
    with pytest.raises(Retry):
        run_analysis_job.apply(args=[str(task_context.job_id)], throw=True)
    assert reload_job(task_context.job_id).status == JobStatus.RUNNING


def test_changed_jobs_cursor_is_monotonic(auth_client, changed_jobs) -> None:
    first = auth_client.get("/api/v1/jobs").json()
    second = auth_client.get("/api/v1/jobs", params={"changed_after": first["cursor"]}).json()
    assert {item["id"] for item in second["items"]} == {changed_jobs[-1].id}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/workers/test_analysis_tasks.py tests/integration/test_job_polling_api.py -q`

Expected: FAIL because worker and polling cursor are missing.

- [ ] **Step 3: Implement persisted state transitions and bounded retry**

The task loads the Job from PostgreSQL, marks it running once, dispatches by target type, and uses exponential backoff with jitter for transient errors. After the configured maximum, persist `failed`, a safe error code/message, and `retryable=true`; permanent errors fail immediately with `retryable=false`. Polling uses `(updated_at, id)` as an opaque cursor and returns affected Profile IDs.

- [ ] **Step 4: Run worker and polling tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/workers/test_analysis_tasks.py tests/integration/test_job_polling_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers backend/app/api/routes/jobs.py backend/tests
git commit -m "feat: execute and poll analysis jobs"
```

---

### Task 12: Mandatory scheduled Re-analyze and stale Creator behavior

**Files:**
- Create: `backend/app/workers/schedules.py`
- Modify: `backend/app/workers/celery_app.py`
- Modify: `backend/app/repositories/profiles.py`
- Create: `backend/tests/unit/workers/test_schedules.py`
- Create: `backend/tests/integration/test_stale_creators.py`

**Interfaces:**
- Produces: Celery Beat task `enqueue_due_reanalysis() -> int` every 15 minutes.
- Produces: `mark_stale_creators(now: datetime) -> int`.

- [ ] **Step 1: Write failing interval and stale tests**

```python
def test_due_scheduler_staggers_and_deduplicates(session, due_profiles) -> None:
    assert enqueue_due_reanalysis(batch_size=20) == 20
    assert count_active_jobs_for_same_target(session) == 20


def test_creator_over_thirty_days_is_stale_and_hidden(auth_client, old_creator) -> None:
    body = auth_client.get(f"/api/v1/profiles/creators/{old_creator.id}").json()
    assert body["source_status"] == "stale"
    assert body["youtube_metrics"] is None
    assert body["contact"]["source"] == "manual"
```

- [ ] **Step 2: Run schedule tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/workers/test_schedules.py tests/integration/test_stale_creators.py -q`

Expected: FAIL because scheduling and stale projection do not exist.

- [ ] **Step 3: Implement mandatory scheduling**

Beat runs every 15 minutes. Query due Profiles ordered by `next_analysis_at`, enqueue at most the batch size, and use the same active-Job uniqueness rule as manual Analyze. Recalculate `next_analysis_at` only after success. A Creator whose latest successful analysis is older than 30 days becomes stale; no setting or endpoint can disable either schedule.

- [ ] **Step 4: Run schedule and stale tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/workers/test_schedules.py tests/integration/test_stale_creators.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers backend/app/repositories/profiles.py backend/tests
git commit -m "feat: schedule mandatory profile refresh"
```

---

### Task 13: Resumable initial Creator CSV seeding

**Files:**
- Create: `backend/app/cli/__init__.py`
- Create: `backend/app/cli/seed_creators.py`
- Create: `backend/tests/unit/cli/test_seed_creators.py`
- Create: `backend/tests/fixtures/creators.csv`

**Interfaces:**
- Produces: `python -m app.cli.seed_creators <csv-path> --report <json-path>`.
- Consumes: canonical target resolution and normal Analysis Job creation.

- [ ] **Step 1: Write failing CSV import tests**

```python
def test_seed_import_preserves_manual_fields_and_skips_duplicate(seed_runner, tmp_path) -> None:
    result = seed_runner(
        "youtube_url,contact_email,notes\n"
        "https://youtube.com/@alpha,alpha@example.com,Warm\n"
        "https://youtube.com/@alpha,ignored@example.com,Duplicate\n"
    )
    assert result.counts == {"queued": 1, "duplicate": 1, "failed": 0}
    assert result.rows[0].contact_email == "alpha@example.com"
```

- [ ] **Step 2: Run the CLI test and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/cli/test_seed_creators.py -q`

Expected: FAIL because the CLI is missing.

- [ ] **Step 3: Implement resumable import and report writing**

Require `youtube_url`; accept optional `contact_email` and `notes`; validate email syntax. Resolve each Channel ID, skip an existing Profile or active Job, persist manual values before enqueueing the normal Creator Analysis Job, and write an atomic JSON report with `queued`, `duplicate`, and `failed` rows. When an existing report is supplied, retry only incomplete/failed rows.

- [ ] **Step 4: Run CLI tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/cli/test_seed_creators.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/cli backend/tests/unit/cli backend/tests/fixtures/creators.csv
git commit -m "feat: seed creator library from csv"
```

---

### Task 14: OpenAPI export and backend vertical-slice verification

**Files:**
- Create: `backend/scripts/export_openapi.py`
- Create: `backend/tests/integration/test_openapi_contract.py`
- Create: `backend/tests/integration/test_analyze_vertical_slice.py`
- Create: `backend/openapi.json`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `python backend/scripts/export_openapi.py` with deterministic JSON ordering.
- Produces: stable operation IDs consumed by the macOS plan.

- [ ] **Step 1: Write failing contract and vertical-slice tests**

```python
def test_openapi_has_stable_core_operations(app) -> None:
    operation_ids = {
        operation["operationId"]
        for path in app.openapi()["paths"].values()
        for operation in path.values()
    }
    assert {"validateSession", "listCreatorProfiles", "createAnalysisJob", "listJobs"} <= operation_ids


def test_creator_analyze_job_reaches_library(auth_client, eager_worker, fake_gateways) -> None:
    created = auth_client.post(
        "/api/v1/jobs/analysis",
        headers={"Idempotency-Key": "creator-e2e"},
        json={"target_type": "creator", "url": "https://youtube.com/@alpha"},
    ).json()
    eager_worker.run(created["job"]["id"])
    assert auth_client.get("/api/v1/profiles/creators", params={"query": "Alpha"}).json()["items"]
```

- [ ] **Step 2: Run contract tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_openapi_contract.py tests/integration/test_analyze_vertical_slice.py -q`

Expected: FAIL until operation IDs and export are stable.

- [ ] **Step 3: Set explicit operation IDs and export the schema**

Every route receives a camelCase `operation_id`. Export from `create_app().openapi()` with sorted keys and a trailing newline. Add a test that rejects hidden service-secret fields from the schema. Generate `backend/openapi.json` only after the test database slice passes.

- [ ] **Step 4: Run the complete backend slice and export check**

Run: `docker compose -f backend/compose.test.yaml run --rm test sh -c 'alembic upgrade head && pytest -q && python scripts/export_openapi.py && git diff --exit-code openapi.json'`

Expected: all tests pass and the committed schema is unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "test: verify analyze library vertical slice"
```
