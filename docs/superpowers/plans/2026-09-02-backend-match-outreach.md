# Backend Match and Outreach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add progressive three-stage Creator matching, complete-result publication, email template management, SMTP sending, campaigns, and final Accepted/Declined response tracking to the working backend.

**Architecture:** Match orchestration persists every input and checkpoint in PostgreSQL, launches independent Celery pairwise tasks, and publishes client-visible result rows only in the final ranking transaction. Outreach renders immutable per-Delivery email snapshots, validates a whole Send Batch before inserting it, sends through an injected SMTP gateway, and treats public response tokens as one-time capability links whose GET is read-only and POST is final.

**Tech Stack:** Existing FastAPI/SQLAlchemy/Celery backend, PostgreSQL advisory locks, Pydantic structured outputs, Markdown-It, Bleach, Python `smtplib`, Jinja2 response pages, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-find-me-gamer-design.md`

## Global Constraints

- Match uses only current, non-stale Creator Profiles already in Library; it never discovers Creators.
- Screening uses `deepseek-v4-flash`, selects 0–30 Creators, and receives shuffled Creator Briefs with a stable per-task seed.
- Pairwise and final ranking use `deepseek-v4-pro`; at most five pairwise calls execute concurrently.
- Deep Match input is locked Game Brief plus the selected Creator's full Profile snapshot.
- A Match publishes either a complete result or no result; successful pairwise outputs are durable checkpoints.
- The API never serializes ordinal rank, numeric total score, or numeric dimension score.
- Contact availability, favorite state, and prior Outreach never affect Match scoring.
- SMTP acceptance is `sent`, never `delivered`.
- Version 1 does not implement open tracking, verified delivery tracking, bounce ingestion, or inbound mailbox parsing.
- Template Markdown cannot contain arbitrary HTML; the backend owns the CTA block and response endpoints.
- GET response links never mutate state; POST makes the first confirmed Campaign/Creator response final.
- Duplicate sending requires explicit Resend; confirmed responses cannot be resent.
- Every task follows TDD and ends with a focused commit.

## File Map

- `backend/migrations/versions/20260902_0002_match_outreach.py` — Match, Campaign, Template, Send Batch, and Delivery schema.
- `backend/app/db/models/match.py` — Match task, input snapshot, checkpoint, and published result persistence.
- `backend/app/db/models/outreach.py` — Template, Campaign, Send Batch, Delivery, and response persistence.
- `backend/app/schemas/match.py` — public Match contracts with hidden fields excluded by construction.
- `backend/app/schemas/ai_match.py` — strict screening, pairwise, and ranking model outputs.
- `backend/app/matching/` — prompt builders, orchestration, scoring publication, and retention cleanup.
- `backend/app/schemas/outreach.py` — Template, composer, batch, Delivery, and campaign contracts.
- `backend/app/outreach/` — rendering, validation, SMTP, rate limiting, sending, and response logic.
- `backend/app/api/routes/match.py` — Match create/history/detail/retry endpoints.
- `backend/app/api/routes/outreach.py` — Campaign, Template, SMTP, and Send Batch endpoints.
- `backend/app/api/routes/responses.py` — unauthenticated GET confirmation and POST confirmation.
- `backend/app/templates/response_confirmation.html` — branded, English-only confirmation page.
- `backend/tests/` — unit and integration coverage for every state boundary.

---

### Task 1: Match and Outreach database migration

**Files:**
- Create: `backend/app/db/models/match.py`
- Create: `backend/app/db/models/outreach.py`
- Modify: `backend/app/db/base.py`
- Create: `backend/migrations/versions/20260902_0002_match_outreach.py`
- Create: `backend/tests/integration/test_match_outreach_migration.py`

**Interfaces:**
- Produces: `match_tasks`, `match_screening_records`, `match_candidate_inputs`, `match_pairwise_records`, and `match_result_items`.
- Produces: `outreach_campaigns`, `templates`, `send_batches`, `deliveries`, and `campaign_creator_responses`.

- [ ] **Step 1: Write the failing schema test**

```python
def test_match_and_outreach_tables_exist(database_inspector) -> None:
    names = set(database_inspector.get_table_names())
    assert {
        "match_tasks", "match_screening_records", "match_candidate_inputs",
        "match_pairwise_records", "match_result_items", "outreach_campaigns",
        "templates", "send_batches", "deliveries", "campaign_creator_responses",
    } <= names
