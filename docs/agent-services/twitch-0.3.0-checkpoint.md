# Twitch CLI 0.3.0 — pre-deployment checkpoint

2026-09-16. Source implementation and local verification only; production remains
0.2.1 until a separate deployment/release. No production credentials, data or
services were changed by this development task.

## Delivered

- `fmg twitch operations|describe|call`, full JSON field passthrough, repeated query
  parameters and bounded cursor pagination using the existing CLI conventions.
- Official reference snapshot catalog: 76 GET operations, 24 enabled public/total
  reads, 47 extra-authorization reads blocked, 5 unsupported. No social writes.
- Server-managed App tokens and User OAuth for follower totals; startup/hourly
  validation, serialized acquisition, user refresh and persistent private rotation.
- Twitch response rate limits and reset delays; zero marginal Helix USD estimate
  under current assumptions, actual charge unknown; existing per-run ledger.
- Updated API and research Skills: unspecified platforms = YouTube/X/Twitch;
  unspecified count = 10 supported matches per selected platform, hence default
  30. Explicit counts override this; missing matches are reported, not padded.
- Public country/email limitations, creator-vs-clipper distinction, content
  evidence requirements, enrichment, quotas and billing recovery documented.

## Verification

- Backend pytest: 123 passed, 3 existing opt-in environment tests skipped; Go
  tests/vet passed; compiled CLI → actual loopback HTTP
  gateway → simulated Twitch OAuth/Helix two-page flow and usage ledger.
- Both Skills pass the Skill Creator validator. Existing local workspace identity
  already supports Twitch IDs; no file schema migration was needed.
- Real local gateway calls succeeded for getGames, getStreams, getVideos,
  getUsers (4-account batch), getChannelInformation, getChannelFollowers (total
  present; follower list empty as expected), getClips. Seven Helix reads per run,
  repeated once after correcting the smoke harness's missing usage query parameter:
  14 successful Helix calls in total, estimated marginal USD 0, no paid X/Gemini/
  YouTube requests and no email. The corrected run also verified ledger count 7.
- Live User OAuth refresh was deliberately not triggered: existing credentials
  were validated/read only. Expiry, rotation, file permissions and restart recovery
  are covered by mock-provider tests, not claimed as live-verified.

## Release checklist

1. Build/publish matching 0.3.0 API image and CLI/Skill assets only after deployment
   approval. No database migration is introduced by this feature.
2. Transfer company Twitch credentials privately from Keychain; never put them
   in CLI assets, command arguments, Git or logs. Configure the API's persistent
   token store described in agent-service README. Preserve its volume on upgrades.
3. Run one API process/container for token ownership. Confirm mounted directory
   uid 10001, mode 0700; rotated token file 0600. Back up OAuth state privately;
   existing PostgreSQL backups do not contain this file.
4. Verify real company-gateway public reads and follower totals, health, existing
   YouTube/X/Steam catalogs and run accounting. Do not send email as a smoke test.
5. Update public install guide to the published release, upload checksummed assets
   and source to `cli`, then verify `fmg upgrade --latest --skills` from 0.2.1.

The new local release bundle is `/tmp/fmg-release-0.3.0-twitch`; it has not been
uploaded. Installing it against the old gateway does not enable Twitch there.
