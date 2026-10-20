# No Rest for Thieves footer — template v2

User approved adding the supplied JPEG after Michael / No Rest for Thieves Team,
at the very bottom of the email. No title, pitch, variable or other template
changes. No automatic test email or rewrite of existing frozen previews/tasks.

- Asset: `thieves-banner.jpg`, original 1920×1080 JPEG, 198253 bytes.
- SHA-256: `bf98277e4e89529f67fead5c6e53abaa2c9a467fdda90b9cba5f5d5a4fad264f`.
- Display: width 600px, max-width 100%, height auto (600×337.5 at full width).
- HTML uses CID `thieves-game-banner`; shared SMTP/Graph MIME embeds image/jpeg.
- The image is snapshotted with the draft. No remote image URL or extra logo.
- `thieves-outreach` v2 replaces v1 for newly created drafts only.
- Existing v1 plain-text snapshots and LIMINAL/generic image snapshots still work.
- Batch create/get responses omit the repeated JPEG payload, just as they omit
  existing PNG payloads. Individual previews and stored messages retain the image.

## Clients

The existing CLI supports the dynamic server template; no binary upgrade needed.
Before creating new drafts run `fmg email template thieves-outreach`, use
`--mailbox second --template thieves-outreach --template-version 2`, and retain
the four existing variables. Older bundled Skill references describe v1 without
images; their server-authoritative discovery rule applies. Do not submit stale v1
creation inputs or transfer approval from an old draft to a replacement.

## Validation and safe rollout

New tests were observed failing for missing HTML/footer and missing version
retirement before implementation. Focused template/MIME/Graph tests: 38 passed,
one existing Starlette/AnyIO deprecation warning. An independent read-only reviewer
found no actionable issues in the scoped patch.

Use a derivative of `fmg-agent:thieves-template-20261020`, copying only template
renderer, shared MIME builder, compact batch serializer, Thieves JSON and original JPEG. Apply
`thieves-footer-20261020.yaml` last after all existing production overrides.
Enrichment's diagnostics image and all registry/SMTP/IMAP settings stay untouched.
Hold runtime gates under an exclusive row lock, require no active sends/retries
or pending recipients, warm-stop mail roles without forced killing, then recreate
only the five mail/API roles. Verify health, image hash/MIME, unchanged send/retry
counts and restore the saved gates. Preserve the old image and private pre-cutover
runtime snapshot for rollback. Do not clear any safety hold or unknown receipt.

The 50-recipient regression first failed with a 13,400,587-byte response, then
passed after adding JPEG to the existing binary-image omission set. Supplemental
tests: 26 passed, one environment-dependent skip, one existing warning. The first
full-suite run was interrupted after 508 passed to include this final correction;
it was not treated as a completed suite. A fresh full run follows.

Wheel packaging with isolated build dependencies succeeded and contains the
original JPEG hash (the existing development environment lacks setuptools for
`--no-build-isolation`). Final production image `9f954dd1a6fc` passed offline MIME
validation with networking disabled. Its compact serializer source hash matches
the formatted workspace. The production pre-patch serializer matched HEAD before
replacement, so no separate production hotfix is overwritten.

Independent rollout review identified and verified fixes for two safeguards:
save/fsync prior runtime state **before** holding gates, then compare it under
the exclusive lock; verify every mail/API role uses the exact new image ID before
restoring gates. Registry, safety holds and historical unknown receipts are untouched.

## Final verification

- Fresh full isolated PostgreSQL/Redis suite: **579 passed, 1 skipped**, 660.77s.
  The skip is the opt-in Docker backup/restore rehearsal (`FMG_AGENT_TEST_IMAGE`
  unset); the image itself was separately tested offline on the target host.
  One pre-existing Starlette/AnyIO deprecation warning remains.
- Final focused template, compact batch, LIMINAL and Graph tests: 42 passed,
  one environment-dependent skip. Black and `git diff --check` pass.
- Isolated local PostgreSQL and Redis were shut down after testing.
- Final pre-cutover gate check: zero active sends/retries and zero pending
  outreach recipients. Both original runtime flags were true. Private restoration
  evidence is saved under
  `/etc/fmg-agent/multimail-20261017/thieves-footer-20261020/state.before.json`.
- Five mail/API roles were warm-stopped and recreated with exact image
  `9f954dd1a6fc`. The first release check correctly kept maintenance closed while
  both mail workers had not yet emitted readiness. Logs showed their initialization;
  a subsequent check passed for both workers, both mailbox monitor probes,
  dispatch, API and the exact role image IDs. No bypass or forced readiness.
- Release confirmed `thieves-outreach` v2, original JPEG checksum/MIME and unchanged
  send/retry counts, then restored `dispatch_enabled=true`, `send_enabled=true`.
  Sends remained sent 5370 / unknown 2 / failed 83; retries remained sent 2108 /
  unknown 1 / failed 32. No test send, queue replay or safety reset was performed.
- Gemini enrichment retained its pre-cutover image and was not restarted.
