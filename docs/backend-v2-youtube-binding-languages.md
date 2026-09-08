# YouTube first binding and content languages

Scope: stable internal Demo. No new migration/service/key; no deployment or live
provider/model/mail calls in this acceptance. X full Analyze remains the next unit.

## Client contract

`POST /api/v2/library/creators/{creator_id}/youtube-binding`

Authenticated workspace request, `Idempotency-Key`, body:

```json
{"url":"https://www.youtube.com/@creator","expected_revision":1}
```

Returns the existing v2 `CreatorDetail` (200), preserving the selected UUID and
manual fields. URL-only YouTube entries must explicitly bind before submitting
`POST /api/v1/jobs/analysis` with their returned canonical URL and `mode: reanalyze`.
The bridge itself does not queue analysis or claim that analysis has completed.
Already bound/discovery metadata YouTube entries can directly use `reanalyze`, even
when `last_analyzed_at` is null; do not use legacy `create` for those entries.

The first binding reuses explicit identity-correction semantics: old contacts/works
remain recorded against their prior identity generation, not promoted into newly
bound source evidence. Existing manual profile fields remain. A different already
bound channel must use explicit identity correction, not this first-binding bridge.

Success replay returns the stored response without another resolution. The resolver
uses the existing YouTube configuration and runs outside the read transaction;
publication rechecks identity/revision under the shared change lock. Duplicate
identity and active Analyze/delivery guards are the existing repository guards.
Handle resolution respects collection pause before network I/O; a direct UC URL
can be bound locally while paused, but Analyze still respects the collection switch.

Expected errors: 409 revision/identity/active-analysis/collection conflicts;
422 unsupported platform/URL; 404 missing Creator/channel; 503 retryable resolution
unavailability; 502 unavailable provider connection. Failed resolution never clears
manual values or caches a successful binding. Reuse the same key to retry a failure;
after an actual success use a new key for a new operation.

## Language source rules

- YouTube `snippet.defaultAudioLanguage` is mapped into the typed video source and
  normalized MapReduce checkpoint, then published as `current_facts.languages` and
  `language_evidence` (raw language label, video URL, provider field name). Each
  source work also retains its provider language. This is provider metadata, not
  proof that the creator's content was watched by a human or model.
- `snippet.defaultLanguage` describes title/description language and is not used as
  audio language. AI audience-language guesses are never promoted to source facts.
- Discovery-only records without a published `languages` field derive language
  from current-identity, same-platform source works (e.g. X post `lang`). Manual
  works and old identity generations do not contribute. Explicit published empty
  languages remain authoritative, preventing stale old works from filling unknowns.
- Manual `languages`, including an explicit empty array, overrides automatic source.
- Unknown/empty/`und`/`zxx` stay unknown. Provider labels are retained, not rewritten.
  Comparison only maps ordinary regional presets, e.g. `en-US` to English and
  `zh-Hant-TW` to Traditional Chinese; ambiguous `zh-TW` does not infer a script.

Official semantics: [YouTube videos resource](https://developers.google.com/youtube/v3/docs/videos).

## Acceptance evidence

TDD demonstrated missing binding endpoint, missing source-language projection, and
the actual MapReduce-success→empty-Library-language defect before implementation.
The final gate includes URL binding→job→production `CreatorMapReducePipeline` with
real `CreatorAnalysisService` publication→same UUID/detail/filter, as well as
discovery metadata→reanalyze continuity. Provider/model/artifact adapters are offline
fixtures; this is not a live YouTube/DeepSeek credential acceptance.

- Final focused set: **194 passed** (18.53s), including existing discovery/language
  alias regressions, actual MapReduce/library continuity and OpenAPI.
- One integrated read-only independent review: **accept, no blocking findings**.
- The first full run exposed a same-transaction relationship-cache regression
  after 378 passed: language projection loaded an empty `creator.works` before
  discovery created source works. A new immediate-detail/second-import test
  reproduced it red; relationship append fixed it and the 194-test set passed.
  No second broad review was opened. The fresh full gate is recorded below.
- Fresh complete real-Redis regression: **2320 passed, 3 skipped, 0 failed**
  (301.47s). The three existing skips concern old live-writer migration lock-order
  scenarios outside the agreed maintenance-window deployment boundary. One existing
  Starlette/AnyIO deprecation warning remains. Current migration head stays `0018`.
- **24 new tests** in this unit. No real provider, model, SMTP or deployment action.