```

- [ ] **Step 2: Run the migration test and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_match_outreach_migration.py -q`

Expected: FAIL with missing tables.

- [ ] **Step 3: Implement constraints that enforce publication and response invariants**

Use UUID keys and timezone-aware timestamps. Make `(match_task_id, creator_id)` unique in every candidate/checkpoint/result table. Store locked input JSON only in screening/candidate tables with `expires_at`. Published result rows include hidden `backend_order`, `total_score`, and `dimension_scores` but are inserted only after ranking. Make `(match_task_id)` unique on Campaign and `(campaign_id, creator_id)` unique on `campaign_creator_responses`. Store only the SHA-256 response token digest.

- [ ] **Step 4: Upgrade and run the schema test**

Run: `docker compose -f backend/compose.test.yaml run --rm test sh -c 'alembic upgrade head && pytest tests/integration/test_match_outreach_migration.py -q'`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db backend/migrations backend/tests/integration/test_match_outreach_migration.py
git commit -m "feat: add match and outreach schema"
```

---

### Task 2: Strict Match AI schemas and English prompt builders

**Files:**
- Create: `backend/app/schemas/ai_match.py`
- Create: `backend/app/matching/prompts.py`
- Create: `backend/tests/unit/matching/test_match_schemas.py`
- Create: `backend/tests/unit/matching/test_match_prompts.py`

**Interfaces:**
- Produces: `ScreeningOutput`, `PairwiseMatchBrief`, `RankingItem`, and `FinalRankingOutput`.
- Produces: `build_screening_prompt`, `build_pairwise_prompt`, and `build_ranking_prompt`.

- [ ] **Step 1: Write failing validation and neutrality tests**

```python
def test_screening_rejects_more_than_thirty() -> None:
    with pytest.raises(ValidationError):
        ScreeningOutput(selected=[candidate(i) for i in range(31)])


def test_pairwise_prompt_excludes_outreach_and_favorite_data() -> None:
    text = render_messages(build_pairwise_prompt(game_brief(), creator_profile()))
    assert "contact_email" not in text
    assert "favorite" not in text
    assert "prior_outreach" not in text
```

- [ ] **Step 2: Run tests and verify missing schemas**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_match_schemas.py tests/unit/matching/test_match_prompts.py -q`

Expected: FAIL because Match AI contracts do not exist.

- [ ] **Step 3: Implement complete structured contracts**

`PairwiseMatchBrief` contains Content Fit, Audience Fit, Performance Fit, Promotion Fit, Brand Safety, Strengths, Risks, Evidence, and Match Reasons. `FinalRankingOutput` requires every input Creator exactly once, hidden scores constrained to 0–1, a unique non-negative backend order, group `recommended|other`, and label `Strong Match|Good Match|Limited Match`. Prompts say `Return English only`, prohibit numeric claims without supplied evidence, and pass stable opaque Creator IDs.

- [ ] **Step 4: Run Match schema and prompt tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_match_schemas.py tests/unit/matching/test_match_prompts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/ai_match.py backend/app/matching/prompts.py backend/tests/unit/matching
git commit -m "feat: define progressive match contracts"
```

---

### Task 3: Candidate screening and immutable task inputs

**Files:**
- Create: `backend/app/matching/screening.py`
- Create: `backend/app/repositories/match.py`
- Create: `backend/tests/unit/matching/test_screening.py`
- Create: `backend/tests/integration/test_match_input_lock.py`

**Interfaces:**
- Produces: `ScreeningService.run(match_task_id: UUID) -> list[UUID]`.
- Produces: `MatchRepository.create_locked_task(game_id: UUID, seed: int, threshold: Decimal) -> MatchTask`.

- [ ] **Step 1: Write failing eligibility, stable-shuffle, and empty-result tests**

```python
def test_screening_uses_every_eligible_creator_once(screening_service, eligible, stale) -> None:
    screening_service.run(match_task_id)
    sent_ids = screening_service.fake_ai.last_creator_ids
    assert set(sent_ids) == {creator.id for creator in eligible}
    assert stale.id not in sent_ids


