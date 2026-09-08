# FindMeGamer desktop

Electron + React + TypeScript client for macOS 14+. This is a new desktop frontend, not the OUTPUT prototype and not a SwiftUI performance patch. The existing `macos/` client, backend and production deployment are untouched.

## Run locally

Requires Node.js 24.14+ and npm. From this directory:

```sh
npm ci
npm run check
npm start
```

`npm run dev` builds and launches the actual Electron client. It does not run a web-only mock, SSR server, Python process or local business database. Vite builds local resources; the desktop serves them from the restricted `fmg://app` protocol.

If the official Electron binary installer cannot reach GitHub while Node is not using your existing terminal proxy, run:

```sh
node --use-env-proxy node_modules/electron/install.js
```

This configures that installer process only. The running app independently uses Electron's system proxy configuration, not assumed shell proxy variables. Never disable TLS validation to make a connection work.

Open Settings and enter the service origin and Workspace Key. HTTPS is required except for exact loopback HTTP development addresses. Connect saves the encrypted key and verifies `/api/v1/session`; only successful authentication opens Library. The old Swift Keychain item is not automatically imported. Never paste production credentials into commands, tests, logs or chat.

## Delivered scope

- Four stable navigation entries: Match, Outreach, Library and Settings.
- Shared Collection settings: explicit YouTube/X policy changes with coworker-impact confirmation, separate credentials/availability states, and readback after uncertain saves. Twitch/Instagram remain unavailable. Match preserves source outcomes and candidates; re-enabling saves policy only, with a separate explicit Continue action. The Collection detour retains Match conditions and blocks workspace replacement until return.
- Match v2 source implementation: Activity/Game/reference selection, explicit server discovery planning, retained paginated candidates, stop/continue and history, explicit frozen-candidate evaluation and grouped Match Briefs. Detail/evidence and usage are disclosed on demand. Source verification passed; packaged real-backend acceptance is pending manual macOS Keychain authorization (see the Match unit record).
- Responsive PRD-inspired warm surface, coral actions, deep-blue sidebar and local pixel-art backgrounds. FindMeGamer remains the product name; native macOS titlebar controls are not painted into the page.
- Editable Creator and Game v2 Library, explicit search, independent tab state and saved filters. Both use offset pagination; Creator filters include platform, language and favorites.
- Games: manual creation with a name or website, grouped field editing, reference works, saved state, source/manual comparison and explicit source restoration. No Steam ID or analysis is required.
- Creator profile, multiple email contacts and paginated known works have dedicated reading/editing states. Identity and source details are available through named disclosures; missing counts remain unknown. Identity correction requires explicit old/new confirmation and keeps previous-identity contacts and works read-only.
- Game drafts survive local failures; revision conflicts require explicit per-field choices. Unknown creation results retain the frozen request/idempotency key, and successful creation is followed by a current-detail read.
- Service origin and OS-encrypted Workspace Key configuration, explicit authentication feedback, disconnect and connection-generation isolation.
- Full Settings: local system/light/dark appearance and five text sizes, workspace connection, shared service credentials/probes, two auto-refresh intervals and actual schedule disclosure, shared SMTP configuration/tests, local software update checks with manual GitHub downloads. Categories preserve drafts; shared operations require confirmation and block connection changes while pending.

Outreach is explicitly **Not connected yet**. No campaign send, persisted roster selection or Steam/Analyze Request UI is exposed. Match requires the separately accepted v2 discovery/evaluation backend; the older Library/Settings fixture does not implement it. Match exposes YouTube and X for one run, with Twitch/Instagram visibly unavailable. Settings can send one SMTP test email only after explicit recipient confirmation. Steam credentials can be saved but testing is unavailable in the accepted backend; X credential testing checks usage access only, not recent search, balance or analysis.

## Exact existing API

All business requests originate in main and include `Authorization: Bearer …`. The key is never returned through preload. Creator/Game writes and Settings operations use narrow validated methods. Routes were checked against the delivered backend contract, not guessed from the prototype.

