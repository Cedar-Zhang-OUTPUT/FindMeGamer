# Client 0.1.3: work duration and update discovery

## Delivery boundaries

The installed 0.1.2 client cannot acquire new UI through a server update. Users must manually install 0.1.3 once to gain the update checker. There is no silent download, installer, application replacement, or privilege escalation.

The client patch starts from `371a434` (interaction-first UI). The 0.1.2 tag is `v0.1.2-internal.1` / `888f1f2`; its analysis job model and original elapsed-time row are identical to that baseline. This patch requires no new API fields. Release integration must preserve the already repaired production backend, using the current deployment branch rather than deploying this older frontend branch's backend tree.

The release owner coordinates `APP_VERSION=0.1.3`, tag `v0.1.3-internal.1`, and a new `FindMeGamer-0.1.3.dmg` plus checksum. Existing 0.1.2 artifacts are not silently replaced. The release remains an internal, ad-hoc-signed Universal build for macOS 14+, not a Developer ID notarized build.

## Analysis Activity duration

The previous `Text(createdAt, style: .relative)` displayed age since submission forever, including after completion. It is replaced by an explicit time presentation:

| Snapshot | Display | Clock source |
| --- | --- | --- |
| Queued | Waiting | No work timer. |
| Running, valid start, no completion | Working for … | Current time minus `startedAt`; ticks locally once per second. |
| Succeeded / failed / superseded, valid start and end | Worked for … | Fixed `completedAt - startedAt`. |
| Running snapshot already has completion | Worked for … | Completion caps elapsed time even if status is stale. |
| Missing, non-finite, or reversed work timestamps | Working for — / Worked for — | No invented duration; terminal rows never keep ticking. |

`createdAt` remains available as an absolute Submitted tooltip. Queue time is excluded. `updatedAt` is a change-feed watermark, not a trustworthy substitute for completion. Failed jobs may legitimately never have started. The current analysis contract has no cancelled status; all terminal statuses available to this client are explicitly handled.

Only running rows with a valid start create a `TimelineView`. Terminal rows are static text. Seconds are visible, with minutes/hours/days as needed; small clock skew clamps live negative elapsed time to zero. Invalid terminal timestamps are unavailable, not silently corrected.

## Update-source contract

GitHub's private repository is not anonymously readable, and `/releases/latest` excludes internal prereleases. Neither endpoint is used as the machine-readable version source. No GitHub token or Workspace Key is sent for update checks.

The publisher exposes only non-sensitive version metadata at this fixed HTTPS URL:

`https://44.233.174.193/updates/macos.json`

```json
{
  "schema_version": 1,
  "version": "0.1.3",
  "release_page_url": "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3-internal.1"
}
```

This feed represents the internal client channel. `version` is the numeric application version, independent of GitHub's prerelease flag. A release page is accepted only for the fixed official repository and a matching release tag. Checking a version does not download or execute code.

The app checks on launch and activation, at most once per 24 hours automatically, including after an unsuccessful attempt. A manual Check for Updates bypasses that interval. Automatic checking is optional. Errors are shown in Software Update without interrupting the current task; a failed recheck does not erase an already verified Update link. Missing development-build version metadata is not interpreted as version zero or as up to date.

Software Update is available from the application menu and Settings. A quiet sidebar Update entry appears only when a newer version has been verified. The update window names the installed and available versions and makes GitHub access/manual installation explicit.

The manifest reveals no source code, credentials, business data, or installation asset. Clicking Update opens the official private GitHub release page, where the user needs repository access. The server publishes this manifest only after the referenced release and DMG asset are available, and serves it without caching. Publication is a narrowly scoped static Caddy route and graceful reload, not an API/Worker/database deployment.

## Validation

- Timer policy: 10 tests cover every terminal status, queue isolation, advancing running time, late start metadata, frozen completion, missing and invalid endpoints, skew, formatting, and overflow safety. Independent read-only review found no blocking issue.
- Native Demo: an already completed Activity entry displays `Worked for 0s` (the fixture has identical start/end timestamps); reading it again later shows the same value. This is a fixture check, not a claimed real zero-second analysis.
- Full strict run: `swift test --package-path macos -Xswiftc -warnings-as-errors` reports 312 tests in 41 suites passed; the opt-in live-source test is skipped until publication. Update tests cover version ordering, malformed data and URLs, anonymous transport, redirects, streaming limits, cache and failure states, daily/manual scheduling, concurrent requests, and cancellation recovery.
- Native update UI: application-menu Check for Updates opens Software Update; Settings → Software Update is also accessible. The unversioned development Demo correctly shows Development build rather than claiming it is current.
- After publishing the 0.1.3 DMG and manifest, run `FMG_VERIFY_LIVE_UPDATE=1 swift test --package-path macos -Xswiftc -warnings-as-errors --filter liveApprovedManifestOffers013To012AndKeeps013Current`. This opt-in test uses the actual anonymous HTTPS transport and checks that 0.1.2 is offered 0.1.3 and 0.1.3 is current. Do not point production users to an unverified or unpublished update.
- Final release and live-manifest results are recorded in the release handoff after publication. No real analysis or email is triggered to test this client feature. Live running-job transitions, VoiceOver announcements, and a separate Intel Mac still require environment-specific validation; unit checks and a Universal build do not establish those behaviors.
