# Outreach A: locked template versions and four-slot drafts

> **For agentic workers:** Use executing-plans inline, TDD and one bounded
> independent integrated review. This follows saved sets and the language fix.

**Goal:** Deliver P6 typed HTTP→queued per-recipient generation→model HTTP fixture→
durable read/edit/repair, preserving N recipients and factual-source boundaries.

**Architecture:** New immutable `OutreachTemplateVersion` and immutable composition
membership (`OutreachComposition` / one `OutreachDraft` per RecipientSnapshot).
Draft current inputs/output have explicit revision, context fingerprint and lease;
refresh is an explicit new revision, not an overwrite of the original recipient
snapshot or discovery context. Dedicated four-slot renderer/gateway, shared model
credentials and queue. No Delivery, SMTP, qualification or sending endpoint in A.

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy/PostgreSQL, Celery, existing DeepSeekGateway.

**Spec:** Original PRD751 P6 `doxcnAeqz3rolPlWxymtyTTmoKh` and source template
`Ieqid5pULoUSqMxOtKTc156xnLe` revision69, both directly fetched2026-09-08;
`docs/outreach-v2-implementation-handoff.md` fully read. Root's explicit correction:
canonical registration may bind a manually created Game with no Steam ID; if a
Steam ID is present it must be4952700. Explicit registration only, never name
guessing or rewriting Game acquisition identity.

## Global constraints

- Internal stable Demo; TDD + one integrated review, only ordinary E2E/data loss/
  duplicate work/profile overwrite/concrete safety/current migration block.
- Canonical source rawSHA256 `6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd`;
  fixedSHA256 `0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93`.
- Preserve subject,20 body paragraphs, bold, exactSteamURL and Toki signature.
- Only `firstName`, `channelName`, `reference`, `observation`; fourth includes final
  period. No model-supplied source URL; no inferred real name or watching claims.
- No Yes/No/tracking added to new renderer; old templates/response endpoints untouched.
- Missing email/evidence retains members; success is not send-ready. No mandatory
  AI fit/evaluation/current-game-play gate added to factual email evidence.
- No actual provider/model/SMTP calls during verification; use strict HTTP fixtures.

## Task1: template resource, immutable registration and rendering

Create:
`backend/app/outreach/resources/liminal-revision-69.json` (exact reviewed XML content
inside a JSON resource, so file newline formatting cannot change its content hash);
`backend/app/outreach/locked_templates.py`; `backend/app/schemas/outreach_drafts.py`;
`backend/app/db/models/outreach_drafts.py`;
`backend/migrations/versions/20260908_0016_outreach_drafts.py`;
`backend/app/repositories/outreach_templates_v2.py`;
`backend/app/api/routes/outreach_drafts.py` (template routes first).
Register model/router with existing modules. New tests
`backend/tests/unit/outreach/test_locked_template_v2.py` and
`backend/tests/integration/test_outreach_template_versions.py`.

Contracts:

```text
GET /api/v2/outreach/template-versions?game_id=UUID
  -> registered immutable versions + builtin canonical descriptor (no write)
POST /api/v2/outreach/template-versions/canonical
  Idempotency-Key + {game_id}; explicit binding, return existing registration if any
POST /api/v2/outreach/template-versions
  Idempotency-Key + {request_id,game_id,name,subject,fixed_fragments:[str,str,str,str,str]}
GET /api/v2/outreach/template-versions/{version_id}
  -> subject,5fragments,fixed_hash,game_id,source metadata,original placeholders
```

- [ ] Red deterministic source test: derive exact subject/body/fixedhash,20paragraphs,
  4scopes with terminal period; wrong slot count/empty/unsupported newline/markup/
  missing observation period rejected. Literalhash expected, not computed by same
  helper. Renderer escapes slot text, verifies fixedhash, returns HTML/text withoutCTA.
- [ ] Green compile canonical by stripping only IDs/title/Subject paragraph and
  replacing the four exact marked spans; preserve byte-level fragments. Promote
  resource through apply_patch, verify bytes against reviewed localXML before use.
- [ ] Red/green explicit registration: noSteammanualGame allowed, different nonempty
  SteamID rejected, noGameidentity write; anotherGame cannot use an existing bound
  template. Explicit customversion survives independently of original. Custom HTML
  must allow only safe formatting/link tags and schemes, no script/event attributes;
  validate without silently rewriting fixed content.

## Task2: frozen composition, repairable drafts and sender facts

Create `backend/app/repositories/outreach_drafts.py`,
`backend/app/outreach/draft_inputs.py`; extend schema/routes. Tests
`backend/tests/integration/test_outreach_drafts.py`.

