# YouTube first binding and content-language projection

> **For agentic workers:** Use superpowers:executing-plans inline with TDD and one
> bounded integrated independent review, after Steam import's safe local commit.

**Goal:** A URL-only YouTube Library Creator can bind its resolved channel then
Analyze to the same UUID, while actual provider content languages reach Library.

**Architecture:** Add a source-binding-only bridge around the existing channel
resolver and explicit identity repository; Analyze remains the existing job pipeline.
Project source language metadata from current-identity content, with manual overrides
winning. Never promote model audience guesses or title-language hints into audio facts.

**Tech Stack:** Existing FastAPI/Pydantic/SQLAlchemy, YouTubeGateway, CreatorMapReduce
pipeline/service and current v2 Library models. No new provider/service/migration.

**Spec:** `docs/analyze-v2-implementation-handoff.md` §2–§6 (YouTube and languages).
YouTube official videos resource: https://developers.google.com/youtube/v3/docs/videos
distinguishes snippet.defaultAudioLanguage (default audio track) from defaultLanguage
(title/description text). X complete Analyze is the next distinct unit.

## Global constraints

- Stable internal Demo; no live provider/model/SMTP, deployment or credential changes.
- Preserve selected UUID and manual values, never silently create another Creator.
- First binding uses existing explicit identity semantics; old-identity source/evidence
  is not silently transferred. Existing manual records remain stored with provenance.
- Bridge is YouTube-only; it cannot secretly rebind an already-bound different account.
- Respect YouTube collection pause before handle-resolution I/O; no shared DB write
  lock over provider I/O, recheck current revision/identity before final publication.
- Content language unknown stays unknown. Manual languages (including explicit empty)
  override automatic source. Ignore previous-identity works and model audience fields.
- Keep provider-reported labels in provenance; use comparison keys for UI filters.

## Task 1: explicit first-source binding bridge

Create `backend/app/api/routes/youtube_binding.py`,
`backend/app/schemas/youtube_binding.py`,
`backend/tests/integration/test_youtube_binding.py`; register effective existing
channel resolver through main and reuse CreatorLibraryRepository.rebind.

```text
POST /api/v2/library/creators/{creator_id}/youtube-binding
Idempotency-Key + {url, expected_revision} -> CreatorDetail (200)
```

- [x] Red: HTTP manual YouTube URL-only seed → real YouTubeGateway resolver fixture
  maps handle to UC ID → same UUID with canonical source identity; no AnalysisJob yet.
  Successful replay no second resolve; stale revision/duplicate channel/other platform
  reject before publish, collection-disabled rejects before handle network.
- [x] Green: canonicalize only supported YouTube URLs, resolve outside transaction,
  safe notfound/unavailable errors, locked replay/revision/identity recheck, explicit
  first bind through existing identity repository. Already same bound UC id may replay;
  a different existing bound channel requires existing explicit rebind UI, not this path.
- [x] Red/green: source failure does not change UUID/manual fields; concurrent manual
  edit during resolve causes409; existing queued/sending/analysis identity guards hold.

```python
assert bound['id'] == original['id']
assert bound['source_identity']['account_id'] == 'UCresolved123'
assert analysis_job_count == 0
```

## Task 2: current-source language publication/projection

Modify `backend/app/analysis/contracts.py`, `backend/app/integrations/youtube.py`,
`backend/app/analysis/service.py`, `backend/app/repositories/creator_library.py`;
create a small content-language helper if shared. Add focused gateway/publication/
Library tests using existing MapReduce/service and discovery fixture modules.

- [x] Red: video defaultAudioLanguage en → actual Creator language/filter en; video
  defaultLanguage alone and AI audience primary_language alone leave unknown. Retain
  source labels/evidence; raw provider data not rewritten. X discovered source works
  with language en yield Library source language even without full Analyze.
- [x] Green: map declared audio language to VideoSource and publication current_facts
  languages plus source provenance. For metadata-only discovery without a published
  languages field, derive from current-identity same-platform source works. Published
  explicit empty source languages remain authoritative; no stale historical fallback.
  Reuse manual-overlay behavior and current language comparison presets. Cover ordinary
  provider regional English values without treating und/zxx as known spoken languages
  or guessing Chinese script from ambiguous zh.
- [x] Red/green: manual English/Japanese override wins including explicitempty; old
  identity works never leak language after rebind; no language data stays empty.

## Task 3: real Analyze continuity and bounded acceptance

- [x] Add HTTP binding→reanalyze job→production CreatorMapReducePipeline fixture→v2
  detail/filter sameUUID regression. Metadata-only discovery YouTube uses reanalyze,
  preserving the original Creator and manual overlays. Do not count legacy-only
  CreatorAnalysisPipeline as production MapReduce acceptance.
- [x] Format/export OpenAPI/add operation; focused binding/source-language/current
  Analyze fixtures, then full realRedis suite serially in fmg-v2-tests.
- [x] One integrated read-only review; fix verified ordinary blockers, keep defensive
  minor follow-ups separate, no broad re-review. Record exact evidence in
  `docs/backend-v2-youtube-binding-languages.md`, commit only this unit, notify root and
  frontend and continue X complete Analyze without waiting on external credentials.

```python
assert str(pipeline.run(job_id)) == original_creator_id
assert detail['languages'] == ['en']
assert library_english_filter['items'][0]['id'] == original_creator_id
```

Self-check: first-identity bridge, actual runtime pipeline, language source truth,
manual priority, no duplicate UUID, and ordinary failure/guard continuity covered.