def test_same_task_seed_produces_same_order() -> None:
    assert shuffled_ids(creators, seed=42) == shuffled_ids(creators, seed=42)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_screening.py tests/integration/test_match_input_lock.py -q`

Expected: FAIL because screening orchestration is absent.

- [ ] **Step 3: Implement snapshot-first screening**

At Match creation, copy the current Game Brief and every eligible Creator Brief into task-owned records before the AI call. Shuffle by a generated seed stored on the Match Task. Validate returned IDs are a subset, unique, and at most 30. For selected Creators, persist the complete current Profile input with `expires_at = created_at + 30 days`. Zero selected Creators atomically marks the task succeeded with result count zero and skips later stages.

- [ ] **Step 4: Run screening tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_screening.py tests/integration/test_match_input_lock.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/matching/screening.py backend/app/repositories/match.py backend/tests
git commit -m "feat: screen locked creator candidates"
```

---

### Task 4: Pairwise Match checkpoints and concurrency-safe advancement

**Files:**
- Create: `backend/app/matching/pairwise.py`
- Create: `backend/app/workers/match_tasks.py`
- Create: `backend/tests/unit/matching/test_pairwise.py`
- Create: `backend/tests/integration/test_match_checkpoint.py`

**Interfaces:**
- Produces: `PairwiseService.run(match_task_id: UUID, creator_id: UUID) -> PairwiseMatchBrief`.
- Produces: Celery tasks `start_match_task`, `run_pairwise_match`, and `advance_match_task`.

- [ ] **Step 1: Write failing checkpoint and duplicate-execution tests**

```python
def test_successful_pair_is_not_called_twice(pairwise_service, completed_checkpoint) -> None:
    result = pairwise_service.run(completed_checkpoint.match_task_id, completed_checkpoint.creator_id)
    assert result == completed_checkpoint.brief
    assert pairwise_service.fake_ai.calls == 0


def test_advance_enqueues_ranking_once(session, completed_pairs, celery_spy) -> None:
    advance_match_task(str(completed_pairs.match_task_id))
    advance_match_task(str(completed_pairs.match_task_id))
    assert celery_spy.count("finalize_match_ranking") == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_pairwise.py tests/integration/test_match_checkpoint.py -q`

Expected: FAIL because pairwise workers are absent.

- [ ] **Step 3: Implement durable checkpoints and PostgreSQL advisory locking**

Each selected Creator gets one pairwise task. Persist `running`, `succeeded`, or `failed` checkpoint state and the validated Match Brief. Retry transient integration errors with exponential backoff. `advance_match_task` acquires a transaction-scoped advisory lock derived from Match Task UUID; it enqueues final ranking only when every selected checkpoint succeeded and `ranking_enqueued_at` is null. Configure the single worker service with concurrency 5 so no more than five pairwise calls run at once.

- [ ] **Step 4: Run checkpoint tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_pairwise.py tests/integration/test_match_checkpoint.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/matching/pairwise.py backend/app/workers/match_tasks.py backend/tests
git commit -m "feat: checkpoint pairwise match work"
```

---

### Task 5: Atomic final ranking and hidden-field projection

**Files:**
- Create: `backend/app/matching/ranking.py`
- Create: `backend/app/schemas/match.py`
- Create: `backend/tests/unit/matching/test_ranking.py`
- Create: `backend/tests/integration/test_match_publication.py`

**Interfaces:**
- Produces: `RankingService.run(match_task_id: UUID) -> int` result count.
- Produces: public `MatchResultItem` without numeric/rank fields.

- [ ] **Step 1: Write failing all-or-nothing and redaction tests**

```python
def test_ranking_failure_publishes_no_results(ranking_service, invalid_ranking) -> None:
    with pytest.raises(InvalidModelOutput):
        ranking_service.run(match_task_id)
    assert count_published_results(match_task_id) == 0


