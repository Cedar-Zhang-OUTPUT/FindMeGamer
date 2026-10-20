# FMG CLI / Skills 0.8.1 — No Rest for Thieves

User authorized publication on 2026-10-20. Backend template deployment and
acceptance are recorded in `thieves-template-20261020.md`.

- Both Skills now route No Rest for Thieves (熬夜神偷) to `thieves-outreach` v1,
  mailbox `second`, From `norestforthieves@ontologyplay.com`.
- Exactly four personalization variables: `creator_name`, `channel_name`,
  `reference_work`, `specific_observation`. Observation contains complete
  sentences; approved fixed pitch, Steam URL and Michael signature stay intact.
- Plain text without LIMINAL's images; LIMINAL v7 and generic v5 are unchanged.
- CLI command behavior is unchanged from 0.8.0. This coordinated version packages
  updated guidance. Discover the live mailbox/template before creating drafts.
- Draft creation still requires later recipient/content approval before sending.
  No campaign, enrichment retry, or paid provider call is started by this release.

Upgrade at a safe boundary:

```sh
fmg upgrade --latest --skills
fmg version
fmg auth check
```

Reload both installed Skills and relevant references after upgrade. Do not replay
completed requests. Existing credentials and frozen task identities are retained.

Validation: backend suite 575 passed / 1 skipped before deployed template
cutover; independent template/code and Skill application reviews passed. Package
build, checksums, installation and public download acceptance are recorded after
execution below.

## Local package acceptance

Four macOS/Linux architectures built successfully. Complete Go tests and vet
passed. All four installer/release-bundle tests passed against the actual 0.8.1
archives, including checksums, repeated install, authentication preservation,
Skill version markers and update status. Both Skill validators and whitespace
checks passed. No production restart or provider operation was needed for
packaging.

## Published acceptance

- Published `fmg-v0.8.1` at **2026-10-20 08:01:52 UTC**, source
  `1dff83e276932a2042791fdb47eaa46ef8fc68d1`. Tag matches that commit. Seven assets,
  non-draft internal prerelease, not the repository-wide macOS-app latest.
- All uploaded assets were downloaded again. Six payload SHA256 checks passed
  and the checksum list matched the local candidate. All four installer/bundle
  tests passed again on those downloaded artifacts. Anonymous public checksum
  download also matched the same file.
- Public artifact URLs returned HTTP 200. The current local network's anonymous
  GitHub API returned HTTP 403 with `x-ratelimit-remaining: 0`, so full online
  installer acceptance on that route is **not claimed**. Offline installation
  from the verified downloads passed. No installer code was changed to bypass
  rate limits. Retry online upgrade after the network's GitHub quota recovers.
- Existing unrelated backup and Gemini diagnostic working-tree edits were not
  included in the release. No production restart, email or paid lookup occurred
  during publication.
