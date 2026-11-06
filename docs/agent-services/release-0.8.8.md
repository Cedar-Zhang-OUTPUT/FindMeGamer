# FMG CLI & Skills 0.8.8 — Creator Profile metrics

Creator research now collects the three facts used by the Feishu invitation
table: verified source/active platforms, the main account's follower count, and
the sum of cumulative views across its latest up to 10 content items.

## Behavior

- Five available items means summing those five. The field is never an average,
  median, popular-content total, or extrapolation to ten items.
- Select by publication time, deduplicate content IDs, and preserve individual
  counts and the actual sample size. A short page is not a complete short sample
  when pagination still contains relevant items. Missing view counts stay
  unknown; do not turn incomplete evidence into a zero or completed total.
- Reuse saved Creator Profiles and raw responses before making additional reads.
  Keep each metric tied to the same main account; do not sum platform audiences
  or mix Twitch VODs, Clips and current live viewers.
- No metric update timestamp is required in the profile or Feishu. The bundled
  follower-check helper now accepts records without `checked_at`, while retaining
  value, platform, source and unavailable-reason checks. Existing valid timestamps
  remain supported. Content publication dates still establish recency.
- Both Skills point to the collection and CRM mapping rules. Agents read the live
  Feishu schema, patch matching rows and verify results. This release does not
  backfill the table, change its fields or establish server synchronization.

The four-platform CLI and both Skills are packaged together as 0.8.8. Server
APIs and mail workers need no deployment or restart. Upgrading does not replay
research, contact enrichment, or sending tasks.

## Upgrade

```sh
fmg upgrade --tag fmg-v0.8.8 --skills
fmg version
fmg update check --refresh
```

Preserve the existing Skill directory with `--skill-dir` when customized.
Re-read both installed `SKILL.md` files, `fmg-research/references/completion.md`
and `fmg-api/references/crm.md` before continuing authorized collection or
maintenance. Existing task IDs, source artifacts and idempotency keys stay valid.

## Validation

Release acceptance covers Skill frontmatter and local links, focused research
completion regression tests (including missing metric timestamps), existing CLI
tests and vet, and the actual downloaded four-platform bundle/installer tests.
The latter verify checksums, versions, Skill installation, and retained
authentication in isolated temporary directories. No live research or mail call
is needed for this release.
