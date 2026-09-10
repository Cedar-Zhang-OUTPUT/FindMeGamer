# Automatic Find creators verification — 2026-09-10

## Scope

Frontend-only integration of the independently supplied creator-search API.
No backend source, old Query/Plan DTO, production data, SMTP, or sealed internal.5
package was changed. No automatic upgrade or restart of the user's existing task.

Main path: conditions → one explicit Find creators request → backend task stages
and processed counts → terminal task and complete paginated results → explicit
review of selected creators. Email availability does not determine fit.

| State | Main focus/action | Supporting information |
| --- | --- | --- |
| Conditions | Platform selection / Find creators | Source settings expandable; blocking errors and quota consequence visible |
| Processing | Current backend stage / Stop search | Counts; processing details expandable; no Draft N or Evaluate loaded |
| Stopped or partial | Retained results / Retry unfinished work | Unknown-outcome retry requires fresh charge acknowledgement |
| Completed | Creator matches / Review selected | Match reason, related works, independent email badge; more details expandable |
| Read failure | Local recovery / Refresh | Prior results retained, selection disabled until current |

Search conditions and history use named disclosures. Legacy searches remain
available without automatically evaluating or restarting them. Saved lists do
not display alongside the automatic results as competing primary sections.

## Verification inputs and commands

- Actual FastAPI serialization bundle supplied by the backend task:
  `.local/creator-search-contract/creator-search-api.json` in the main workspace.
  Its raw queued/partial/completed tasks, creator pages, history, evaluation results
  and candidates pass the production strict decoders without projection.
- Exclusive synthetic HTTP fixture: `http://127.0.0.1:18093`, backend git archive
  `755cc4827bbefa174e7e673f526692bcef458d65`, database migration 0022.
  Credentials are read privately; no keys, headers or credential screenshots are
  included in evidence.
- `FMG_CREATOR_SEARCH_DTO=<private bundle path> npm test -- --maxWorkers=2`
- `npm run typecheck` and `npm run build`
- `FMG_CREATOR_SEARCH_NATIVE=18093 npx playwright test e2e/creator-search-native.spec.ts`

## Native acceptance

Final frozen-source results: 121 test files passed, 1251 tests passed and 5
environment-gated tests skipped (actual creator-search DTO gate enabled).
Typecheck and build passed; both native journeys passed on the final build
(21.2 seconds combined). `git diff --check` passed. The coordinator's independent
review found no internal-Demo blockers; its 12 targeted tests, including actual
DTOs, passed. Source submission is authorized. Packaging and publication remain
on hold pending the separate backend real-model evidence check.

Two Electron development-build journeys use the actual preload IPC, production
HTTP adapters and fixture API. They create only new synthetic activities.

1. Create an activity for Synthetic Star Garden, choose YouTube + X, click Find
   creators once, observe Stop while processing, then six complete match cards.
   Four have email and two do not; all six retain their evaluated fit. Returning
   to the activity restores the results. At 760 px no horizontal overflow occurs.
2. Start a new search, explicitly stop it, observe Search stopped, retry the same
   task, then reach the same complete six-result state.

Both run with reduced motion and count renderer exceptions. Network gates reject
non-fixture HTTP and any writes outside owned activity creation/search creation
and, for the second journey, its exact task's stop/retry routes. No evaluation or
sending POST is allowed. Reports list only route paths, never credentials.

Evidence is under `desktop/output/playwright/`:

- `creator-search-native-auto-e3208-s-email-independent-matches/`
- `creator-search-native-auto-3c12f-ated-HTTP-stops-and-retries/`

Each contains `verification.json`, conditions/processing/complete/narrow PNGs;
the stop/retry journey also contains `stopped.png`. Main-agent visual inspection
covered completion, narrow layout and stopped state.

## Boundaries

The HTTP fixture uses synthetic provider, Profile, email and model implementations,
and in-process dispatch, not a real broker. This is not production-provider,
real-broker, signed-package or DMG acceptance. The backend task owns those gates
separately. No failure injection exists in this fixed fixture; partial-failure and
unknown-outcome interactions are component/actual-DTO tests, not native failure
injection. Pagination beyond one page is tested with 120 synthetic unit results.
Keyboard-only completion and assistive-technology navigation have not been fully
walked end-to-end. Build retains the existing large-chunk warning.

Do not publish the sealed internal.5 artifact as containing this work. Version,
new packaging, final integration and GitHub upload remain coordinator-owned.
