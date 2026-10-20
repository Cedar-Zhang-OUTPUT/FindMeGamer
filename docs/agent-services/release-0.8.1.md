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