| Purpose | Route / fields |
| --- | --- |
| Verify connection | `GET /api/v1/session` → `workspace_name`, `api_version`, `service_connections` |
| Creators | `GET/POST /api/v2/library/creators`; POST requires `Idempotency-Key` |
| Creator detail/edit | `GET/PATCH /api/v2/library/creators/{uuid}`; PATCH requires `expected_revision` |
| Creator list query / page | `query`, `platform`, `language`, `only_collection`, `offset`, `limit`; `{ items, total, limit, offset }` |
| Email contacts | `POST /api/v2/library/creators/{uuid}/contacts`, `PATCH .../contacts/{contact_uuid}`; parent `expected_revision` and POST idempotency key |
| Known works | `GET/POST /api/v2/library/creators/{uuid}/works`, `PATCH .../works/{work_uuid}`; POST identity revision/key, PATCH work revision |
| Identity correction | `PUT /api/v2/library/creators/{uuid}/identity`; explicit `confirmed:true` and Creator `expected_revision` |
| Match activities | `GET/POST /api/v2/activities`, `GET /api/v2/activities/{uuid}`; POST freezes Game/reference context and requires `Idempotency-Key` |
| Discovery planning | `GET/POST /api/v2/activities/{uuid}/discovery-plans`, `GET /api/v2/discovery/plans/{uuid}`, bodyless `POST .../plans/{uuid}/retry` |
| Discovery tasks / candidates | `GET /api/v2/discovery/queries/{uuid}`, `GET .../queries/{uuid}/results`, bodyless `POST .../stop`, `POST .../continue` |
| Explicit evaluation / briefs | `GET/POST .../queries/{uuid}/evaluations`, `GET .../evaluations/{uuid}`, `GET .../evaluations/{uuid}/results`, `POST .../evaluations/{uuid}/retry`; all POSTs require an idempotency key |
| Games | `GET /api/v2/library/games`, `GET /api/v2/library/games/{uuid}` |
| Game list query / page | `query`, `only_collection`, `offset`, `limit`; `{ items, total, limit, offset }` |
| Create game | `POST /api/v2/library/games` with `Idempotency-Key` |
| Edit game | `PATCH /api/v2/library/games/{uuid}` with `expected_revision` |
| Service credentials | `GET/PUT/POST /api/v1/settings/connections/{service}`; PUT secret is write-only; POST tests stored credentials |
| Shared collection policy | `GET /api/v1/settings/collection`, `PUT /api/v1/settings/collection/{platform}` with exact `{enabled:boolean}`; four-platform response, no automatic collection |
| Refresh intervals | `GET/PATCH /api/v1/settings/reanalysis`; Game 1–90 days, Creator 1–30 days, both fields saved together |
| Refresh activity | Existing v1 profile lists (Steam-linked games / YouTube creators), expansion-only bounded pages; actual last/next analysis timestamps |
| Shared SMTP | `GET/PUT /api/v1/outreach/smtp`; optional write-only password replacement |
| SMTP tests | `POST /api/v1/outreach/smtp/test-connection`, `POST /api/v1/outreach/smtp/test-email` with explicit `recipient` |

Changing search or filters resets that tab's pagination; switching type restores each tab's independent query and page. The backend owns ordering; the client does not claim unsupported sorting. Analysis dates are not general edit timestamps.

Manual games without Steam sources are now visible through v2. Ordinary website/Steam field edits do not rebind the immutable acquisition identity or start an analysis. PATCH sends only changed fields; `null`/`[]` are explicit clears, while `reset_fields` removes manual overrides. Reference replacement preserves returned UUIDs and displays the backend's deduplication result.

Unknown POST results must not start a fresh creation. Retry the frozen request only within the 24-hour backend idempotency window; a later rejection does not prove the original attempt failed. After a workspace change, verify the original workspace rather than replaying into another one. The editor does not persist private drafts across a process crash: normal close/reload has an unsaved-work confirmation, and an explicitly discarded unresolved save may still complete on the server.

Authentication failures expose **Repair connection** next to the affected task. Same-origin repair retains the draft and expected revision while locking the service address and disconnect action. Saving replacement credentials makes any prior unknown POST non-replayable: the backend scopes idempotency by workspace-key digest, not merely service origin. **Check Library** uses bounded canonical queries and pagination; a user explicitly selects **Use this record** before loading current detail. Testing the unchanged saved connection does not mark the credentials replaced. If no matching record can be confirmed, the client does not invent a safe new POST.

Task guidance lives in controls: new references expand and focus their name field, conflicts use explicit **Use latest / Keep mine** choices, and diagnostics live under **Connection details**. Repeated empty-state, loading and idle-state instructions are omitted; source-binding, destructive-action and uncertain-save consequences stay visible when relevant.

## Desktop boundary

- Main: authenticated network, encrypted credential file, system proxy, restricted external HTTPS links.
- Preload: typed `connection`, `library`, `creators`, `games`, `match`, `settings`, `preferences`, `updates`, and `openExternal` business methods. No generic fetch, IPC channel, Node, filesystem or shell access.
- Renderer: sandboxed, context-isolated, Node disabled, restrictive CSP and navigation/window-creation policy. IPC checks the exact app main frame, excluding child/preview frames.
- Credentials: `safeStorage` async OS encryption; atomic mode-0600 encrypted file under `FindMeGamerDesktop` user data. Encryption unavailable means save fails, not plaintext fallback. Changing service origins requires a newly entered key.
- Requests omit cookies, reject redirects, retain TLS verification, use bounded responses and timeout. Creator/Game writes have strict method/path/body validation and no automatic retry. Error output never echoes raw proxy/service responses which could include credentials.
- Settings project known public response fields only; credentials/passwords never return to the renderer or local preferences. Failed shared writes require read-only reconciliation before dependent tests. Unknown SMTP delivery is never automatically retried. Saving SMTP never sends a message.
- Local preferences store only appearance/update preferences and verified update metadata. Software checks use a separate system-proxy-aware ephemeral session with no workspace headers, fixed HTTPS feed, strict GitHub repository/tag verification, 32 KiB response bound and 24-hour automatic-check cooldown. No installer or auto-download is included.
- Future email preview primitive: sandboxed iframe with no scripts, forms, external requests or business IPC. It is not an implemented email workflow.

