# No Rest for Thieves dedicated outreach template

## Approved design

Source: [《熬夜神偷》pitch邮件](https://k1mai98sti.feishu.cn/wiki/LVDkw4GI0iCCeWkplq8cGepfn1b),
document revision 199, read on 2026-10-20.

The user approved replacing `I loved how you [specific observation]` with a
complete-sentence variable. The remaining pitch is fixed. The Outlook Safe Links
wrapper is replaced by the document's visible direct Steam link; no tracking
parameters or email-specific metadata are propagated. Whitespace between document
blocks is normalized to paragraphs. No images were supplied for this template.

| Item | Value |
| --- | --- |
| Mailbox | `second` |
| Sender | `norestforthieves@ontologyplay.com` |
| Display name | `No Rest for Thieves Team` |
| Template | `thieves-outreach` |
| Version | `1` |
| Variables | `creator_name`, `channel_name`, `reference_work`, `specific_observation` |
| Signature | Michael / No Rest for Thieves Team |
| Format | Plain text |

The template guard requires the exact mailbox ID and case-insensitive sender
match in addition to the normal allowlist. LIMINAL version 7 and generic version 5
are unchanged. Existing frozen drafts are not rewritten. The second mailbox's
allowlist becomes exclusively `thieves-outreach`; older generic drafts, if any
appear, must not be silently rewritten or sent.

## CLI usage

Existing CLI 0.8.0 supports the change through its dynamic template catalog:

```sh
fmg email mailboxes
fmg email template thieves-outreach
```

Prepare draft/task JSON with these selections:

```json
{
  "mailbox_id": "second",
  "template_id": "thieves-outreach",
  "template_version": "1"
}
```

Use factual creator evidence for all four required variables. Observation must
contain complete sentences and punctuation, not a verb fragment. Names must not be
invented. Keep the approved fixed title/body/signature. Existing preview, approval,
idempotency and confirmation flows remain mandatory; enrollment is not permission
to send a campaign.

## Verification and deployment approach

Expected RED: 10 failed, 1 passed before adding the template/guard (missing catalog
entry and missing cross-mailbox protection). Tests cover exact rendered pitch,
required/extra variables, invalid mailbox/sender pairs, catalog coexistence, API
discovery, frozen sender, and preview creation without a send attempt.

The initial bare suite produced 494 passed, 67 skipped and 14 setup errors due to
missing local PostgreSQL/Redis environment variables. A fresh isolated native
PostgreSQL database and Redis namespace were then provisioned for the full suite.
Neither service connects to production. Final results are recorded below.

Independent read-only review approved the scoped code and tests without findings.
CLI Go tests passed. Black and `git diff --check` passed. An offline network-disabled
container verified catalog, binding, and rendering.

Production image `fmg-agent:thieves-template-20261020` is derived from the current
multi-mailbox image, copying only `templates.py` and the new JSON. Production's
original template module hash matched the checked-in baseline before building.
Enrichment retains `fmg-agent:gemini429-20261020`; no diagnostic/provider change is
rolled back or bundled accidentally.

Server override: `/opt/fmg-thieves-template-20261020/compose.yaml`, applied last
after the base, Gemini worker-diagnostics, and second-mailbox overrides. Safe
cutover holds/drains the runtime gates, preserves private registry/runtime
snapshots, refuses active/uncertain in-progress sends or existing second previews,
warm-stops mail roles without SIGKILL, and compares send/retry state counts before
restoring the original gates. Historical unknown receipts and sender safety states
are never cleared. No test email is sent.

## Verified result — 2026-10-20

- Full isolated PostgreSQL/Redis backend suite: **575 passed, 1 skipped**, one
  pre-existing Starlette/AnyIO deprecation warning, 674.33 seconds.
- Isolated local PostgreSQL and Redis were shut down after the suite.
- Cutover observed **zero active sends/retries**, zero second-mailbox previews.
- The five mail/API roles were warm-stopped and recreated with the new image.
  Both mailbox workers, both monitor probes, dispatch and API health passed before
  restoring the original `dispatch_enabled=true`, `send_enabled=true`.
- Send counts remained sent 5370 / unknown 2 / failed 83; bounce retry counts
  remained sent 2108 / unknown 1 / failed 32. No send attempt was created.
- Second mailbox discovery is enabled/ready with exclusive `thieves-outreach`
  permission and display name `No Rest for Thieves Team`. The first mailbox still
  permits LIMINAL and generic templates. The disabled legacy mailbox is unchanged.
- CLI 0.8.0 uses the new server catalog without a binary change. README and Skill
  source guidance are updated separately; no new downloadable CLI/Skill release
  is implied by this server-only deployment.
- Both Skills were baseline-tested: old routing incorrectly selected generic
  outreach for Thieves and conflicted with the second mailbox allowlist. After
  scoped guidance edits, independent application tests selected the correct
  identity/template, preserved four-variable/plain-text rules and the approval
  boundary, and correctly kept LIMINAL when Thieves was only a creator's reference
  work. Both Skill validators passed.
- Isolated CLI mailbox examples and gateway smoke passed (fake transports only).
  Production hashes of all three template JSON files match the tested workspace.
  Enrichment container retained its original diagnostics image and was not restarted.
