# Independent discovery directions — internal Demo

## Incident and scope

After the authorized September 13 reset, LIMINAL: Within searches
`fe5cdd6e-cb50-49ee-8f09-43ca773b28bd` and
`7a01ea52-33d1-456b-818d-dbf161bde355` completed with zero candidates.
DeepSeek, YouTube and X all returned HTTP 200. The old compiler joined three
quoted phrases into a single query; both providers returned zero items. Appending
reused the exhausted query without another provider call.

This release changes discovery, not AI matching or outreach. Instagram/Twitch
remain Library-only. No new infrastructure or schema migration is required;
the known database head stays `20260913_0023`.

## Implementation

- Each platform has at most three independent search directions. New planning
  prompts favor genre/gameplay, supplied reference works and related content;
  the target game title is optional and ordered last when present.
- Existing JSONB conditions hold the immutable directions. Per-direction status
  and query-bound cursor persist in provider state. Pages rotate between remaining
  directions; empty results advance to another direction.
  Platforms also rotate so a long YouTube cursor cannot consume every batch before
  X gets its first request.
- All pages still use the existing durable attempt, lease, total/batch request and
  scan reservations. Candidate identity deduplication spans directions. Successful
  exhausted directions are not replayed. Known failures may still be explicitly
  retried; unknown outcomes retain the acknowledgement requirement.
- Explicit **Find more creators** on an old automatic search recompiles the saved
  plan without a model call. It preserves filters, existing results and cumulative
  budgets. GET requests and deployment do not upgrade or rerun searches.
- YouTube pages configured for three requests fetch `search`, `channels`, and
  batch `videos(part=snippet)` metadata. `defaultAudioLanguage` takes precedence;
  `defaultLanguage` is a fallback declaration for title/description language, not
  proof of audio language. `language_source` preserves the distinction. Discovery
  language filtering is on recorded content metadata, not a verified contact
  language; missing values remain unknown. No viewing evidence is created.
- Direct requests capped at two still make at most two calls. New generated
  YouTube requests expose the truthful `max_requests: 3`; three requests must be
  reserved before I/O, or no page is requested. Unused reservation is conservative;
  `usage.requests_used` records actual calls. Existing batch/total caps are unchanged.
- Public query JSON retains its shape. Internal direction cursors are omitted.
  The desktop decoder needs the coordinated internal.12 change allowing a page
  cap of three while retaining support for two. Do not release the server change
  without making that compatible client available.

## Verification

TDD first reproduced four failures: independent fallback, legacy exhausted recovery,
three-request language metadata and corrected query compilation. The relevant
regression group passed 156 tests with three broker-fixture skips; an additional
38-test run passed the final append/idempotency and metadata cases. An independent
bounded static review found no blocking issue (the reviewer did not run tests).
The final changed-path regression run passed 122 tests, including the added
platform-fairness case. A broader intermediate run had 216 passes, three skips and
three logging-test failures caused by preceding migration tests disabling existing
loggers; the logging assertion now explicitly isolates that test-side effect.

The real-provider check used a dedicated local PostgreSQL database, no Worker,
no AI calls and no SMTP. It reproduced the saved exhausted LIMINAL plan and used
the unchanged user filters: US/CA/JP/KR, English/Japanese, 0–99,999 followers, all
three unknown-field exclusions enabled. The validation batch target was one so
the run stopped after proving nonzero eligible candidates; this did not relax
any eligibility filter and is not the production batch target.

| Source / independent query | HTTP calls | Raw items / accounts | Eligible unique candidates |
| --- | ---: | ---: | ---: |
| YouTube — `indie horror mystery` | 3, all 200 | 50 videos / 39 accounts | 10 |
| X recent — `horror RPG strategy -is:retweet` | 1, 200 | 3 posts / 3 accounts | 0 |

YouTube rejection counts were country 15, language 2, followers 26; reasons can
overlap. All three X authors lacked an acceptable known country and were excluded,
not assigned an inferred country. Examples among accepted metadata candidates:
Dregobob (US, 52,300), KazzaGamesTV (US, 85,800), KrysticGames (US, 1,570), Cryx
(US, 918). Some broader results are horror-film channels: **ten eligible metadata
candidates is not ten AI-approved game matches**. Existing downstream evaluation
remains responsible for content fit. No guarantee of 100 candidates is made.

The validation stopped at four HTTP calls, below the approved ceiling of 18
YouTube plus three X calls. Raw normalized metadata and the report remain in the
ignored isolated fixture, not production or this repository. No production
Profile, task, draft, setting or secret was changed by validation.

## Release and operator handoff

Coordinate internal.12's decoder before server release. Verify the existing
automatic search is readable and its **Find more creators** control is enabled;
that control does not disable solely because discovered count is zero. The older
manual discovery-only page has its own exhausted-source disabling behavior and is
not the affected automatic-search recovery entry.

Use a maintenance window after confirming no active work, retain a verified
database backup and protected configuration hashes, deploy the precise reviewed
revision, and check health and authenticated reads. Do not clear Library, rewrite
historical outcomes, or automatically run the user's new batch during deployment.
Deployment evidence will be recorded after release.
