# DeepSeek Flash model selection and isolated validation

## Model-selection change

All newly selected DeepSeek models now use `deepseek-flash`: Game and Creator text/vision/synthesis, Creator Map-Reduce and Brief, X analysis, legacy Match screening/pairwise/ranking, Discovery planning/evaluation, and Outreach draft generation. New task/publication model metadata uses the same name. Existing configuration exposes provider keys/base URLs, not a model-selection override.

The request gateway maps the three known historical names (`deepseek-v4-flash`, `deepseek-v4-flash-vision-exp`, `deepseek-v4-pro`) to `deepseek-flash`, covering saved plans and recursive repair calls. Existing stored histories are not migrated or rewritten. Gemini, image acquisition/inlining, concurrency, output budgets and validation rules are unchanged.

The official [pricing/model page](https://api-docs.deepseek.com/quick_start/pricing/) and [2026-09-10 changelog](https://api-docs.deepseek.com/updates/) were read directly. They identify `deepseek-flash` as V4.1 Flash with native vision; the older Flash/vision aliases are temporarily routed to it. This does not establish which underlying model served a particular earlier request. The model-name change is separate from output-validation failures.

## Local automated verification

- New model-selection tests initially produced 12 expected failures and 1 pass.
- After the change, a targeted selection of 633 tests passed, covering text/vision gateway behavior, analysis, matching, publication metadata, Creator Search and model selection.
- A supplemental selection of 166 tests passed, including explicit vision request-model assertion, planning, evaluation and Creator Search API. These selections overlap; they are not 799 unique tests.
- The gateway tests exercise known historical aliases and their repair requests without changing stored inputs. Existing failure/truncation logging now correctly reports the actual outbound model name.
- Bounded independent review found no blocking issue. It noted that retained successful checkpoints may come from earlier model choices; final Profile metadata is not a per-node execution ledger. Do not claim that an explicit retry reruns all stages with Flash.

## Two real failed-stage samples

Only two previously failed jobs from Search `01b3b649-f5ad-40b1-a146-aac2d666e1ea` were exported read-only. Their successful checkpoints and minimal failure metadata were retained locally, not the full production database. Hashes of six relevant production source files were verified against the frozen deployed source. Successful checkpoint schemas and evidence references passed offline validation before replay; current prompts/schemas stayed unchanged.

The isolated Docker project is `fmg-creator-failure-repro-20260910`, with its own PostgreSQL and Redis. Its fresh database was migrated to 0022, API readiness was checked through TestClient, and a worker using a dedicated empty diagnostic queue responded to inspection. No original production job was enqueued there. Two checkpoint snapshots were stored in a diagnostic table. Existing frontend fixtures, including port 18093, were not changed.

| Sample | Replayed stage | Result with new model name |
| --- | --- | --- |
| `92192013-82fb-4275-a3b2-ffeeb86a04f2`, originally `deepseek_model_output_invalid` | Presentation reduction only; reuse completed map/visual inputs | Still fails after standard repair: `production_quality.available.value` is 322 characters, exceeding 320. |
| `af98a11d-a069-4551-a0c0-e700e8a0be58`, originally `deepseek_model_contacts_invalid` | Brief only; reuse all four successful reductions and existing contact evidence | Succeeds after existing Brief text repair; schema, evidence references and contact ID/kind binding pass. |

The original Presentation time-window logs also show `string_too_long`, including the same field after repair. Original failed raw responses were not stored by production; their exact full output cannot be reconstructed. The new Brief sample passing does not establish the precise original contact-selection mistake or prove that all contacts errors are fixed.

## Actual model-request ledger

Exactly **4 actual model HTTP requests** were sent, sequentially, all using `deepseek-flash`. The hard limit includes repair requests. All returned HTTP 200 and `finish_reason=stop`; none was a truncated response.

| Request | Stage | Tokens | Validation |
| --- | --- | ---: | --- |
| 1 | Presentation initial, max_tokens 2048 | 5,375 | Six overlong fields; response body 4,954 bytes. |
| 2 | Brief initial, max_tokens 3072 | 8,291 | Four Brief values longer than 144 characters; body 4,472 bytes. |
| 3 | Presentation standard repair, max_tokens 2048 | 7,017 | Only the 322/320-character field remains invalid; body 3,698 bytes. |
| 4 | Existing Brief text-only repair, max_tokens 2048 | 595 | Repair and complete Brief schema/evidence/contact validation pass; body 1,037 bytes. |

Total: **21,278 tokens**. There was no fifth request. No YouTube/X acquisition, Gemini search, SMTP, production mutation or deployment was performed for these replays. The existing local encrypted DeepSeek credential was read into memory only. Recent production DeepSeek logs had no 429 before starting; the replay would stop on 429 and no such response occurred.

The diagnostic wrapper initially passed the wrong argument shape to the safe-error helper, producing a local KeyError after each initial response. The wrapper was corrected; the two already-paid raw responses were replayed locally into the unchanged gateway repair path, not regenerated. The ledger was preserved across this continuation, and both actual repairs count toward the same four-request limit. This diagnostic error was not an application failure or success.

## Retained evidence and handoff

Ignored local directory `.local/creator-failure-repro-20260910/` has mode 0700. Checkpoints, request inputs and raw response files are private; raw responses/checkpoints have mode 0600 and are not committed. `offline-report.json` and `replay-report.json` hold source hashes, exact HTTP count, stage/model/finish reason/usage, response lengths, safe validation locations and contact binding checks. No email values, keys or authentication headers are included in this document.

This change does not fix the remaining Presentation length failure and does not widen validation or truncate model text. It should not be presented as a complete successful Creator reanalysis, a fix for all failed creators, or a production E2E validation. Successful prior checkpoints were reused. The four-request budget is exhausted; any further paid validation requires new authorization.

At the last pre-validation production snapshot (16:34:08 Shanghai), the user's Search was still running in `profiles`: 21 ready including 11 reused, 14 failed, 1 running and 14 pending. No stop/retry/restart was requested. Deployment requires the coordinator's separate safe window; no production code has changed in this unit. Continuous-refill concurrency and shared Service health remain separate deferred tasks.
