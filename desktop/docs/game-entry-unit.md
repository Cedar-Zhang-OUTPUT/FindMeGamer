# Game entry completion — 2026-09-09

Desktop-only unit following `3403863`. No backend, shared API/IPC contract, credentials, deployment, or external-mail changes. The existing native/full-suite acceptance was not repeated.

## Checked PRD and existing interfaces

The coordinator's verified revision-751 PRD cache (`docs/prd-acceptance-matrix-2026-09-08.md`) and accepted Steam contract (`docs/backend-v2-steam-import.md`) establish:

| PRD | Required behavior | Existing interface used |
| --- | --- | --- |
| P1.1 `doxcnjghsRhdnq5tKDR7PQFKrSf` | Same-context Library/Steam selection, retained inputs, empty Library → Steam, then editable P2 | Game list/detail |
| P1.2 `doxcnu3Tplyh6cQoTvBzKZFDQSb` | Explicit HTTPS `/app/` submit/Enter; no request on paste; failure retains URL with retry/manual entry | `analysis.steamImport` → `POST /api/v2/library/games/steam-import` |
| P2.1 `doxcn3lWs54B8k2VVIO8QNnpwch` | Edit returned Game, optional fields may remain empty, preserve source/manual layering | Game update with returned UUID/revision; existing manual create |
| P12.2 `doxcnDooFzqEExqIRD60OtD45Ph` | “Use for Match” enters editable game setup, not immediate execution | Local guarded navigation, then existing explicit activity creation |

No new server endpoint is necessary for these three entry gaps. Steam source-only import does not run analysis, discovery, or sending. A Steam URL retained during manual fallback is not silently recast as the game's official website, source identity, or inferred tags.

## States and transitions

- Game detail → Use for Match → game editor → Use game → named activity setup. Entry creates no activity or paid work. An unchanged record can continue without a PATCH.
- New activity → Library/Steam tabs. Mounted panels retain Library search and Steam URL. Empty search has a direct Steam button. Arrow/Home/End keys select tabs.
- Selection/import → review of the returned Game. Explicit edits use the returned UUID/revision and retain reference IDs; activity references remain explicitly selected, not inferred.
- Definite Steam failure → Enter manually in the same context. Original URL stays visible. Cancel with dirty fields asks before discarding; continuing editing preserves fields, and returning to Steam preserves the original retry request/link.
- Pending/unknown source writes lock source switching and manual fallback. Same-request retry keeps its immutable key/body. Source requests may be retained in the existing Analysis drawer with an explicit acknowledgment; this is not cancellation or success.
- Match now hosts the existing AnalyzeProvider so retained source requests have real storage for the mounted workspace and a visible Analysis tasks entry, rather than a no-op context. Credentials repair forwards to both current-task and retained-analysis guards.
- Parent activity drafts remain guarded while reviewing a Game. Game confirmation does not bypass the activity's own confirmation. Library handoffs reveal the retained Match task before its guard runs. Consumed handoffs are cleared, so reactivation cannot replay an old request.

## Verification

- TDD: three new entry tests initially failed (missing tabs, editable handoff, manual fallback), seven existing cases passed. Implemented the entry paths and adapted prior activity tests to the required explicit game-review step.
- Final affected regressions: 17/17 across NewActivity and MatchWorkspace (3.08 s); 86/86 across renderer, games renderer/query UI, Creator game picker/forms, Analyze Library/workspace, and source import (12.41 s). **103 passed across nine files**, not a new full-suite claim.
- Typecheck and build passed. Build: 124 modules, `index-BGBWdCEQ.js` / `index-BKj7H0fI.css`; existing >500 kB chunk warning remains.
- The sole bounded review was interrupted before findings and resumed. It found one P2: parent activity guard disabled during game review. Fixed; regression covers pristine review and dirty game discard followed by activity confirmation. Reviewer performed only that finding's fixcheck and closed it. Dialogs already use a portal, so no extra visibility redesign was needed.
- Real built renderer + production Node clients + existing synthetic API 64692: **1/1 passed**, test 1.5 s / run 2.3 s. Library detail → Use for Match → unchanged review; Library/Steam switching retains search/link; explicit Enter performs one real source import; returned UUID and manual/reference/analysis fields preserved; review → setup. No activity creation or analysis/SMTP request in this test.
- Ledger: `/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-xmmhoufp/private/game-entry-39b2fc4d-ea4e-441b-b7a3-8ca39ff281e8.json`.
- Nine GETs, one POST (Steam import), source revision 4 → 5 for existing Game `7ad5e819-e330-4c29-8b71-bbf544e793d6`; exactly one synthetic Steam event and no model/mail events. Existing controls unchanged; no old data removed. Zero page errors, unexpected bridge calls, or forbidden requests.
- Final source tree SHA-256 `aca5280bef2fb0bf396903e0cea15cf5e7d33f6e2deffe92099834b44e750614`; renderer bundle tree SHA-256 `1cc7f4c5898bdd418b2226eac6e2881f094a6d1c68bb577d1c2a8efc7ab2411c`; both unchanged throughout the real-API run.
- Visually inspected `desktop/output/playwright-game-entry/game-entry-game-entry-buil-45b12-ne-source-only-Steam-import/game-entry-narrow.png`: 760 px / 135% text / reduced motion, no horizontal overflow. Four remote artwork requests deliberately suppressed; this does not certify artwork loading.

## Remaining boundaries

This unit is not the final native write-path run, complete PRD acceptance, live Steam/provider validation, or SMTP delivery verification. Definite source failure/manual fallback, uncertain retry/archive, and dirty-return branches were verified in component tests, not by toggling shared fault controls in the real-API run. Global Outreach is the next separate scope/API check. No GitHub push, installer, release, or deployment was performed.
