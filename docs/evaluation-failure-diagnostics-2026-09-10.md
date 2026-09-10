# Deep-evaluation failure diagnostics — 2026-09-10

## What is and is not fixed

This patch repairs the **diagnostic gap**, not the unproven cause of nineteen
historical deep-evaluation failures. Public `evaluation_model_output_invalid`
remains unchanged. After a valid worker claim fails, a structured log records
the run/step IDs, stage, public error code and an allowlisted internal reason.
Unknown reasons become `unclassified`; no exception text, model response,
contact, source input or credential is logged. Successful outputs and the
existing lease/publication rules are unchanged. No migration is needed.

The safe reasons distinguish candidate identity, work-reference membership,
supported-evidence, narrative and schema/response rejection. No validation was
removed, and no automatic retry or additional model call was added.

## Evidence and bounded real verification

Historical failure responses and semantic subcodes were not retained. The old
worker maps these failures to the same code without logging the internal reason.
The prior fixed log window has no evaluation schema-failure event; this does not
identify which semantic check failed for any historical step.

Two isolated samples used the persisted inputs from the current evaluation:

| Stratum | Step | HTTP requests | Tokens | Result |
| --- | --- | ---: | ---: | --- |
| Original failure, attempt 2 | `08e6a0b7-2736-4c35-a1df-a4b7ed407bab` | 1 | 4,189 | Passed |
| Newly selected failure, attempt 1 | `006d13e3-eda4-4660-9a03-a547a08fec32` | 1 | 8,007 | Passed |

Each probe had a hard two-HTTP ceiling including gateway repair; neither needed
repair. Both used `deepseek-flash`, max_tokens 4096, HTTP 200 and finish_reason
`stop`. Both passed schema, candidate identity, work references, supported-evidence
and narrative checks. Total: **2 HTTP requests and 12,196 reported tokens**.
No production job/result was published, no source was reacquired, and no mail
was sent. The original steps remain failed, with unchanged attempt and null output.
Sensitive inputs/responses were kept only in restricted diagnostic storage, not
the repository or user-facing report. No further random sampling was performed.

Read-only/offline checks then established:

- API, Worker and local `evaluation_ai.py` / `deepseek.py` SHA256 values match.
- For both samples, saved probe input equals the current worker's stored
  `game_brief` plus selected EvaluationItem snapshot.
- Replaying the saved response through `production_execute` with a stubbed
  gateway produces exactly the same messages/model/schema/token limit and
  validated result as the isolated adapter path. This replay made zero provider
  calls and zero database writes.
- The configured provider base URL equals the default used by the probe.

Thus no deterministic code, input-assembly or request-context difference was
found for these two samples. This does **not** prove that all nineteen failures
were random, nor that their root cause is fixed. Future failures will carry a
safe actionable subtype after this diagnostic patch is deployed.

## Tests and review

- TDD: six diagnostic unit cases failed before implementation and then passed.
- Related regression suite: **198 passed**, no skips, one existing Starlette
  deprecation warning. It includes DeepSeek adapter/model selection, evaluation
  unit and PostgreSQL integration, evaluation migration and checkpoint retry.
- Worker integration checks assert exact safe subtype logs, unchanged public
  errors and no fabricated Match Brief. An Alembic logger-disable side effect
  in mixed test order is isolated in the test fixture, not production code.
- One bounded independent review: **no blockers**. The reviewer noted an existing
  narrative keyword check can reject a negative statement such as “No viewing
  evidence is available”; this is a separate confirmed example, not evidence
  that it caused the historical nineteen failures, and was not changed here.

Deployment is coordinated separately. This patch does not authorize an online
Activity retry, bulk replay, SMTP sending, or more paid diagnostics.
