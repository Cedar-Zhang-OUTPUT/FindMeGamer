# FMG CLI & Skills 0.8.7 — Agent-maintained business CRM

The invitation/reply CRM now uses one business row per creator and game. This
release distributes the current Feishu table coordinates and maintenance rules
with both Skills, replacing the retired multi-table maintenance model.

## Behavior

- People view progress, filter records, read dashboards and provide business
  decisions. Agents read the source mail, update the matching row through Feishu
  CLI, then verify the changes. Routine manual data entry is not the handoff.
- This is a collaboration rule, not a new human read-only permission. The Base
  has no server synchronization, and a table status cannot send an email or
  change an FMG task, transport receipt, hold or permission.
- The two external Agents retain their game assignments: LIMINAL and No Rest.
  Read requests may overlap; writes to the same row require coordination. No
  cross-Agent lock or automatic deduplication service is implied.
- Keep stable business IDs, source reply/task/send IDs, original messages,
  contact restrictions, actual dates, and unknown transport results. Patch only
  changed fields after reading current values. Reconcile interrupted writes by
  the original record/business ID instead of creating duplicate rows.
- Reply-rate formulas remain automatic. Count one creator × game once;
  bounce/automatic mail is not a human reply and transport acceptance does not
  prove inbox delivery. Unreviewed intent stays unreviewed.
- Both Skill entrypoints route to `fmg-api/references/crm.md`. Old business Bases
  remain references; the retired contact/send/event technical tables are not
  rebuilt or maintained.

The four-platform CLI is rebuilt as 0.8.7 with the matching Skill bundle. Command
behavior and server APIs are unchanged; no backend deployment, worker restart,
schema migration, mail send, paid lookup or task restart is needed for this
release.

## External Agent handoff

At a safe boundary after the current request finishes:

```sh
fmg upgrade --tag fmg-v0.8.7 --skills
fmg version
fmg update check --refresh
```

Use `--skill-dir` for the Agent's existing non-default Skill directory. Preserve
authentication, running server tasks, task IDs, mail cursors, saved receipts and
idempotency keys. Actually re-read both installed `SKILL.md` files and
`fmg-api/references/crm.md`; installation alone does not reload the model context.
Read-check the current Feishu schema and one row for the assigned game before
continuing already-authorized maintenance. Report the CLI/Skill versions, loaded
guide and assigned game. Publishing does not itself upgrade an external Agent.

## Release acceptance

Candidate validation passed: Go tests and vet, both Skill validators, four
installer/bundle tests, archive-to-source checks for both Skill entrypoints and
the CRM guide, and read-only verification of all 28 fields and both game views
against the current Feishu table. No mail or metered provider call was made.

Before publication, run the Go test suite and vet, validate both Skills, build
all four CLI platform archives, and run the actual bundle/installer tests in
isolated directories. Verify that the installed CRM guide and both entrypoints
match the source files. Upload a draft, download all seven assets, compare
checksums and repeat downloaded-bundle installation acceptance before publishing
on the existing FMG prerelease channel. Preserve the desktop app's separate
latest-release selection.