```text
POST /api/v2/activities/{activity_id}/compositions
  {request_id,recipient_batch_id,template_version_id} + Idempotency-Key
GET /api/v2/activities/{activity_id}/compositions
GET /api/v2/outreach/compositions/{composition_id}
  -> all N ordered drafts, individual statuses/context/versions/sources/send_ready:false
PATCH /api/v2/outreach/drafts/{draft_id}
  {expected_revision,context_token,values:{firstName,channelName,reference,observation}}
POST /api/v2/outreach/drafts/{draft_id}/refresh
  {expected_revision,context_token} -> new current input revision; queue if sufficient
POST /api/v2/outreach/drafts/{draft_id}/retry
  {expected_revision,context_token} -> explicit failed-member retry, same frozen input
POST /api/v2/outreach/compositions/{composition_id}/sender-facts
  {members:[{draft_id,expected_revision,context_token}],following,enjoyed,liked}
```

- [ ] Red three-memberfixture: complete/missingemail/missingobservation remain3 in
  original order and original RecipientSnapshots remain byte-equal. No fake Match,
  Delivery or sendtask. Composition requestID durable replay/conflict.
- [ ] Green freeze current Game/version and source references separately from
  Activity's historical discovery snapshot. Use current selected works only; bind
  the first selected recorded work deterministically (explicit selection order).
  Server binds publicname/source, actualchannel/source, referencedworkURL/ID and
  excerpt/notes/timestamp; model never adds URLs or source identifiers.
- [ ] Green input/context fingerprint includes current identity, name confirmation,
  selected contact/work data, liveGame/reference data, template hash, SMTP public
  sender identity (not password). Do not use old `missing_fields==[]` as gate:
  evaluation/relation warnings do not block generation. Missing email can generate;
  missing confirmedname/channel/reference/observation source remains repairable.
- [ ] Red/green manual edits only four values, preserve fixed fragments; validate
  name/channel/reference against bound current records, observation concrete nonblank
  with terminal period. Existing Library/selection APIs repair source information;
  explicit refresh adopts it and clears stale generation/fact confirmations.
- [ ] Red/green senderfacts only explicit chosen members/version/context, never
  implied by generation/publicnameconfirmation/preview. Bind to values+source+sender
  identity fingerprint and time; editing relevant values/source/sender invalidates.
  Missing SMTP does not prevent drafting but does not establish sendability.

## Task3: queued per-member generation and durable recovery

Create `backend/app/outreach/draft_ai.py`,
`backend/app/workers/outreach_draft_tasks.py`; extend Celery includes and injectable
dispatcher in create_app. Tests `backend/tests/unit/outreach/test_draft_ai.py` and
`backend/tests/integration/test_outreach_draft_runtime.py`.

- [ ] Red strict DeepSeek HTTP fixture: returns exactly four nonempty fields;
  malformed/extra fields, timeout, invented firstName/channel/reference fail locally.
  Observations draw solely from supplied recorded excerpt/notes; no titles-only
  inference. Prompt strings/data in English; source data treated as untrusted.
- [ ] Green existing DeepSeekGateway with bounded output (2048tokens) and model
  `deepseek-v4-flash`; credential lookup same encrypted sharedsettings path. No
  contact address/secret included in AI request; sanitized public source payload.
- [ ] Green one queued task per ready draft, worker concurrency through existing
  Celery pool. Claim with row lock/lease/revision; commit before I/O, publish only
  matching lease/revision. Repeated dispatch skips completed/running work. Expired
  work becomes explicit failed/unknown, no surprise duplicate paid calls.
- [ ] Red HTTP→dispatcher→production worker path→modelHTTPfixture→DB→GET successful
  four slots and sources. One failure preserves other successes, retry only that
  member; source changed during generation never becomes fresh/confirmed.
- [ ] Red create committed but broker fails: same key/request retry dispatches same
  composition/draft IDs; no new members or duplicate successful calls.

## Task4: bounded acceptance

- [ ] Current0015→0016 migration preserves existing rows and safe populated downgrade;
  adapt declared OpenAPI operation allowlist and linearhead test to new contract.
- [ ] Focused typed/runtime/migration tests, generatedOpenAPI, formatting, full
  realRedis suite; one independent integrated review, fix only verified blockers.
- [ ] `docs/backend-v2-outreach-drafts.md` typed contract/limits/proof, explicit local
  commit, root/frontend handoff. Then B qualification/preview/final-send; no deploy.

Self-review: A covers P6 templates/fourfields/sources/edit/retry/Npreservation. P7
eligibility/sending and P9followup intentionally remain B/C, not implied complete.

## Execution checkpoint

Tasks1–3 implemented with red/green tests. Task4 migration and contract export done;
first full realRedis run2230passed/3deferred skips,221.62s. One integrated independent
review found one ordinary-work-title blocker (square brackets misclassified as
placeholders); schema-only red reproduction and30 green unit tests verify the minimal
fix. A further real HTTP bound-title regression is included in final full execution.
No second broad review. Final full-run result/commit are recorded in delivery docs.
Review minor prompt prefix was corrected to canonical `I liked how you `.
Three skipped tests remain the approved old-writer/rolling-migration cases, not new
functional omissions. No live provider/model/SMTP calls or deployment occurred.

Final acceptance:2236passed/3approvedskips/0failed,208.52s on final code including
the bracketed-title HTTP regression.52newtests. One integrated review blocker fixed
with red/green proof; no second broad review. All A implementation/verification
steps complete; local commit/handoff follows, B remains its own planned unit.
