# Native provider compatibility inventory

Status: Task 3 compatibility changes implemented on the native branch; validation evidence below.

The restored native baseline is `97bcd95`, not the deployed v2 application. Do not copy entire v2 commits simply because one repair is useful.

| Capability | Baseline evidence | Restoration action |
| --- | --- | --- |
| Public-page email discovery with Gemini fallback | `creator_pipeline._discover_creator_contacts_with_research`, introduced before this baseline by `8bb8f65` | Preserve. Normal discovery runs first; Gemini is used when no email candidate was found and its gateway is configured. |
| Multiple email addresses, purpose/source and recipient choice | CreatorContact purpose migration `20260904_0007`; native contact arrays and outreach recipient selection | Preserve existing API and native behavior. General descriptive Profile editing is a separate Save from contact/notes editing. |
| DeepSeek model names | Baseline pipeline constants still use v4 Flash, vision-exp and Pro names | Adapt applicable parts of `e924c52`, including gateway mapping of historical aliases, with focused tests. Do not bring in X/discovery/draft v2 modules. |
| Normal-length AI narratives | Short map/reduce and Creator Brief limits in baseline schemas | Adapt relevant repair from `e43b6ed`: preserve source/type/reference validation and aggregate size protection; avoid failing an otherwise valid Profile for a small overrun of a stylistic length target. |
| Creator stage checkpoint reuse | `creator_map_reduce_pipeline` loads source, batch, visual, contacts, reductions and Brief checkpoints; `cli/resume_creator_analysis.py` has maintenance recovery | Already present. Test it; do not add the v2 activity/search scheduler from `991a8ef`. |
| Pairwise matching checkpoint reuse | Existing native matching worker/repository and `test_match_checkpoint.py` | Preserve and include in regressions. |
| v2 discovery/activity personalizations, X/four-platform workflow | Added after native baseline | Excluded from this native restoration by design. |
| Deep Match viewing-word repair `241aa11` | Changes only `discovery/evaluation_ai.py`, absent from native baseline; native `ai_match.py` has no equivalent vocabulary block | Do not import the v2 evaluation service for this fix. |

Saving a manual Profile edit must not make any provider request. Local deterministic tests do not establish fresh paid-provider availability; report that boundary explicitly.

Directly opened on September 14: [DeepSeek API quick start](https://api-docs.deepseek.com/) identifies `deepseek-flash` and explains retirement/routing of the old Flash and experimental vision aliases. The [vision guide](https://api-docs.deepseek.com/guides/vision/) explicitly supports image input with `deepseek-flash`. Search-index excerpts were stale, so this inventory uses the direct pages. The separate Pro model remains offered, but this project's previously approved choice is Flash for every DeepSeek stage.

## Baseline test-clock finding (diagnostically verified)

Isolated baseline: 1,818 passed, 3 skipped, 4 failures in `test_resume_creator_analysis.py` (queue failure and the three resumed-stage variants). The tests inject `NOW = 2026-09-07T10:00Z` into the service, but `JobsRepository.create_or_reuse_job` lets the database assign current `created_at` through `func.now()`. On September 14 the resumed job therefore starts/completes earlier than its database creation time, violating the normal job contract.

A one-shot pytest plugin aligned only missing test `AnalysisJob.created_at` to `2026-09-07T09:59Z` before insertion. All four previously failing tests then passed (0.31 s, 26 deselected). Log: `.superpowers/sdd/2026-09-14-native-profile-editing/clock-probe.log`. Task 3 implements that alignment as a module-local autouse fixture using a SQLAlchemy before-insert listener, removed after each test. Explicit timestamps remain unchanged. No application clocks or job validation changed.

## Applied changes and provenance

- `e924c524d49e4a817c93627a203ef8d4e462a28d`: selectively adapted existing Game/Creator extraction, vision, synthesis, map/reduce and matching defaults, plus newly published model metadata, to `deepseek-flash`. The gateway maps the three historical v4 aliases to Flash for outbound requests and repairs, without rewriting saved records. Connection probing already uses `/models` and has no model default. Native domain mapping still treats historical metadata as data.
- `e43b6ed8e35b4480803bc285eb83d1bf9010db14`: selectively adapted existing Creator schema fields to 4,000 characters for prose/reasons/observations and 512 characters for descriptive list items. Creator map/reduce stages retain 32,000-byte aggregate guards; the published Creator Brief retains an 8,000-byte aggregate guard. Type, nonblank, uniqueness, evidence count and exact citation validation remain. Game Brief and downstream matching input budgets are unchanged.
- `991a8efbc21a1203fe1ec4c131bdac6dc7bba862`: automatic v2 activity/search scheduling remains excluded. Existing native stage checkpoints, failed-email retry behavior, pairwise checkpoint reuse, duplicate delivery handling and maintenance recovery are retained and tested.
- `241aa112aab9fde0f6d9c69a45d8ab462ecbbbf4`: viewing-word repair remains inapplicable because its discovery evaluation module is absent here.
- `8bb8f65913a65039d19542a4e9f85f24e05d255a`: public-page/Gemini email enhancement remains intact, including first-email binding, purpose/source preservation and multi-email deduplication.

The bounded Task 2 integration correction shares the existing Creator `source_status` visibility policy between public detail and editor documents. GET and PATCH editor responses return null source values and empty effective values for stale content, except for explicit manual overrides. Saving an unrelated field succeeds even when the untouched required source title is empty. Manual values remain editable and visible. No provider request, source deletion, migration, DTO or endpoint shape change is introduced by this correction.

## Validation and deferred work

Focused RED: 21 failures, 34 passes, including old model requests/defaults, normal prose rejection, stale source exposure and the four fixture-clock failures. Focused GREEN: 295 passes, including Creator and pairwise checkpoint regression tests. Final full backend: **1,851 passed, 3 skipped**, 109.68 seconds; native domain mapping: **5 passed**. The backend retains its existing Starlette/AnyIO deprecation warning; native generation retains existing nullable/PublicJSONValue warnings. Exact commands and intermediate evidence are recorded in the Task 3 report.

Optional scheduling/performance tuning and provider health UI improvements remain deferred. No paid calls, production changes, Keychain access or deployment were performed; local deterministic tests do not prove fresh live-provider availability. The native migration remains `20260914_native_0008`.
