# Activities loading diagnosis — 2026-09-13

Scope: read-only diagnosis; no runtime changes, online requests, production credentials, POSTs, retries or deployment from this audit. Added an isolated diagnostic test only. This is not evidence that Keychain caused the user's incident.

## Request chain and refresh behavior

`MatchWorkspace.tsx:70–85` invokes `match.activities({limit:50,offset})`; preload `match:activities` → application handler → `MatchClient.activities` → `WorkspaceGateway.matchRequest` → `GET /api/v2/activities?offset=0&limit=50`.

- One GET per page, no per-row detail requests and no list polling.
- Initial active entry, explicit refresh/page/retry and creation completion request the list. Completed lists are retained across navigation.
- Leaving before completion invalidates the old result but does not cancel IPC/HTTP. Returning issues another invoke. The obsolete response cannot replace the current page.
- On the list route, MatchActivity is unmounted: detail hooks are not hidden behind the list.
- AnalyzeProvider may poll already tracked analysis tasks every two seconds (bounded per task); opening the activities list does not itself load analysis history. These requests do not gate the list promise but share credential access.
- Development StrictMode replays initial effects; this is not production double invocation.

## Isolated timing experiment

Command (desktop directory):

```sh
npx vitest run tests/activities-loading-diagnosis.test.tsx
```

Result: **2 passed**, 1.64 seconds, 2026-09-13 14:57:24 local. Real CredentialStore filesystem serialization and WorkspaceGateway/Match transport; synthetic crypto adapter and in-memory fetch Response. Temporary directory contains only a fake key/cipher and is removed afterwards. No real Keychain or network is used.

Synthetic elapsed milliseconds from test start:

| Event | ms |
|---|---:|
| First decrypt starts | 11 |
| First controlled gate released | 123 |
| First fetch | 124 |
| Second decrypt starts | 127 |
| Second controlled gate released | 240 |
| Second fetch | 240 |

The two controlled pauses request 60 ms each; waitFor scheduling and filesystem overhead contribute to the displayed elapsed values. Tests assert causal ordering and dispatch counts, not a machine-dependent latency threshold.

Before releasing the first decrypt gate: zero fetches and zero `AbortSignal.timeout` creations. After first release: one fetch and one timeout. After second release: two fetches and two 20,000 ms timeouts. Thus shared credential queuing/decryption precedes the HTTP timeout. There is no 20-second bound covering the whole renderer loading state. CredentialStore serializes read + storage availability + decrypt for every request (`credential-store.ts:59–71,112–115`); HTTP timeout begins in `match-transport.ts:133`.

Renderer diagnostic: initial pending invoke=1; leave/return while unresolved=2; completed leave/return remains=2; activity detail and plans calls=0. Old result is rejected, current result displayed.

## Online observations supplied by coordinator

Coordinator independently reported three read-only GET totals **0.892 / 0.766 / 0.802 seconds**, server durations **0.289 / 0.186 / 0.194 seconds**, response **3,598 bytes**. This audit did not repeat those requests. Those samples do not establish a multi-second server bottleneck or explain the user's desktop incident.

## Next measurement points

Capture monotonic durations for renderer invoke → main handler entry → getConnection completion → fetch headers → bounded JSON completion → DTO decode completion → renderer commit. If instrumenting CredentialStore in a separate authorized diagnostic run, split queue wait, file read, storage availability and decrypt. Use existing HTTP X-Correlation-ID to join server logs; never log credentials, Authorization or request bodies. A long pre-fetch gap will not appear in server access logs.

## Bounded optimization candidates (not implemented)

1. Deduplicate identical in-flight list reads within the same workspace/credential generation, preserving stale-result fences. Avoid navigation-triggered duplicate reads without introducing global credential caching.
2. Distinguish `Loading activities…` (list) from `Loading activity…` (detail). For the latter, `useMatchSession.ts:59` awaits activity detail and plan history together in Promise.all before committing either. Independent publication can remove that deterministic dependency, but is not a list fix.

No changes to backend, API contracts, credential caching/security policy or production tasks are proposed as part of the selection feature.