def test_public_match_item_has_no_numeric_score_or_rank(published_item) -> None:
    body = MatchResultItem.model_validate(published_item).model_dump()
    assert {"total_score", "dimension_scores", "backend_order", "rank"}.isdisjoint(body)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_ranking.py tests/integration/test_match_publication.py -q`

Expected: FAIL because ranking and public schemas are absent.

- [ ] **Step 3: Implement final validation and one-transaction publication**

Send all successful Match Briefs to Pro once. Require exactly the selected Creator IDs. Derive `recommended` using the Match Task's frozen threshold and verify the model group agrees; reject mismatches. In one transaction, insert all result rows, create the one-to-one empty Campaign, mark Match succeeded, and set completed time. Public serialization exposes group, qualitative label/dimensions, reasons, current Creator card/contact/outreach state, and sort order applied server-side, but never emits the hidden order itself.

- [ ] **Step 4: Run ranking and publication tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/matching/test_ranking.py tests/integration/test_match_publication.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/matching/ranking.py backend/app/schemas/match.py backend/tests
git commit -m "feat: publish complete match results"
```

---

### Task 6: Match create, history, detail, retry, and retention APIs

**Files:**
- Create: `backend/app/api/routes/match.py`
- Modify: `backend/app/api/routes/jobs.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/matching/retention.py`
- Modify: `backend/app/workers/schedules.py`
- Create: `backend/tests/integration/test_match_api.py`
- Create: `backend/tests/unit/matching/test_retention.py`

**Interfaces:**
- Produces: `POST /api/v1/matches`, `GET /api/v1/matches`, `GET /api/v1/matches/{id}`, and `POST /api/v1/matches/{id}/retry`.
- Produces: `purge_expired_match_inputs(now: datetime) -> int`.

- [ ] **Step 1: Write failing API and expired-retry tests**

```python
def test_match_creation_requires_idempotency_and_game(auth_client, game) -> None:
    response = auth_client.post(
        "/api/v1/matches",
        headers={"Idempotency-Key": "match-game"},
        json={"game_id": str(game.id)},
    )
    assert response.status_code == 202
    assert response.json()["stage"] == "screening"


def test_retry_after_snapshot_expiry_creates_superseding_task(auth_client, expired_failed_match) -> None:
    body = auth_client.post(
        f"/api/v1/matches/{expired_failed_match.id}/retry",
        headers={"Idempotency-Key": "retry-expired"},
    ).json()
    assert body["id"] != str(expired_failed_match.id)
    assert body["supersedes_id"] == str(expired_failed_match.id)


def test_changed_job_feed_includes_match_tasks(auth_client, running_match) -> None:
    body = auth_client.get("/api/v1/jobs").json()
    item = next(item for item in body["items"] if item["resource_id"] == str(running_match.id))
    assert item["kind"] == "match"
    assert item["status"] == "running"
```

- [ ] **Step 2: Run tests and verify 404 failures**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_match_api.py tests/unit/matching/test_retention.py -q`

Expected: FAIL because Match routes are missing.

- [ ] **Step 3: Implement routes, idempotency, and 30-day cleanup**

Creation rejects a missing Game Profile and starts a cloud task after transactional task creation. History is reverse chronological and includes stage/progress/result count/safe failure. Detail groups published results into ordered Recommended and Other arrays. Extend the changed-Job endpoint to return a discriminated union of Analysis and Match summaries ordered by `(updated_at, kind, id)`, so the existing opaque cursor and three-second client poll cover both workflows. Retry resumes missing checkpoints while snapshots exist; after expiry it creates a new task and marks the old task superseded. Beat deletes only screening/input snapshot JSON after 30 days, never published Match Briefs or result ordering.

- [ ] **Step 4: Run Match API tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_match_api.py tests/unit/matching/test_retention.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/match.py backend/app/api/routes/jobs.py backend/app/main.py backend/app/matching/retention.py backend/app/workers/schedules.py backend/tests
git commit -m "feat: expose match workflow api"
```

---

### Task 7: Template validation, Markdown rendering, and system CTA injection

**Files:**
- Create: `backend/app/schemas/outreach.py`
- Create: `backend/app/outreach/templates.py`
- Create: `backend/app/repositories/outreach.py`
- Create: `backend/tests/unit/outreach/test_templates.py`

