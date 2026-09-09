# Global Outreach entry

## Scope and contract

Global Outreach now opens existing activities and their invitations. Match and Outreach share one mounted workspace and activity session. No backend, shared contract, SMTP behavior, campaign model or synthetic runtime data changes.

Checked the verified PRD acceptance matrix, P9 and the Outreach v2 handoff against the accepted activity-collaboration unit. Existing activities, invitations, creator history and sending APIs cover this entry; no additional global invitations endpoint is required.

## Task and states

| State | Primary action | Context retained |
| --- | --- | --- |
| Activity list | Open activity | Existing list and pagination |
| Invitations | Review response / edit progress | Activity, response and follow-up filters |
| Creator detour | Inspect source activity relationship | Common creator profile; All activities remains available |
| Continue in Match | Prepare another selection | Same loaded activity session; no automatic discovery |
| Email settings | Configure email | Source page and unsaved progress draft |
| Disconnected / read failure | Connect / retry | Existing connection and local recovery UI |

Only the active task is foregrounded. Source activity history opens contextually; Library keeps its lazy all-activity history. Surface changes use the existing dirty/unknown mutation guards; settings detours preserve their owner. Existing invitation response semantics and explicit-failure retry rules remain unchanged.

## Evidence

- TDD: initial global entry tests failed against the placeholder; creator-source test failed before context wiring.
- 49 tests passed across global-outreach, renderer, collaboration-workspace, match-workspace and creator-forms. Typecheck and production build passed (existing >500 kB chunk warning remains).
- One bounded independent Medium review found no reproducible P1/P2 navigation, session identity, guard or context defects.
- Built renderer + production Node clients + exclusive synthetic API 64692: real activity opened from global Outreach; source Creator history, retained invitation filter and Continue in Match verified. 33 GET, zero POST, zero runtime/bridge/forbidden-request errors; fixture effects unchanged. Initial ledger: `c-renderer-08375a8a-3793-48ca-9067-34f230481a4d.json` in the private fixture directory.
- Narrow 760 px, 135% root text, reduced-motion browser verification has no horizontal overflow. Screenshot under `output/playwright-global-outreach/` (ignored local evidence).

No fresh native run, full suite, SMTP send, model invocation, cloud deployment or release packaging is claimed for this bounded entry change. Previously accepted invitation write controllers are reused; this real-API run intentionally permits GET only.

## Release handoff

Coordinator handles verified AWS deployment, then client default origin and release packaging/upload. Connection defaults are currently empty in `src/main/credential-store.ts` and `src/renderer/components/ConnectionSettings.tsx`; do not invent a cloud origin or overwrite existing saved credentials. Packaging entry: `npm run bundle:dir` / `scripts/package.mjs`. Cloud origin/revision verification and unconfigured SMTP remain release/test limitations, not missing frontend contracts.
