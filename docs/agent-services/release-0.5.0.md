# FMG CLI 0.5.0 — Plain-text outreach and real replies

Upgrade CLI and both Skills together:

```sh
fmg upgrade --latest --skills
fmg version
fmg auth check
fmg email template liminal-outreach
```

Then reread installed `fmg-api` and `fmg-research` Skills and their email/outreach
references. Start a new Agent conversation if its Skill instructions are cached.
Restart existing local dashboards to load the updated page. Authentication is
preserved; an upgrade does not authorize any search or sending.

## Changes

- Plain-text email only. No HTML/Markdown rendering or Yes/No callbacks.
- Real IMAP reply monitoring, recipient isolation, duplicate protection, separate
  automatic reply/bounce states, human reply rate and mailbox-monitor health.
- Read-only dashboard with plain-text previews and recorded reply details.
- Liminal Outreach server template version 3, `Internal Test —` subject prefix.
  Fetch current versions/variables instead of copying stale examples. Custom
  CLI subject overrides are not implemented.
- Approved recipient allowlist remains enforced. This release does not grant
  token scopes or permission to mail arbitrary recipients.
- Updated public installation guide, including current SMTP/IMAP behavior.

Existing command names remain unchanged. Previously generated drafts retain their
snapshots; create and approve fresh drafts to get the updated subject. Unknown
delivery must never be automatically resent. Reply does not mean acceptance or
completed cooperation. Local/SMTP tests do not prove inbox placement; real reply
acceptance depends on mailbox matching and monitor health.

Contains macOS/Linux arm64 and amd64 binaries, both Skills, installer and SHA256
checksums. Internal prerelease; no emails are sent by installation or upgrade.