**Interfaces:**
- Produces: `validate_template_variables(text: str) -> set[str]`.
- Produces: `render_delivery(template: TemplateData, context: TemplateContext, response_urls: ResponseURLs) -> RenderedDelivery`.
- Produces: default CTA labels `Yes, I'm in` and `No, I'm not interested`.

- [ ] **Step 1: Write failing variable, raw HTML, and CTA tests**

```python
def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(TemplateValidationError):
        validate_template_variables("Hello {{unknown_name}}")


def test_system_ctas_are_appended_after_sanitized_markdown() -> None:
    rendered = render_delivery(template(body="Hello <script>x()</script>"), context(), urls())
    assert "<script>" not in rendered.html
    assert "Yes, I'm in" in rendered.html
    assert "No, I'm not interested" in rendered.html
    assert rendered.html.index("Yes, I'm in") > rendered.html.index("Hello")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_templates.py -q`

Expected: FAIL because rendering is absent.

- [ ] **Step 3: Implement allowlisted variables and HTML sanitization**

Allow only the seven variables from the specification. Escape substituted values before Markdown rendering. Disable raw HTML in Markdown-It and sanitize the result with a small allowlist (`p`, `br`, `strong`, `em`, `ul`, `ol`, `li`, `a`, `blockquote`, `code`). Append backend-generated CTA HTML after sanitization; labels are escaped and endpoints cannot be supplied by Template authors. Return rendered subject, Markdown source, and final HTML.

- [ ] **Step 4: Run renderer tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_templates.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/outreach.py backend/app/outreach/templates.py backend/app/repositories/outreach.py backend/tests/unit/outreach
git commit -m "feat: render safe outreach templates"
```

---

### Task 8: Shared Template CRUD and preview API

**Files:**
- Create: `backend/app/api/routes/outreach.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_templates_api.py`

**Interfaces:**
- Produces: `GET/POST /api/v1/outreach/templates`.
- Produces: `GET/PATCH/DELETE /api/v1/outreach/templates/{id}`.
- Produces: `POST /api/v1/outreach/templates/{id}/duplicate`, `/default`, and `/preview`.

- [ ] **Step 1: Write failing CRUD and history-safety tests**

```python
def test_only_one_template_is_default(auth_client, two_templates) -> None:
    auth_client.post(f"/api/v1/outreach/templates/{two_templates[1].id}/default")
    items = auth_client.get("/api/v1/outreach/templates").json()["items"]
    assert sum(item["is_default"] for item in items) == 1


def test_preview_uses_sample_data_without_sending(auth_client, template_id) -> None:
    body = auth_client.post(f"/api/v1/outreach/templates/{template_id}/preview").json()
    assert "Sample Creator" in body["html"]
    assert count_deliveries() == 0
```

- [ ] **Step 2: Run Template API tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_templates_api.py -q`

Expected: FAIL with missing endpoints.

- [ ] **Step 3: Implement transactional CRUD**

Validate subject/body/labels on every write. Setting default clears the prior default in the same transaction. Reject deletion of the last Template or current default until another default is chosen. Duplication appends `Copy` and never becomes default automatically. Preview uses fixed non-secret sample data and the reserved non-routable URLs `https://example.invalid/r/preview-accepted` and `https://example.invalid/r/preview-declined`.

- [ ] **Step 4: Run Template API tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_templates_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/outreach.py backend/app/main.py backend/tests/integration/test_templates_api.py
git commit -m "feat: manage outreach templates"
```

---

### Task 9: SMTP gateway, connection tests, and shared rate limiter

**Files:**
- Create: `backend/app/outreach/smtp.py`
- Create: `backend/app/outreach/rate_limit.py`
- Modify: `backend/app/api/routes/outreach.py`
- Create: `backend/tests/unit/outreach/test_smtp.py`
- Create: `backend/tests/unit/outreach/test_rate_limit.py`
- Create: `backend/tests/integration/test_smtp_settings_api.py`

**Interfaces:**
- Produces: `SMTPGateway.probe(config: SMTPConfig) -> None`.
- Produces: `SMTPGateway.send(config: SMTPConfig, message: EmailMessage) -> SMTPReceipt`.
- Produces: `SMTPRateLimiter.acquire(workspace: str, per_minute: int) -> float` returning required delay seconds.
- Produces: SMTP status/update/test/test-email endpoints under `/api/v1/outreach/smtp`.

- [ ] **Step 1: Write failing TLS, redaction, and limiter tests**

```python
def test_starttls_is_established_before_login(fake_smtp) -> None:
    SMTPGateway(factory=fake_smtp.factory).probe(smtp_config(encryption="starttls"))
    assert fake_smtp.events[:2] == ["starttls", "login"]


