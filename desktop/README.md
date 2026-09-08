# FindMeGamer desktop · first rebuild unit

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
- Existing Library creator/game lists and unified read-only details, explicit search submission, independent tab state, favorites filter and cursor pagination.
- Complete public detail data and contact purposes/sources remain available; missing counts remain unknown. Returning from details preserves the list. Failed loading and retry do not masquerade as empty success.
- Service origin and OS-encrypted Workspace Key configuration, explicit authentication feedback, disconnect and connection-generation isolation.

Match and Outreach are explicitly **Not connected yet**. The frontend exposes no analysis, matching, edits, send or paid-platform methods. Instagram is an unconnected platform placeholder. Existing v1 Library creators are YouTube profiles; this is not evidence of Twitch/X/Instagram discovery integration.

## Exact existing API

All business requests originate in main, are GET-only, and include `Authorization: Bearer …`. The key is never returned through preload. Routes were checked against `backend/openapi.json` and the existing backend handlers, not guessed from the prototype.

| Purpose | Route / fields |
| --- | --- |
| Verify connection | `GET /api/v1/session` → `workspace_name`, `api_version`, `service_connections` |
| Games | `GET /api/v1/profiles/games` |
| Creators | `GET /api/v1/profiles/creators` |
| Detail | `GET /api/v1/profiles/{games\|creators}/{uuid}` |
| List query | `query`, `only_collection`, `cursor`, `limit` (1–100, default 50) |
| Page | `{ items, next_cursor }`; no invented total/offset/has-more |

Changing search or favorites resets that tab's cursor; switching type restores each tab's independent query and pagination. The backend orders by its existing name/id cursor contract; the client does not claim unsupported full-library sorting or platform filters. `updatedAt` in the view model is the API's `last_analyzed_at`, and the UI labels it as analysis time.

The announced v2 `/api/v2/library/games` contract is a follow-on dependency, not used by this unit. Hand-authored games with no Steam source will not appear in v1. Editing, references and manual/source overrides must use the delivered v2 contract later; no v1 writes are invented here.

## Desktop boundary

- Main: authenticated network, encrypted credential file, system proxy, restricted external HTTPS links.
- Preload: `connection.status/save/test/clear`, `library.list/detail`, `openExternal`. No generic fetch, IPC channel, Node, filesystem or shell access.
- Renderer: sandboxed, context-isolated, Node disabled, restrictive CSP and navigation/window-creation policy. IPC checks the exact app main frame, excluding child/preview frames.
- Credentials: `safeStorage` async OS encryption; atomic mode-0600 encrypted file under `FindMeGamerDesktop` user data. Encryption unavailable means save fails, not plaintext fallback. Changing service origins requires a newly entered key.
- Read requests omit cookies, reject redirects, retain TLS verification, use bounded responses and timeout. Error output never echoes raw proxy/service responses which could include credentials.
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
FMG_VERIFY_SYSTEM_HTTPS=1 npx playwright test e2e/network.spec.ts
```

Set `FMG_PACKAGED_EXECUTABLE` to the full `FindMeGamer.app/Contents/MacOS/FindMeGamer` path to repeat these checks against the packaged app. The network check makes one anonymous request to the approved service's public health endpoint, keeps TLS validation enabled, removes shell proxy variables from Electron, and expects a machine with its macOS system proxy enabled. It is opt-in and is not a production-authentication test.

The accepted first-unit sequence is followed by a separate Game v2 unit, then the coordinated full Settings migration. Settings is **not being reduced permanently to connection fields**; its migration scope is recorded in the delivery document below.

See [first-unit.md](docs/first-unit.md) for state design, verification results and outstanding limits.
