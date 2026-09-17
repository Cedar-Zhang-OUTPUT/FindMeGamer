# Liminal signature update — 2026-09-17

- Source/image: `b354f2a` / `fmg-agent:signature-b354f2a`.
- Checkout: `/opt/fmg-agent-signature-b354f2a`; API and Worker healthy.
- Backup: `/var/backups/find-me-gamer-agent/signature-b354f2a/agent.dump`.
- No schema or configuration changes; previous image remains available.
- Liminal Outreach v4 changes only the signature: Kind regards, Toki Yuan,
  Game Producer, Ontology Play, Email: OntologyPlay@hotmail.com, and the
  document's Ontology Play PNG. Title and preceding body verified unchanged.
- User approved minimal HTML solely for the inline signature image. Text fallback
  remains; image uses CID and is snapshotted with the draft, with no remote fetch.
  No Yes/No controls or callback routes restored.
- Regression: 146 passed, 1 skipped. Deployed MIME verified with mocked SMTP;
  existing send count remains three. No real email sent during this deployment.
- Existing immutable drafts remain unchanged. Fetch the current template and
  create new drafts to use v4. Existing CLI commands work without upgrade.
- CLI 0.5.0's read-only dashboard shows the text fallback, not the inline logo;
  its plain-text-only instructions predate this explicitly approved exception.
