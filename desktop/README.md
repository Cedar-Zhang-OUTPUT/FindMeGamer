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
- Responsive PRD-inspired warm surface, coral actions, deep-blue sidebar and local pixel-art backgrounds. FindMeGamer remains the product name; native macOS titlebar controls are not painted into the page.
- Existing Creator v1 read-only list/detail and editable Game v2 Library, explicit search, independent tab state and saved filters. Creators use cursor pagination; Games use offset pagination.
- Games: manual creation with a name or website, grouped field editing, reference works, saved state, source/manual comparison and explicit source restoration. No Steam ID or analysis is required.
- Complete public Creator detail data and contact purposes/sources remain available; missing counts remain unknown. Returning from details preserves context. Failed loading and retry do not masquerade as empty success.
- Game drafts survive local failures; revision conflicts require explicit per-field choices. Unknown creation results retain the frozen request/idempotency key, and successful creation is followed by a current-detail read.
- Service origin and OS-encrypted Workspace Key configuration, explicit authentication feedback, disconnect and connection-generation isolation.

Match and Outreach are explicitly **Not connected yet**. The frontend exposes no analysis, matching, Creator writes, send or paid-platform methods. Instagram is an unconnected platform placeholder. Existing v1 Library creators are YouTube profiles; this is not evidence of Twitch/X/Instagram discovery integration.

## Exact existing API

All business requests originate in main and include `Authorization: Bearer …`. The key is never returned through preload. Creator/session operations are read-only; only the four specified Game v2 operations support editing. Routes were checked against the delivered backend contract, not guessed from the prototype.

| Purpose | Route / fields |
| --- | --- |
| Verify connection | `GET /api/v1/session` → `workspace_name`, `api_version`, `service_connections` |
| Creators | `GET /api/v1/profiles/creators` |
| Creator detail | `GET /api/v1/profiles/creators/{uuid}` |
| Creator list query / page | `query`, `only_collection`, `cursor`, `limit`; `{ items, next_cursor }` |
| Games | `GET /api/v2/library/games`, `GET /api/v2/library/games/{uuid}` |
| Game list query / page | `query`, `only_collection`, `offset`, `limit`; `{ items, total, limit, offset }` |
| Create game | `POST /api/v2/library/games` with `Idempotency-Key` |
| Edit game | `PATCH /api/v2/library/games/{uuid}` with `expected_revision` |

Changing search or favorites resets that tab's pagination; switching type restores each tab's independent query and page. The backend owns ordering; the client does not claim unsupported sorting or platform filters. Analysis dates are not general edit timestamps.

Manual games without Steam sources are now visible through v2. Ordinary website/Steam field edits do not rebind the immutable acquisition identity or start an analysis. PATCH sends only changed fields; `null`/`[]` are explicit clears, while `reset_fields` removes manual overrides. Reference replacement preserves returned UUIDs and displays the backend's deduplication result.

Unknown POST results must not start a fresh creation. Retry the frozen request only within the 24-hour backend idempotency window; a later rejection does not prove the original attempt failed. After a workspace change, verify the original workspace rather than replaying into another one. The editor does not persist private drafts across a process crash: normal close/reload has an unsaved-work confirmation, and an explicitly discarded unresolved save may still complete on the server.

Authentication failures expose **Repair connection** next to the affected task. Same-origin repair retains the draft and expected revision while locking the service address and disconnect action. Saving replacement credentials makes any prior unknown POST non-replayable: the backend scopes idempotency by workspace-key digest, not merely service origin. **Check Library** uses bounded canonical queries and pagination; a user explicitly selects **Use this record** before loading current detail. Testing the unchanged saved connection does not mark the credentials replaced. If no matching record can be confirmed, the client does not invent a safe new POST.

Task guidance lives in controls: new references expand and focus their name field, conflicts use explicit **Use latest / Keep mine** choices, and diagnostics live under **Connection details**. Repeated empty-state, loading and idle-state instructions are omitted; source-binding, destructive-action and uncertain-save consequences stay visible when relevant.

## Desktop boundary

- Main: authenticated network, encrypted credential file, system proxy, restricted external HTTPS links.
- Preload: `connection.status/save/test/clear`, Creator `library.list/detail`, `games.list/detail/create/update`, `openExternal`. No generic fetch, IPC channel, Node, filesystem or shell access.
- Renderer: sandboxed, context-isolated, Node disabled, restrictive CSP and navigation/window-creation policy. IPC checks the exact app main frame, excluding child/preview frames.
- Credentials: `safeStorage` async OS encryption; atomic mode-0600 encrypted file under `FindMeGamerDesktop` user data. Encryption unavailable means save fails, not plaintext fallback. Changing service origins requires a newly entered key.
- Requests omit cookies, reject redirects, retain TLS verification, use bounded responses and timeout. Game writes have strict method/path/body validation and no automatic retry. Error output never echoes raw proxy/service responses which could include credentials.
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
FMG_VERIFY_SYSTEM_HTTPS=1 npx playwright test e2e/network.spec.ts
```

Set `FMG_PACKAGED_EXECUTABLE` to the full `FindMeGamer.app/Contents/MacOS/FindMeGamer` path to repeat these checks against the packaged app. The network check makes one anonymous request to the approved service's public health endpoint, keeps TLS validation enabled, removes shell proxy variables from Electron, and expects a machine with its macOS system proxy enabled. It is opt-in and is not a production-authentication test.

The read-only first unit and separate Game v2 unit are followed by the coordinated full Settings migration. Settings is **not being reduced permanently to connection fields**; its migration scope is recorded in the first-unit delivery document. Creator v2 editing remains a separate, not-yet-integrated unit.

See [first-unit.md](docs/first-unit.md) and [game-v2-unit.md](docs/game-v2-unit.md) for state design, verification results and outstanding limits. `e2e/games.spec.ts` is explicitly opt-in and writes only disposable records in the coordinator-owned isolated API; it simulates a lost successful response and a second editor to test real persistence/idempotency/conflicts.
