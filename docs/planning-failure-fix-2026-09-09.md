# Discovery planning repair — 2026-09-09

## Evidence and scope

Original failed plan `83d03259-473f-4847-8028-1d4c31df007c` belongs to
activity `66ffcb66-e5d7-4880-8d70-a2a94357e4a9`. Its frozen Game is
LIMINAL: Within; platform YouTube, no manual keywords, unrestricted filters.
It failed on attempt1 with `planning_model_output_invalid` and no query.
The historical response was not persisted and existing logs do not distinguish
the underlying validation/envelope/platform reason. Its exact original cause is
**not established**.

Three isolated replays against the old production adapter all ultimately passed;
two required its existing single schema-repair call for invalid query terms.
One resulting real YouTube search returned7 accounts/10 contents with no issues.
These observations justify making term constraints actionable, not claiming that
punctuation is proven to have caused the original failure.

## Minimal change

- Planning instructions explain rewriting title punctuation only within keyword
  phrases, preserving the Game itself and requiring exactly requested platforms.
- Safe validator reason codes distinguish unsafe keyword syntax, duplicates,
  missing alphanumeric text and control characters without echoing model content.
- SearchPlanOutput repair guidance states the same existing restrictions.
- Worker failure logs carry plan ID, attempt and fixed/allowlisted reason codes;
  no raw exception text, prompt, output or credential is logged.

Schema strictness,2048 output budget, the single repair limit, lease/dispatch
semantics and explicit Retry remain unchanged. No automatic retry, new service,
database migration, original plan reset or Profile rewrite is introduced.

## Verification before deployment

- New regression tests first failed; final focused planning API/unit and DeepSeek
  adapter gate: **151 passed**, one existing Starlette/AnyIO deprecation warning.
- One bounded independent review: **Accept**, no concrete internal-Demo blocker.
  No extra full-suite run or expanded defensive review.
- Reviewed source loaded only into an isolated API-container Python process,
  without replacing running application files: same frozen input passed in
  **one DeepSeek HTTP call**, three valid terms, no repair needed.
- Its compiled real YouTube search used two HTTP requests and returned
  **10 accounts/10 contents**, status `more`, no issues.
- Read-only checks confirmed the original failed plan remains failed/attempt1,
  query null, with unchanged frozen Game. No diagnostic records or emails written.

Deployment evidence will be recorded separately after the maintenance window.
