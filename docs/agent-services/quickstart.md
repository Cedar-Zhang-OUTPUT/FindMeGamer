# FMG CLI and Skills — pre-deployment guide

This build is prepared locally; no public CLI gateway or release is announced. The legacy macOS backend is intentionally stopped. Do not use an old client URL/token as if it were a new gateway credential.

## Install a prepared bundle locally

macOS/Linux arm64/amd64, Python 3.10+, and a shell are supported. The CLI itself has no runtime language dependency. From a verified downloaded release directory:

```sh
python3 install.py --release-dir . --skills
```

Default binary directory is `$HOME/.local/bin`; add it to PATH if needed. Skills go to `$HOME/.codex/skills`, with `--skill-dir` available for a different Codex runtime. Without `--skills`, only the binary is installed. Existing Skill versions are retained as `.previous` folders; move those backups outside the active Skills folder after verification before a subsequent upgrade. Reload Codex Skills if required. Installation cannot automatically inject a first conversation message.

After publication, the intended explicit-tag one-command bootstrap is:

```sh
curl -fsSL https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/fmg-v0.1.0/install.py | python3 - --tag fmg-v0.1.0 --skills
```

**This URL is a planned artifact location, not an existing download link.** For inspection before execution, download the installer and review it first. Asset URLs come from exact GitHub release metadata; binary/Skill archives are checked against SHA256SUMS. Checksums detect corruption, not a compromised release publisher. Unsigned macOS binaries may require normal local approval; no automatic Gatekeeper disabling is performed.

## Authenticate

Administrator provides the new verified HTTPS gateway and personal revocable token separately. Never paste provider/SMTP credentials in an Agent chat or command argument. Pipe the token privately into:

```sh
fmg auth login --server https://YOUR-VERIFIED-GATEWAY --token-stdin
fmg auth check
fmg version
```

Configuration is mode 0600; `auth logout` removes it locally. Server-side revocation is separate. Remote HTTP is rejected. Read access is default; enrichment and sending need `email:enrich` and `email:send` scopes.

## Ask Codex

“Use fmg-research to find suitable English-speaking creators for this Steam game on YouTube and X. Save the evidence locally; do not send mail.”

“Find more new creators for the same game, excluding everyone previously seen.”

“Explain why this creator was matched using our saved evidence.”

“Draft outreach for these three creators and show me the recipients and messages.”

The workflow defaults to a bounded target and announces its request budget. It saves a game Markdown profile, JSON matches and evidence, progress and a local identity index. Missing geography/contact information stays unknown. Email lookup failure is distinct from Not Found. Drafting is not permission to send.

## Costs, updates and limits

Use `fmg --run-id RUN_ID ...` and `fmg --run-id RUN_ID usage`. Request counts and available Gemini tokens are measured; monetary costs are currently unknown. YouTube quota estimates cite their dated source and are not money. Codex shared-account usage does not measure one task.

`fmg upgrade --tag fmg-vX.Y.Z` replaces only the CLI after verification; Skills remain unchanged. Re-run the matching installer with `--skills` to update both. A failed checksum keeps the existing binary. Public GitHub downloads, provider authorization and company SMTP are separate rollout checks, not proven by local fixtures.

Only YouTube/X/Steam API reads, public business email enrichment and templated sends are included. No legacy Library/Match database, social platform writes, Instagram/Twitch API, reply ingestion, Yes/No callbacks or attachment sending is claimed.
