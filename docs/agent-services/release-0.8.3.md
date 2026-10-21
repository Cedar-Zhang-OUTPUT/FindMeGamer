# FMG CLI / Skills 0.8.3 — LIMINAL Private Email migration

User-authorized scope, 2026-10-21: move new LIMINAL work to Private Email,
retain historical Hotmail records but stop its sending and monitoring, update
CLI/Skills, and leave No Rest sending unchanged. No test messages, batch starts,
resends, approval transfers or paid enrichment are part of this migration.

## Identity and content

- New mailbox `liminal`, From `liminal_within@ontologyplay.com`, display name
  `Ontology Play`; SMTP/IMAP credentials are administrator-managed and private.
- New template `liminal-private-outreach`, string version `1`. Four existing
  personalization variables remain; old v7 rendered subject, fixed body and both
  inline images are identical except the signature email address.
- Historical `ontologyplay` / `ontologyplay@hotmail.com` is disabled, not renamed.
  Old templates, immutable drafts, approvals, receipts, uncertain attempts and
  sender holds retain their original identity. Monitoring stops for this mailbox.
- No Rest `second` / `thieves-outreach` and disabled `legacy-byoutput` are unchanged.
- New LIMINAL has its own two-slot queue, shared five-second pacing, existing
  bounce protection, INBOX/Spam monitoring and Sent-copy archiving. This does not
  assert any provider sending quota or guaranteed inbox delivery.

## Agent contract

Discover current mailbox/template state before creating drafts. For new LIMINAL:

```sh
fmg email mailboxes
fmg email template liminal-private-outreach
fmg --run-id RUN_ID outreach task create --input batch.json --mailbox liminal --template liminal-private-outreach --template-version 1 --idempotency-key STABLE_KEY
```

Do not change the identity of an old task or reuse its approval. Verified
never-attempted rows may form a fresh draft after confirming the old mailbox is
disabled; exclude sent, accepted, unknown and in-flight attempts. Confirmed failed
rows need separate resend approval. Every replacement needs fresh content review
and explicit sending approval. Existing holds are not cleared by migration.

The release reuses existing CLI selection/protocol support, updates its offline
mailbox acceptance fixture and publishes all four binaries with the synchronized
Skills. No client-side automatic send/retry is introduced.

## Verification and deployment record

- New regression tests first failed before implementation, then passed: exact
  rendered-copy/image equivalence, identity/address rejection, historical draft
  preservation, disabled old send and fresh unapproved new task with zero sends.
- Independent code review required initialized role readiness, not merely running
  containers. The cutover verifier now waits for API health, dispatcher, new mail
  worker and both active mailbox monitors; it checks old monitor absence.
- Skill consumption tests distinguished never-attempted migration from failed
  resend and unknown/in-flight delivery. Five conflicting/stale instructions were
  corrected; read-only re-review passed. Both Skill validators passed.
- SMTP authentication and IMAP read-only selection of INBOX, Spam and Sent passed
  from the production host, without sending a message or reading message bodies.
- Native PostgreSQL 17 / Redis 8.10.1 full regression completed with 599 passing,
  one optional image-rehearsal skip and one stale collected parameter: that process
  had imported the old template-copy test before it was changed to the new template.
  A fresh run of all unified-template and migration tests passed all 13, covering
  the corrected parameter. Combined current coverage: 600 passing, one optional
  image-rehearsal skip; existing AnyIO deprecation warning only. The earlier run
  with an incorrectly named isolated test database was not acceptance evidence.
- Go tests/vet passed; compiled CLI fixture passed all six selection/immutability
  checks. All four actual installer/bundle tests passed. The production image
  passed offline rendering equivalence with networking disabled; its IMAP parser
  hash still matches the 0.8.2 fix. Preflight caught and corrected the image's
  installed-package copy path and file permissions before any live switch.

Deployment files and restricted rollback snapshots are held at
`/opt/fmg-liminal-private-20261021/`. The overlay must remain last after the
existing IMAP fix overlay in future Compose operations. Registry snapshots contain
credentials and must not be published. Registry updates preserve the bind-mounted
inode; history and queue rows are not rewritten or purged.

The preflight includes all Compose profiles and resolves image-default commands
when Compose has a null command. It checks environment, volumes, networks and
unchanged-role images before any live modification. The cutover gracefully stops
API admission, dispatcher, old primary mail worker and monitor; it never stops or
recreates the second mail worker or enrichment worker. A brief API/status-query
interruption is expected; No Rest's worker stays running. The CLI's bounded read
recovery instructions remain applicable.

Upgrade clients using `fmg upgrade --latest --skills`, then verify `fmg version`
and `fmg auth check` and reload both installed Skills. Old drafts are history, not
permission to send again from the new account.
