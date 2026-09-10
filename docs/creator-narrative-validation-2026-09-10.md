# Creator narrative validation correction — 2026-09-10

Scope: internal Demo; repair ordinary Creator prose rejection, not concurrency,
platform acquisition, service health, schema migration or email sending.

## Contract changes

- Creator Map/Reduce narrative values, observations and unavailable reasons:
  4000 characters, aligned with the existing final CreatorSynthesis text contract.
- Reducer list/style items and CreatorBrief list items: 512 characters, aligned
  with the existing final Profile list contract. CreatorBrief narrative: 4000.
- Each Map/Reduce stage retains a unified 32000-byte serialized JSON guard.
  CreatorBrief retains a separate 8000-byte aggregate guard.
- Existing brief/concise prompt instructions and model output-token budgets are
  unchanged. These are safety ceilings, not requested output lengths.
- Nonblank/type/enum/English check, array counts, uniqueness, evidence provenance,
  source-reference membership and contact ID/kind binding are unchanged.
  No truncation, invented evidence, database changes or historical rewrites.

## Verification

New offline regression first: 5 failures, 4 passes under old contracts. Following
implementation and two additional map/aggregate cases, final combined run:
**594 passed**, one existing Starlette deprecation warning. Selection:

```
tests/unit/analysis
tests/unit/matching
tests/unit/integrations/test_deepseek.py
tests/integration/test_creator_analysis_commit.py
tests/integration/test_library_v2_creator_analysis.py
tests/integration/test_creator_analysis_checkpoints.py
tests/integration/test_resume_creator_analysis.py
```

Includes ordinary 322/800/2000-character narrative, 400-character list items,
800-character observations/reasons, lossless final merge, aggregate rejection,
and existing evidence/contact/checkpoint/publication regression coverage.
Existing tiny-limit tests now exercise the wider actual ceilings; semantic
repair remains bounded and covered when a response really exceeds those ceilings.

### Retained real-response replay

Reused protected local responses from the preceding four-call experiment;
**zero new HTTP/provider calls and zero production writes** in this unit.
Raw content/contact data is not committed.

| Saved response | Validated output bytes | Final synthesis bytes | Result |
| --- | ---: | ---: | --- |
| Presentation initial | 3585 | 18989 | Passed |
| Presentation repair (322-char value unchanged) | 3034 | 18438 | Passed |
| Brief initial | 3678 | 20567 | Passed |
| Brief existing text-only repair, applied to original Brief | 3567 | 20456 | Passed |

All four pass schema and supplied evidence validation, lossless merge, public
JSON projection and both current and frozen internal.5 Creator detail decoders.
Both real Presentation outputs can build the next Brief prompt using the saved
other reducers/contact evidence. Their final merge uses a neutral fixture Brief
because that job never reached Brief; this is not a claimed real full-job replay.
Both Brief cases bind the actual saved contact candidates. Deliberately unknown
evidence references and contact IDs remain rejected. The DTO check combines real
analysis metadata with synthetic identity/contact fields; no live HTTP or DB
publication was performed for these private samples.

## Bounded independent review and remaining limits

Independent review found no demonstrated blocker within the ordinary prose
failure/current v2 workflow scope. It confirmed no evidence/contact weakening
or silent data loss. These existing aggregate input limits remain unchanged:

- Legacy Match actually caps total messages at 512KB. Although 100 x 8KB plus
  Game/overhead fits the gateway's 1MB ceiling, it does **not** follow that legacy
  Match accepts 100 briefs simultaneously near their maximum. Current v2 batches
  20 candidates. Do not present the 1MB calculation as a Match guarantee.
- Analysis prompt construction caps one user message at 90KB and all messages
  at 96KB. All four reducer outputs cannot simultaneously reach 32KB and fit
  the next prompt. Actual retained inputs/outputs fit. Near-ceiling synthetic
  payload handling is deferred, not silently truncated or claimed supported.

No deployment, running-job interruption, retry, new acquisition or sending.
Deployment and the separately authorized single failed-search retry require
coordinator release after this unit. Model-name commit e924c52 is preserved.
