# Language filter integration fix

> **For agentic workers:** Use executing-plans inline, TDD and one bounded review.

**Goal:** Make the existing15 language presets compare consistently with saved
display labels in Library and discovery filters, without rewriting stored data.

**Architecture:** One pure comparison helper maps only the explicit code/English/
Chinese labels in desktop `discoveryConditionState.ts` to a casefolded code. Apply
it to requested values, effective Creator values, and usable discovery content
language metadata. Other labels retain trimmed/casefolded exact matching.

**Tech Stack:** Existing Python/FastAPI/SQLAlchemy; no migration or dependencies.

**Spec:** Root's explicit integration correction2026-09-08 after accepted8cf755e:
English preset submits `en`, manual Creator allows `English`; both directions must
match. Chinese scripts stay separate; ambiguous `zh` stays ambiguous.

## Constraints

- Scope only comparison in Library/discovery, preserve source/manual/raw work data.
- No language detection, translation, region guessing, migration, or frontend edits.
- Explicit unknown-language policy (`und`/`zxx`) and manual override priority remain.
- This is a separate unit after named sets; do not reopen their accepted reviews.

## Implementation and test sequence

Files: new `backend/app/core/languages.py`; modify
`backend/app/repositories/creator_library.py` and `backend/app/discovery/library.py`;
new `backend/tests/integration/test_language_filter_aliases.py`.

- [x] Red Library: save manual `English`; GET `languages=en` must find it and still
  return/store `English`. Reverse `en`→`English` works; use literal test data.
- [x] Red discovery: known manual English + filter en accepted, including content
  metadata en + filter English when no manual override; no extra acquisition.
- [x] Green `language_key(value: str) -> str` explicit15 mappings;
  `language_keys(values) -> set[str]` trims/blanks, used on both comparison sides.
- [x] Table-driven every preset, simplify/traditional distinct, unknown zh not
  coerced, custom trim/casefold equality and non-alias labels remain independent.
- [x] Relevant Library/discovery suites then full realRedis regression; one bounded
  independent review, only real internal-Demo blockers. Document and local commit.

Example regression expectation: `assert response.json()['total'] == 1` for manual
English queried with `en`, and `assert stored.manual_overrides['languages'] ==
['English']` after comparison. Chinese `zh-Hans` must NOT match `zh-Hant` or `zh`.

Completed verification:62relevantpassed;2184fullpassed/3deferred/0failed190.01s;
one independent review ready/no blockers. No stored data or schema changed.
