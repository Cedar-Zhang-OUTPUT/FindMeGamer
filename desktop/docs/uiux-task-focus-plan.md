# Task-focused UI/UX — 2026-09-10

Frontend only, following the user-approved task-first design principles. Preserve
the current visual skin, backend/API semantics, edit guards and release artifacts.
No automatic task execution, sending or user-data edits are part of this work.

## Main paths and information hierarchy

| Area | Primary task and default focus | On-demand information | Next state / return |
| --- | --- | --- | --- |
| Match | Start an activity, then inspect matched creators | Search conditions, processing details, history | Stage/counts while running; results on completion; creator detour returns to selection and scroll |
| Library | Find a saved creator or game through search/results | Less frequent filters, source fields, metadata | Open object without duplicate page framing; back restores query/filter/page/scroll |
| Creator | Understand this person and find relevant contact/work records | Account provenance, old identities, analysis evidence | Exactly Profile / Invitations pages; Profile contains visible resource groups, not nested Overview tabs |
| Outreach | Inspect the selected invitation and choose its next action | Filters, preparation/draft/send history | Keep relationship and edit context; local errors/recovery beside the affected action |
| Settings | Edit the selected category | Technical connection details and advanced settings | Keep pending edits; show shared impact and recovery before consequential actions |

## State checklist

| State | Primary content/action | Preserved context / disclosure |
| --- | --- | --- |
| Empty | Explicit start/add action | Short object label; no large instructional panel |
| Loading | Reserved content area and local status | Keep existing content on refresh; do not steal focus |
| Viewing | Current object/result | Quiet global navigation; one coherent action group |
| Editing | Edited fields and Save/Cancel | Keep user input and existing navigation guards |
| Processing | Actual phase and counts, supported stop | Details expandable; no invented progress or premature completion |
| Confirmation | Affected result and explicit confirm/cancel | Consequences, charges and restrictions visible before decision |
| Partial failure | Successful content plus failed part/retry | No whole-page reset or invisible blocking error |
| Blocking error | Problem and recovery | Keep prior context and safe return |
| Return | Previous object/list and opener | Restore scroll and focus; no automatic execution |

## Observed baseline and bounded units

Read-only native audit on exclusive synthetic HTTP fixture 18093 passed with zero
write attempts and zero renderer exceptions. Baseline screenshots live separately
under `desktop/output/playwright/uiux-baseline-20260910/`.

1. **Creator:** Baseline's Library framing, 200 px identity card, detached analysis
   action, Profile tabs, large empty analysis card and nested Overview tabs pushed
   emails/works below the first viewport. Match also showed two different back
   labels for the same destination. Compact identity/actions; use one contextual
   return; preserve exactly Profile / Invitations. Within Profile, named email and
   work groups show counts and available previews before expansion. Preserve lazy
   works loading and directly opened email/work intent. Empty analysis becomes an
   expandable status, never a large empty highlight panel. Supported claims retain
   their AI/source context and limitations.
2. **Match/Library:** Merge redundant framing/tool rows to bring results upward.
   Keep search/filter state and all primary/advanced entry points. Do not globally
   shrink fonts or hide meaningful result facts.
3. **Outreach:** Baseline activity's selected relationship detail is below a full
   wide list, weakening selection feedback. Bring object and list into a clear
   responsive relationship; compress repeated framing/filter space. Do not modify
   invitations, draft qualification, sending confirmation or recovery semantics.
4. **Settings:** Keep stable categories and current editable panel. Avoid repeated
   guidance and equal-weight auxiliary actions; preserve shared-scope warnings,
   unsaved-state protection and connection repair/return paths.

Each unit gets targeted state/interaction tests and before/after screenshots,
including narrow layout, keyboard and reduced-motion checks. Broader regressions
are run at meaningful boundaries, not after every styling adjustment. Functional
removal or backend dependency is escalated before implementation. No new package
is created or published without the coordinator's separate authorization.