def test_smtp_status_never_contains_password(auth_client) -> None:
    auth_client.put("/api/v1/outreach/smtp", json=smtp_payload(password="secret"))
    assert "secret" not in str(auth_client.get("/api/v1/outreach/smtp").json())
```

- [ ] **Step 2: Run SMTP tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_smtp.py tests/unit/outreach/test_rate_limit.py tests/integration/test_smtp_settings_api.py -q`

Expected: FAIL because SMTP services are absent.

- [ ] **Step 3: Implement NetEase-compatible SMTP and Redis token bucket**

Support `tls`, `starttls`, and `none`, with `tls` default for port 465. Require authentication, From Name, Reply-To, and a 1–60 rate. Treat recipient refusal/authentication failure as permanent and connection/timeouts as transient. The Redis Lua token bucket may coordinate rate only; Delivery state remains in PostgreSQL. Test Send targets a caller-supplied company mailbox and persists only the last test status/time, not a Delivery.

- [ ] **Step 4: Run SMTP tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_smtp.py tests/unit/outreach/test_rate_limit.py tests/integration/test_smtp_settings_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/outreach backend/app/api/routes/outreach.py backend/tests
git commit -m "feat: configure enterprise smtp"
```

---

### Task 10: Atomic Send Batch creation, preview overrides, and Resend rules

**Files:**
- Create: `backend/app/outreach/batches.py`
- Modify: `backend/app/api/routes/outreach.py`
- Create: `backend/tests/unit/outreach/test_batches.py`
- Create: `backend/tests/integration/test_send_batch_api.py`

**Interfaces:**
- Produces: `POST /api/v1/outreach/send-batches/preview`.
- Produces: `POST /api/v1/outreach/send-batches` with required `Idempotency-Key`.
- Produces: `POST /api/v1/outreach/deliveries/{id}/resend` with required `Idempotency-Key`.

- [ ] **Step 1: Write failing atomicity and duplicate tests**

```python
def test_invalid_recipient_rejects_entire_batch(auth_client, match_with_one_missing_email) -> None:
    response = create_batch(auth_client, match_with_one_missing_email.all_creator_ids)
    assert response.status_code == 422
    assert count_send_batches() == 0
    assert count_deliveries() == 0


def test_duplicate_send_requires_resend_endpoint(auth_client, sent_delivery) -> None:
    response = create_batch(auth_client, [sent_delivery.creator_id])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "explicit_resend_required"
```

- [ ] **Step 2: Run Send Batch tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_batches.py tests/integration/test_send_batch_api.py -q`

Expected: FAIL because batch orchestration is missing.

- [ ] **Step 3: Implement validate-then-insert behavior**

Validate the Match is succeeded, each Creator belongs to its result, an active email exists, SMTP is configured, the Template is valid, and no prohibited prior send/confirmed response exists. Render each Creator independently, apply only the caller's explicit send-only subject/body override, generate one random response token per Delivery, store only its hash, and insert the Send Batch plus all Deliveries in one transaction. Idempotent replay returns the original batch. Resend supersedes only failed/no-response Deliveries and invalidates their POST capability.

- [ ] **Step 4: Run Send Batch tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_batches.py tests/integration/test_send_batch_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/outreach/batches.py backend/app/api/routes/outreach.py backend/tests
git commit -m "feat: create atomic outreach batches"
```

---

### Task 11: Delivery worker and SMTP result semantics

**Files:**
- Create: `backend/app/workers/outreach_tasks.py`
- Modify: `backend/app/workers/celery_app.py`
- Create: `backend/tests/unit/workers/test_outreach_tasks.py`
- Create: `backend/tests/integration/test_delivery_states.py`

**Interfaces:**
- Produces: Celery task `send_delivery(delivery_id: str) -> None`.
- Produces: `enqueue_send_batch(send_batch_id: UUID) -> int`.

- [ ] **Step 1: Write failing Sent/Failed/retry tests**

```python
def test_smtp_acceptance_is_sent_not_delivered(outreach_task, accepted_smtp) -> None:
    outreach_task.run(str(delivery_id))
    saved = reload_delivery(delivery_id)
    assert saved.send_state == "sent"
    assert not hasattr(saved, "delivered_at")


