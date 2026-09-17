# Plain-text and IMAP deployment — 2026-09-17

- Source `15d8c1a`, image `fmg-agent:inbox-15d8c1a`, checkout
  `/opt/fmg-agent-inbox-15d8c1a` on the existing EC2 instance.
- Confirmed no queued/running enrichment, active SMTP sends or approved pending
  recipients before maintenance. Stopped only the agent API and Worker.
- Backup: `/var/backups/find-me-gamer-agent/inbox-15d8c1a-20260917/`, containing
  private configuration and `agent.dump`. Dump uploaded to the existing bucket's
  `backups/agent/inbox-15d8c1a-20260917.dump`.
- Migrated `0006_outreach` -> `0007_inbox`. Existing counts preserved before the
  new test: 65 enrichment jobs, two sends, two tasks and two task recipients.
  Retired callback columns intentionally removed; rollback requires backup.
- API healthy, Worker running. Public template endpoint returns Liminal Outreach
  version 2, plain_text, without HTML. Retired response endpoint returns 404.
- IMAP TLS host `imap.qiye.aliyun.com:993`, INBOX, 60-second polling and 30-day
  initial lookback. Reuses the existing authorized client credential privately;
  monitor reached active with successful cloud synchronization.
- SMTP allowlist still only `yifan.zhang@byoutput.com`.
- User explicitly authorized one test email. Created task
  `b9cf060a-7844-4f76-aba3-6469eb5c8496`, stable key
  `imap-plaintext-yifan-20260917-001`, run `imap-plaintext-test-20260917`.
  Template Liminal Outreach v2, sample personalization clearly marked internal
  test. Task completed: sent=1, failed=0, unknown=0, pending=0.
- Real recipient reply acceptance is pending the user's reply. SMTP acceptance
  alone does not prove inbox placement or reply ingestion.
- Current local dashboard uses updated source. No new GitHub CLI/Skill release
  was published as part of this service deployment; existing CLI task commands
  work with the updated API. Restart/update old dashboard Skills before using the
  new reply fields.
