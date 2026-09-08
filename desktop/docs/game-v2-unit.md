# Game v2 · task and acceptance plan

Base: desktop-only first unit `b7057bc`. Authority: coordinator's separate Game v2 unit; backend contract is accepted `dd4b15d`, documented in `docs/backend-v2-library-games.md` and OpenAPI in the original workspace. Only `desktop/` is editable here. Actual writes use the coordinator-owned isolated API on 18090, never production or an existing user's Library.

## Task path and information hierarchy

Games → find or add a game → review/edit identity, description and references → save → continue viewing or return to the same Library context. A name or valid website is enough for creation; no Steam ID or analysis is required.

| State | Primary focus / action | Secondary disclosure | Transition and retained context |
| --- | --- | --- | --- |
| List / empty | Search, saved filter, New game | Count / previous and next page | Creator and Game queries remain independent |
| Loading / failure | Reserved list or local error / retry | Current query/filter | Failed page changes retain the last successful page |
| Detail | Game identity / Edit | References, source identity and manual/source provenance | Back restores list context |
| New or editing | Identity, description / Save | Other fields and reference editor | Input survives expand/collapse and local errors |
| Saving | Save status | Draft and origin remain visible | No concurrent edit silently lost |
| Save failed | Related error / retry | Full draft | No navigation or field clearing |
| Create outcome unknown | Frozen attempted creation / retry same request | Full attempted input | Same payload uses same idempotency key; no silent duplicate creation |
| Authentication repair | Workspace key / Connect | Retained draft and connection diagnostics | Same origin is locked; unchanged test preserves context; credential replacement forbids replay of an uncertain POST |
| Revision conflict | Latest values versus local edits / resolve | Original values and revision | No automatic last-write-wins; untouched remote fields remain intact |
| Source restore | Selected field / use source | Source value and existing override | Explicit reset_fields, never simultaneous set/reset |
| Leave unsaved | Continue editing / save / discard | Original destination retained | Save failure stays in editor |
| Saved | Returned authoritative detail | Actual deduplicated references | List/detail synchronize without a second submit |

Navigation and task labels stay stable. Low-frequency metadata belongs in labeled disclosure, not explanatory paragraphs. Errors and source-identity limitations remain explicit where decisions occur. Reference removal affects only the game's references, not a Library game. The editor must not suggest per-activity selection or downstream draft synchronization that this contract does not implement.

## Contract and security constraints

- v2 lists use offset/limit/total, not v1 cursors. Creator v1 remains read-only and must retain previous behavior.
- Main owns Bearer authentication and validates the narrow games list/detail/create/update IPC. Renderer gets no generic HTTP or credentials API.
- POST requires a new idempotency key per logical creation, reused for the exact frozen payload on retry. Replay returns a creation snapshot; reload detail for current state.
- PATCH includes expected_revision. Omitted fields are unchanged, null clears scalars, empty arrays clear lists. Preserve reference UUIDs; show the backend's deduplication result.
- Source identity is not editable. Ordinary website/Steam business edits do not rebind acquisition history. A manual unbound game remains usable without Steam.
- No automatic analysis, Creator edits, Match execution, mail/template operations, backend changes or full Settings expansion.

## Verification plan

Write failing adapter, transport and renderer regressions before implementation. Independently review the bounded change. Verify actual packaged app → isolated API → persistent database behavior for creation without Steam, read-after-create, revision edit/clear, references, favorite, conflict, retry and returning to a preserved draft. Keep fixture credentials out of code/logs/traces/screenshots. Retest existing Creator reads, connection isolation, keyboard/narrow layout and credential boundaries. Final results and limitations are recorded at closure, not inferred from mocks.

## Implemented clarity pass

- Removed duplicate page eyebrows (including disconnected and unavailable states), decorative “WORKSPACE / 01”, empty-reference/empty-Library explanations, idle “No changes”, and a loading paragraph that incorrectly remained visible after failure.
- Kept one local loading status and direct recovery controls. Added a **Repair connection** action beside an authenticated task failure; no reliance on reading navigation instructions.
- Adding a reference opens its editor and focuses its name. Collapse/reopen preserves edits.
- Conflict radio choices are verbs (**Use latest / Keep mine**); only cause and necessary consequences remain prose.
- Connection routing is inside **Connection details**. Profile source records and Game provenance remain on demand. Existing Creator content, contact provenance, visible labels and accessibility descriptions were not removed merely to reduce word count.
- This is the new Electron unit. Old Swift pages, unavailable Match/Outreach business flows and the full Settings migration are not claimed as redesigned or integrated here.

## Verification results · 2026-09-08

- `npm run check`: 9 suites, **213 tests passed**, TypeScript and production build passed. Includes first-rejection vs uncertain-retry classification, key replacement/unchanged testing/failed repair, stale Settings URL, canonical long-URL lookup with pagination, 24-hour dispatch guard, all source/reset/clear/reference cases, navigation and credential boundaries.
- Live development Electron → isolated 18090 API → database: Game flow passed. A real 201 is replaced by a test-relay 502 after commit, retry reuses identical body/key, and query proves one stored record. A second editor creates a real 409; selected local values and untouched remote values both survive resolution.
- Separate recovery flow: committed 201 → lost response → pre-forwarded 401 → same-origin key re-entry → retained editor → disabled POST replay → paged GET lookup → explicit existing record → current detail. Exactly one recovery record and **zero POSTs after credential repair**.
- Local arm64 `.app`: ad-hoc `codesign --verify --deep --strict` passed; ASAR includes only package metadata and compiled runtime, no source maps. Bundled icon SHA-256 exactly matches `build/AppIcon.icns` (the packager retains filename `electron.icns`). No Developer ID identity, notarization or DMG was used.
- Packaged suite: **4/4 passed**: real isolated Creator/Game read path, Game persistence/recovery, anonymous system-proxy HTTPS with shell proxy variables removed, and synthetic HTTP/credential/iframe/navigation isolation. All four honor the explicit packaged executable path.
- Visual evidence inspected at 1320×920 (detail) and 760×900 (editor), plus 760×660 Library coverage. No horizontal overflow. Game runtime reports zero unexpected console warnings/errors or page errors; page URL/title and absence of framework overlays verified. Reduced-motion mode exercised.
- Independent bounded review: GO, no outstanding Critical/Important findings. Recovery edge cases found in review were reproduced with failing tests before fixes.

Browser plugin/skill is not available in this session; the repository’s Playwright Electron integration is used. Native Computer Use identifies/restarts the exact built app only. Screenshot evidence contains disposable fixture records, not user data or credentials: `/tmp/fmg-game-v2-wide-detail.png`, `/tmp/fmg-game-v2-narrow-editor.png`, `/tmp/fmg-library-narrow.png`.

### Explicit limitations

Private drafts are memory-only, so unexpected process death loses them. Native close/reload warns; closing does not cancel a server-side request. An unconfirmed creation with no identifiable Library match remains unresolved rather than allowing a potentially duplicating new POST. No stable server idempotency-domain identifier is exposed; the frontend cannot detect an out-of-band workspace-key hash rotation on its own.

macOS 14 hardware, Intel builds, full VoiceOver auditing, downloaded/quarantined Gatekeeper distribution and real production credentials/provider operations are unverified. The on-device arm64 package is a local demo, not a distribution release. API fixtures are preserved, not reset; disposable test records remain in the isolated DB because no delete route belongs to this contract. No backend/schema/contract or deployment files were changed.