def test_transient_smtp_error_retries(outreach_task, transient_smtp) -> None:
    with pytest.raises(Retry):
        outreach_task.apply(args=[str(delivery_id)], throw=True)
    assert reload_delivery(delivery_id).send_state == "sending"
```

- [ ] **Step 2: Run worker tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/workers/test_outreach_tasks.py tests/integration/test_delivery_states.py -q`

Expected: FAIL because delivery task is absent.

- [ ] **Step 3: Implement idempotent delivery sending**

Lock the Delivery row before transitioning queued→sending. A Delivery already sent or superseded is a no-op. Acquire the shared SMTP rate token, build `EmailMessage` from the immutable stored subject/HTML/Reply-To, and persist `sent_at` only after SMTP accepts the recipient. Retry transient failures with backoff; persist safe error metadata on final/permanent failure. Derive Send Batch aggregate state from its Deliveries.

- [ ] **Step 4: Run Delivery tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/workers/test_outreach_tasks.py tests/integration/test_delivery_states.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/outreach_tasks.py backend/app/workers/celery_app.py backend/tests
git commit -m "feat: send outreach deliveries"
```

---

### Task 12: Public read-only GET and final POST response flow

**Files:**
- Create: `backend/app/outreach/responses.py`
- Create: `backend/app/api/routes/responses.py`
- Create: `backend/app/templates/response_confirmation.html`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/outreach/test_response_tokens.py`
- Create: `backend/tests/integration/test_public_responses.py`

**Interfaces:**
- Produces: `new_response_token() -> tuple[str, str]` returning raw token and SHA-256 digest.
- Produces: `GET /r/{token}?choice=accepted|declined` without mutation.
- Produces: `POST /r/{token}` with form field `choice`.

- [ ] **Step 1: Write failing non-mutation and first-response-wins tests**

```python
def test_get_confirmation_does_not_mutate(public_client, delivery_token) -> None:
    response = public_client.get(f"/r/{delivery_token}?choice=accepted")
    assert response.status_code == 200
    assert reload_campaign_response(delivery_token) is None


def test_first_confirmed_response_is_final(public_client, accepted_token, alternate_token) -> None:
    public_client.post(f"/r/{accepted_token}", data={"choice": "accepted"})
    public_client.post(f"/r/{alternate_token}", data={"choice": "declined"})
    assert campaign_response(accepted_token).state == "accepted"
```

- [ ] **Step 2: Run response tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_response_tokens.py tests/integration/test_public_responses.py -q`

Expected: FAIL because public routes are missing.

- [ ] **Step 3: Implement capability lookup and atomic final response**

Generate 32 random bytes with `secrets.token_urlsafe`, hash the raw token with SHA-256, and compare digests in constant time. GET renders English system copy, the Delivery's stored CTA labels, the preselected choice, and a real form submit button. POST locks the Campaign/Creator response row, records the first accepted/declined state and timestamp, and returns the recorded state for every later request. Superseded tokens render read-only; they never POST a new choice. Rate-limit public endpoints by IP and token digest without logging the raw token.

- [ ] **Step 4: Run public response tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_response_tokens.py tests/integration/test_public_responses.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/outreach/responses.py backend/app/api/routes/responses.py backend/app/templates backend/app/main.py backend/tests
git commit -m "feat: confirm creator outreach responses"
```

---

### Task 13: Campaign metrics, Delivery history, and Outreach API

**Files:**
- Create: `backend/app/outreach/metrics.py`
- Modify: `backend/app/repositories/outreach.py`
- Modify: `backend/app/api/routes/outreach.py`
- Create: `backend/tests/unit/outreach/test_campaign_metrics.py`
- Create: `backend/tests/integration/test_campaign_api.py`

