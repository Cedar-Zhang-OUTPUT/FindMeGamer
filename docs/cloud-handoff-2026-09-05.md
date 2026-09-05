# Cloud internal Demo handoff — 2026-09-05

## Running deployment

- Origin: `https://44.233.174.193` (fixed EC2 Elastic IP, publicly trusted TLS).
- Instance: `i-041e77ab08c86ff1d`, `us-west-2`.
- Runtime commit: `6de8177494536d9db7bc1a05005b609d32fbad5d`.
- Services: API, Worker, Beat, PostgreSQL 17, Redis 7, Caddy 2.11.4.
- Database migration: `20260904_0007` (head).
- S3 bucket: `zhangyue-data-493392056671-us-west-2`.
- Daily database backup: 00:00 UTC / 08:00 Shanghai, systemd timer enabled.
- Reanalysis defaults: Creators every 14 days, Games every 30 days.

Only DeepSeek and YouTube credentials were imported from the local backend and
reencrypted with a new cloud master key. No local Profiles, jobs, Match history,
outreach records, or local database were imported. The new cloud Library now
contains the two real verification Profiles described below. Failed verification
attempts remain in task history for traceability.

See [deployment procedure](ec2-internal-demo.md) for maintenance-window updates,
the server's local Git-bundle mirror, protected configuration, and TLS renewal.
Test-only logging-fixture changes after the runtime commit do not change the
deployed application.

## Verified real flow

| Check | Evidence |
| --- | --- |
| DeepSeek and YouTube credentials | Both live connection probes succeeded |
| Steam Game analysis | Hades, job `612fd993-2058-4320-ade0-600c295b6c79`, succeeded |
| YouTube Creator analysis | Northernlion, job `c8afe692-848c-4fb0-a7ac-6f926c748554`, succeeded |
| Profile details | Both authenticated detail endpoints loaded successfully |
| Match | `f953082b-cff4-4b60-b822-df3940cb2ec6`, succeeded, one Creator result, `result_state=available` |
| API smoke | Health, session, settings, Library, jobs, Match, and read-only public response checks all passed |
| S3 acquisition storage | Real container Put and host Get succeeded using the EC2 role |
| Database backups | S3 upload and download succeeded; isolated restore rehearsal passed |
| Application regression | 398 analysis/worker/gateway tests passed with an isolated PostgreSQL database |
| Client artifact | Universal arm64/x86_64, macOS 14+, strict ad-hoc signature and DMG verification passed |

The restore rehearsal used a separate temporary database, which was removed
after verification; the application database was not restored over. Its source
backup was `backups/20260905T125145Z-cbbf82fc8e80-regular.dump`.
The final runtime deployment also created the pre-migration backup
`backups/20260905T130640Z-6de817749453-pre-migration.dump`.

The real Creator smoke test initially exposed list fields exceeding the existing
schema limits. The bounded fix adds explicit list selection instructions and
safe field-specific validation feedback to the existing single repair request.
It does not increase retry counts or remove validation. Independent review and
the real retry flow passed. Safe diagnostics omit keys and model output bodies.

## Client installation and first connection

Release: `v0.1.2-internal.1`, application version `0.1.2`.
Client source: `888f1f21cf8b89bbef396da37c23c4dc06fd97fb`.
The optimized UI is unchanged; this build switches the bundled service URL to
the cloud origin and uses real service mode, not mock data.
The DMG contains only the client; the later backend-only repair improvements run
on the server without changing the client API contract.

DMG SHA-256:
`77b9eff268bf3c04b1eccf50b1098cc6edcfdcc193234c17a45d50c417013547`.

1. Fully quit the old application and replace it in Applications with version
   0.1.2. This internal build is ad-hoc signed, not Developer ID signed or notarized.
   If macOS blocks opening it, use the system's per-application approval flow;
   do not globally disable Gatekeeper.
2. On **Connect to Find Me Gamer**, enter the cloud **Workspace Access Key** and
   select **Connect**. An old saved key is validated and, if invalid, cleared so
   the connection screen can accept the new key.
3. In **Settings → Workspace**, confirm **App Version** is `0.1.2`, **API Base URL**
   is `https://44.233.174.193`, and **Server Connection** is **Connected**.

The API URL is bundled, not editable in Settings. Old localhost preferences do
not override it. If localhost is displayed, check that the old app was replaced
and that the newly installed version is the one running.

Use **Settings → Workspace → Disconnect This Mac** to replace the saved workspace
key. This does not remove cloud data. Share the workspace key only with the
intended internal colleagues, through a private channel.

Operator recovery files are in the ignored, private local directory
`.local/cloud-deploy/credentials/`: `workspace.key`, `master.key`, and `app.env`.
Do not commit or attach these to GitHub. Preserve the master key separately in
private backup; it is required to decrypt provider configuration after restoration.

## Explicitly pending / known limitations

- **SMTP is not configured.** No real outreach mail was sent. Configure the
  enterprise mailbox and validate delivery to an approved test recipient before
  claiming real send / Yes-No response acceptance. Outreach management remains
  deployed; this is the agreed mailbox dependency, not removed functionality.
- **Google AI Studio is not configured.** Its key was not present in the local
  stored settings. Add it in **Settings → Connections → Google AI Studio →
  Replacement Gemini API Key → Replace Credential**, confirm, then **Test
  Connection**. This shared configuration enables the email-research fallback.
- **Vision is degraded for this verification.** A bounded live replay confirmed
  that DeepSeek returned HTTP 400 because it could not download a YouTube
  thumbnail from `i.ytimg.com`. The documented request format is supported; the
  existing nonfatal `unavailable` result was retained, and metadata-based analysis
  and Match completed. Do not describe these Profiles as having successful image
  analysis. An image-relay approach can be evaluated separately.
- Shanghai-to-US direct connections were intermittently slower than the smoke
  script's short connection timeout. The real authenticated API flow completed;
  colleagues may need their normal company proxy/VPN depending on their network.
- SSH port 22 is restricted to the operator's existing `/32` source rule, not
  opened globally. The temporary access rule can be removed through AWS when
  deployment access is no longer needed; the local MFA CLI session has expired.
- The instance role cannot inspect the bucket lifecycle policy. Actual S3
  read/write and backup behavior passed; the supplied 30-day acquisition/backup
  lifecycle configuration was not changed and no broader IAM was added.
