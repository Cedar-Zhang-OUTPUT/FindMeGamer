# Focus Workspace

## Intent and scope

Make the current task legible before asking the user to configure anything. A calm native macOS workspace, not a dashboard of equally weighted cards. Existing backend contracts, ordering, contact validation, and send safeguards remain authoritative. The interface stays English. This iteration changes presentation, not real provider setup or deployment.

## Primary journey

Choose an analyzed game → request a match → review recommended creators → choose recipients → write a message → review resolved emails → confirm send → follow deliveries and replies.

Library supports finding, understanding, favoriting, and analyzing profiles. Settings supports one configuration task at a time. Neither is a mandatory extra step for an already prepared match.

## State map

| State | Main focus / primary action | Supporting information | Disclosure trigger |
| --- | --- | --- | --- |
| Library | Search and profiles / open profile | Type, favorites, analysis entry | Open profile or Analyze Profile |
| Empty library | Start or recover / analyze, clear search, or show all | Explain whether empty is caused by filtering | Current search and favorite context |
| Analyze request | Source URL / analyze | Source type and accepted URL format | User requests analysis |
| Analysis activity | Submitted job / open result or retry | Input remains available, older jobs quiet | Successful submission or Activity tab |
| New match | Game selection / find creators | Compact recent matches | User selects game |
| Matching | Selected task and honest status | Previous game, recent tasks | Request accepted; no automatic navigation on completion |
| Match ready | Creator review / compose for selection | Compact game context, first rationale | Other matches and evidence expand on demand |
| Compose | Recipients → message → review | Identity and current step | Explicit next/back, actual preview availability |
| Campaign | Delivery/reply outcome / inspect campaign | Secondary metrics and history | Select campaign or expand detail |
| Profile | Identity and decision summary | Dates, favorite, reanalysis | Overview / evidence / creator contacts |
| Settings | Chosen category / relevant save action | Stable category selector | Appearance / connections / automation / workspace |

## Information hierarchy

- Default: task heading, current object, minimum actionable content, one primary next action.
- Nearby secondary: short status, counts, provenance summary, back/cancel, current game and recipients.
- On demand: full evidence, alternate matches, completed jobs, template metadata and response labels, delivery details.
- Advanced: named settings categories and individual provider configuration. Errors or important consequences never depend on opening an advanced section.
- Global: a stable native sidebar; a compact visible demo/offline indicator. No decorative progress line or ambient animated background.

## Transition rules

- Explicit user actions may move visual focus; background changes update the current object without stealing keyboard focus, scrolling, or selecting another page.
- Submitting analysis retains the source text. Validation errors stay next to the input. Accepted requests reveal activity with an explicit return to the input.
- A selected match stays selected while its status changes. Completion invites result review rather than navigating automatically.
- Game context is compact on results; chosen creators remain visible through the selection summary.
- Composer back preserves drafts and explicit email choices. Changing recipients or content requires a matching server preview before sending.
- Template content remains in one editor through width changes. Low-frequency fields are discoverable but do not displace the message body.
- Native sidebar and inspector own their space. Child workspaces adapt to the actual detail width; nested split views must not enforce overflowing minimum widths.
- Motion is short and localized; reduced-motion preference uses a fade or no movement. No automatic staggered entrances.

## Failure and return paths

- Initial loading reserves the content area; existing content stays available during refresh where models permit.
- Library errors retry the failed page, retaining loaded content. Empty search clears only the query; empty favorites offers all profiles.
- Analysis validation preserves the URL; existing profile provides open/reanalyze; failed jobs retain a local retry when supported.
- Match failures show the safe public cause and allowed retry. Background jobs continue when leaving; no unsupported cancel action is invented.
- Composer template load can retry; ambiguous email addresses must be resolved explicitly; send remains disabled until the exact draft/recipient preview matches. Confirmation explains external sending.
- Settings errors remain in the relevant category. Draft state belongs to the long-lived model or parent, not transient disclosure content.
- Canceling a composer closes that composition; back within the journey preserves edits. Destructive actions retain their confirmations.

## Assumptions / limits

The existing business workflow is retained. Demo uses local fixtures and never sends real mail. There is no fabricated progress percentage, cancellation API, or live-provider claim. Runtime UI walkthrough and regression results will be recorded after implementation; native accessibility, reduced motion, and macOS version coverage must be distinguished from checks performed only in tests.