**Interfaces:**
- Produces: `calculate_campaign_metrics(rows: Iterable[DeliveryProjection]) -> CampaignMetrics`.
- Produces: `GET /api/v1/outreach/campaigns` and `GET /api/v1/outreach/campaigns/{id}`.
- Produces: `GET /api/v1/outreach/deliveries/{id}`.

- [ ] **Step 1: Write failing unique-Creator aggregation tests**

```python
def test_campaign_counts_unique_creators_across_resends() -> None:
    metrics = calculate_campaign_metrics([
        sent("creator-a", response="accepted"),
        sent("creator-a", response="accepted", resend=True),
        failed("creator-b"),
        sent("creator-c", response=None),
    ])
    assert metrics.sent_creators == 2
    assert metrics.accepted == 1
    assert metrics.no_response == 1
    assert metrics.failed == 1
    assert metrics.response_rate == Decimal("0.5")
```

- [ ] **Step 2: Run metrics and API tests and verify failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_campaign_metrics.py tests/integration/test_campaign_api.py -q`

Expected: FAIL because projections are missing.

- [ ] **Step 3: Implement unique-Creator SQL projection and history output**

Count only Creators with at least one successful current Delivery in the response-rate denominator. Accepted and Declined come from final Campaign/Creator responses. No Response is successfully sent minus responded. Failed includes Creators whose current Delivery failed and who have no successful Delivery. Detail returns Send Batches and Delivery snapshots, safe SMTP errors, and timestamps, never token hashes or SMTP secrets.

- [ ] **Step 4: Run Campaign tests**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/unit/outreach/test_campaign_metrics.py tests/integration/test_campaign_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/outreach/metrics.py backend/app/repositories/outreach.py backend/app/api/routes/outreach.py backend/tests
git commit -m "feat: report outreach campaign metrics"
```

---

### Task 14: Match-to-response vertical-slice verification and OpenAPI refresh

**Files:**
- Create: `backend/tests/integration/test_match_outreach_vertical_slice.py`
- Modify: `backend/tests/integration/test_openapi_contract.py`
- Modify: `backend/openapi.json`

**Interfaces:**
- Extends: stable OpenAPI operation IDs for Match, Outreach, and settings operations.
- Verifies: Game→Match→Send Batch→Sent→Accepted as one deterministic fake-backed flow.

- [ ] **Step 1: Write the failing end-to-end integration test**

```python
def test_match_to_accepted_response(auth_client, eager_worker, fake_ai, fake_smtp, seeded_library) -> None:
    match = create_match(auth_client, seeded_library.game_id, key="vertical-match")
    eager_worker.finish_match(match["id"])
    result = auth_client.get(f"/api/v1/matches/{match['id']}").json()
    assert result["recommended"]
    assert "total_score" not in str(result)

    batch = create_send_batch(auth_client, match["id"], result["recommended"][0]["creator"]["id"])
    eager_worker.send_batch(batch["id"])
    public_client().post(f"/r/{fake_smtp.last_response_token}", data={"choice": "accepted"})
    campaign = auth_client.get(f"/api/v1/outreach/campaigns/{batch['campaign_id']}").json()
    assert campaign["metrics"]["accepted"] == 1
```

- [ ] **Step 2: Run the vertical slice and verify initial failure**

Run: `docker compose -f backend/compose.test.yaml run --rm test pytest tests/integration/test_match_outreach_vertical_slice.py -q`

Expected: FAIL until all operation wiring is complete.

- [ ] **Step 3: Complete route registration and refresh deterministic OpenAPI**

Assign explicit camelCase operation IDs for every Match and Outreach route. Add a contract assertion that `MatchResultItem` contains no score/rank properties and `Delivery` contains no token digest. Export `backend/openapi.json` with the existing script.

- [ ] **Step 4: Run full backend tests and contract drift check**

Run: `docker compose -f backend/compose.test.yaml run --rm test sh -c 'alembic upgrade head && pytest -q && python scripts/export_openapi.py && git diff --exit-code openapi.json'`

Expected: all tests pass and the OpenAPI schema is stable.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "test: verify match outreach vertical slice"
```
