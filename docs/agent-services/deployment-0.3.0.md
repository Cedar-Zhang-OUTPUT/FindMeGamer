# CLI/gateway 0.3.0 deployment — 2026-09-16

User approved deployment after the Twitch development checkpoint.

- Source: `99dabda`, branch `cli`, release `fmg-v0.3.0` (internal prerelease,
  not the repository's desktop latest release).
- Gateway: `https://44.233.174.193`; image `fmg-agent:0.3.0-99dabda`;
  checkout `/opt/fmg-agent-0.3.0-99dabda`.
- Existing API and Worker upgraded in a maintenance window. Legacy desktop
  services remain stopped; Postgres, Redis and proxy were not replaced.
- No running email jobs at cutoff. Existing counts retained: completed 38,
  failed 27. No business records deleted; no email sent.
- Pre-upgrade PostgreSQL dump:
  `/var/backups/find-me-gamer-agent/upgrade-0.3.0-99dabda/agent-20260916T083218Z.dump`,
  copied to the existing S3 `backups/agent/` prefix.
- Prior private env preserved at `/etc/fmg-agent/service.env.before-0.3.0-99dabda`.
  Twitch credentials transferred from Keychain privately, not committed.
- Persistent named volume `fmg-agent_twitch-oauth`, directory mode 0700,
  owner/group 10001. Initial user token is valid; the 0600 token file will be
  created on first refresh. Live refresh was not forced; rotation/restart tests
  used mock provider responses. Preserve this volume and back up its private
  contents once written, separately from PostgreSQL dumps.
- Public HTTPS health and existing auth/Steam catalog/templates passed.
- Real production Twitch calls: getGames, searchCategories, getStreams,
  getVideos, getUsers, getChannelInformation, getChannelFollowers, getClips.
  All 8 succeeded, attributed to `deploy-twitch-0.3.0-20260916`; ledger reports
  8 requests, estimated marginal USD 0, actual cost unknown. Follower endpoint
  returned a total with an empty detailed list, as intended.
- Four CLI binary archives, two-Skill archive, installer and SHA256SUMS published.
  No provider secret is included in the artifacts.

Rollback retains image `fmg-agent:0.2.1-3461e7f` and its checkout; no database
migration was introduced. Keep the new OAuth volume and backups even if rolling
back. Do not restore or erase databases as a routine image rollback.