Electron's [security guidance](https://www.electronjs.org/docs/latest/tutorial/security), [safeStorage API](https://www.electronjs.org/docs/latest/api/safe-storage) and [system-proxy-aware net API](https://www.electronjs.org/docs/latest/api/net) inform these boundaries. Keychain authorization can still be requested by macOS, especially across unsigned development builds; do not automatically approve it on the user's behalf.

## Verification commands

```sh
npm run typecheck
npm test
npm run build
npm run test:desktop
```

Unit tests use explicit fixtures. The Electron integration test starts a temporary loopback HTTP fixture, uses only its synthetic key, exercises the real main/preload/network/renderer path, and closes its own app/server afterward. It is **not a cloud-data acceptance test**. Playwright artifacts belong in ignored `output/playwright/`; production credentials must never enter traces.

`npm run bundle:dir` makes an architecture-local `.app` under ignored `artifacts/` for packaged resource-path checks. It neither creates nor publishes a DMG. Both Intel and Apple Silicon internal DMGs/manual update support remain the distribution direction; this first unit does not claim dual-architecture acceptance or release readiness.

The local bundle contains only `package.json` and compiled `out/` runtime resources, with source maps excluded. Its existing application icon is embedded. The script re-seals and verifies it with an ad-hoc signature; this is **not Developer ID signing or notarization**, and downloaded/quarantined Gatekeeper distribution has not been accepted. It will not overwrite an existing bundle. When downloading Electron needs the existing terminal proxy, build first and run `node --use-env-proxy scripts/package.mjs`.

Optional real-desktop acceptance (no credential is printed; the isolated fixture file must be mode 0600):

```sh
FMG_BACKEND_FIXTURE_FILE=/absolute/path/to/authorized/client.json npx playwright test e2e/backend.spec.ts
FMG_BACKEND_FIXTURE_FILE=/absolute/path/to/authorized/client.json npx playwright test e2e/games.spec.ts
FMG_BACKEND_FIXTURE_FILE=/absolute/path/to/authorized/client.json npx playwright test e2e/creators.spec.ts
FMG_VERIFY_SYSTEM_HTTPS=1 npx playwright test e2e/network.spec.ts
FMG_BACKEND_FIXTURE_FILE=/absolute/path/to/authorized/client.json FMG_SETTINGS_CAPTURE_DIR=/absolute/path/to/isolated/capture npx playwright test e2e/settings.spec.ts
```

The separate collection policy HTTP check is `FMG_COLLECTION_FIXTURE_FILE=/absolute/path/to/authorized/client.json npx playwright test e2e/collection-http.spec.ts`. It requires exclusive access to the coordinator-owned `b2b15f4` / migration `0014` fixture, changes and restores one synthetic shared flag, verifies retained Match state and zero provider/model events, and launches no Electron process. See [collection-switches-unit.md](docs/collection-switches-unit.md). This is not packaged GUI acceptance. The original `cad5565` Match fixture has no collection endpoint and must not be used to validate this newer source's collection-dependent flow.

Set `FMG_PACKAGED_EXECUTABLE` to the full `FindMeGamer.app/Contents/MacOS/FindMeGamer` path to repeat these checks against the packaged app. The network check makes one anonymous request to the approved service's public health endpoint, keeps TLS validation enabled, removes shell proxy variables from Electron, and expects a machine with its macOS system proxy enabled. It is opt-in and is not a production-authentication test.

The read-only first unit, Game v2, full Settings and Creator v2 migration have separate verification records. Settings tests use unchanged accepted backend code, strict HTTPX provider fixtures and an SMTP capture gateway; they do not establish real provider access or an actual TLS handshake. Test bootstrap/compose helpers under `e2e/fixtures/settings/` are excluded from production packaging.

See [first-unit.md](docs/first-unit.md), [game-v2-unit.md](docs/game-v2-unit.md), [settings-unit.md](docs/settings-unit.md), [creator-v2-unit.md](docs/creator-v2-unit.md), [match-v2-unit.md](docs/match-v2-unit.md) and [ui-information-pass.md](docs/ui-information-pass.md) for state design, verification results and outstanding limits. Opt-in Creator/Game/Settings tests mutate only the coordinator-owned isolated API. Settings SMTP capture is not external mail delivery. Match E2E additionally requires `FMG_MATCH_FIXTURE_FILE` and exclusive access to its separate pinned fixture controls; see its unit record before running.
